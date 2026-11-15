"""Dispatcher actions: one-click Red Alert confirmation, brigade release, alert list, overview."""
import threading
import time
from datetime import datetime

from sqlalchemy import case, func, select, update
from sqlalchemy.orm import Session

from .. import config
from ..models import SOS, Alert, Brigade, Shelter
from ..schemas import OverviewOut
from . import geo
from . import sos as sos_svc
from .clock import utcnow
from .routing_provider import routing_status
from .spam import spam_filter


class AlertNotFound(Exception):
    pass


class AlertAlreadyConfirmed(Exception):
    pass


def _dist_to(lat: float, lon: float):
    return lambda la, lo: geo.haversine_m(lat, lon, la, lo)


def _nearest_available_brigade(db: Session, lat: float, lon: float) -> Brigade | None:
    dist = _dist_to(lat, lon)

    def key(b: Brigade) -> float:
        z = geo.zone_by_id(b.zone_id)  # brigade location = home zone centre
        return dist(z.lat, z.lon) if z else float("inf")

    return min(db.scalars(select(Brigade).where(Brigade.status == "available")), key=key, default=None)


def _open_assembly_point(db: Session, alert: Alert) -> Shelter:
    """Open the nearest closed reserve shelter, or create a temporary one at the zone centre."""
    dist = _dist_to(alert.lat, alert.lon)
    reserves = db.scalars(select(Shelter).where(Shelter.is_reserve.is_(True), Shelter.is_open.is_(False))).all()
    if reserves:
        shelter = min(reserves, key=lambda s: dist(s.lat, s.lon))
        shelter.is_open = True
        return shelter
    zone = geo.zone_by_id(alert.zone_id) if alert.zone_id else geo.nearest_zone(alert.lat, alert.lon)
    lat, lon = (zone.lat, zone.lon) if zone else (alert.lat, alert.lon)
    shelter = Shelter(name=f"Temporary Assembly Point {zone.name if zone else alert.id}", type="assembly_point",
                      lat=lat, lon=lon, capacity=config.TEMP_SHELTER_CAPACITY, current=0,
                      zone_id=zone.id if zone else alert.zone_id, is_open=True, is_accessible=True,
                      is_temporary=True)
    db.add(shelter)
    db.flush()
    return shelter


def confirm_alert(db: Session, alert_id: int, now: datetime | None = None):
    """One transaction: claim alert -> dispatch nearest brigade -> open assembly point. Returns (alert, brigade, shelter)."""
    now = now or utcnow()
    claimed = db.execute(update(Alert).where(Alert.id == alert_id, Alert.status == "open")
                         .values(status="confirmed", confirmed_at=now))
    if claimed.rowcount == 0:
        db.rollback()
        if db.get(Alert, alert_id) is None:
            raise AlertNotFound(alert_id)
        raise AlertAlreadyConfirmed(alert_id)
    alert = db.get(Alert, alert_id)
    db.refresh(alert)

    brigade = _nearest_available_brigade(db, alert.lat, alert.lon)
    if brigade is not None:
        brigade.status, brigade.target_zone_id, brigade.alert_id = "dispatched", alert.zone_id, alert.id
    shelter = _open_assembly_point(db, alert)

    alert.brigade_id = brigade.id if brigade else None
    alert.brigade_shortage = brigade is None
    alert.new_shelter_id = shelter.id
    db.commit()
    return alert, brigade, shelter


def release_brigade(db: Session, brigade_id: int) -> Brigade | None:
    brigade = db.get(Brigade, brigade_id)
    if brigade is None:
        return None
    brigade.status, brigade.target_zone_id, brigade.alert_id = "available", None, None
    db.commit()
    return brigade


def list_alerts(db: Session, status: str | None = None, confirmed_limit: int | None = None) -> list[Alert]:
    """Open alerts first, then newest first."""
    order = (case((Alert.status == "open", 0), else_=1), Alert.created_at.desc(), Alert.id.desc())
    if status:
        return list(db.scalars(select(Alert).where(Alert.status == status).order_by(*order)))
    open_ = list(db.scalars(select(Alert).where(Alert.status == "open").order_by(*order)))
    confirmed = select(Alert).where(Alert.status == "confirmed").order_by(Alert.confirmed_at.desc(), Alert.id.desc())
    if confirmed_limit is not None:
        confirmed = confirmed.limit(confirmed_limit)
    return open_ + list(db.scalars(confirmed))


def overview(db: Session) -> dict:
    """Dispatcher snapshot. Suspected spam is excluded everywhere; the SOS list is capped, totals are exact."""
    not_spam = (SOS.status == "active", SOS.suspected_spam.is_(False))
    critical = case((SOS.priority == config.SOS_PRIORITY_CRITICAL, 1), else_=0)
    counts = {zid: (n, p) for zid, n, p in db.execute(
        select(SOS.zone_id, func.count(), func.sum(critical)).where(*not_spam).group_by(SOS.zone_id))}
    zones = [dict(id=z.id, name=z.name, active_sos=counts.get(z.id, (0, 0))[0],
                  priority_sos=int(counts.get(z.id, (0, 0))[1] or 0)) for z in geo.zones()]
    return dict(
        sos=sos_svc.list_sos(db, status="active", limit=config.OVERVIEW_SOS_LIMIT),  # priority first, newest first
        sos_total=sum(n for n, _ in counts.values()),
        sos_priority_total=sum(int(p or 0) for _, p in counts.values()),
        spam_blocked=spam_filter.snapshot(),
        shelters=list(db.scalars(select(Shelter).order_by(Shelter.id))),
        brigades=list(db.scalars(select(Brigade).order_by(Brigade.id))),
        alerts=list_alerts(db, confirmed_limit=config.OVERVIEW_RECENT_CONFIRMED),
        zones=zones,
        routing=routing_status(db),
    )


class _OverviewCache:
    """Serialized overview JSON reused for OVERVIEW_CACHE_TTL_S (many dispatchers polling during a flood)."""

    def __init__(self):
        self._lock = threading.Lock()
        self._at = 0.0
        self._body: bytes | None = None

    def fresh(self) -> bytes | None:
        with self._lock:
            if self._body is not None and time.monotonic() - self._at < config.OVERVIEW_CACHE_TTL_S:
                return self._body
        return None

    def get(self, db: Session) -> bytes:
        cached = self.fresh()
        if cached is not None:
            return cached
        now = time.monotonic()
        body = OverviewOut.model_validate(overview(db)).model_dump_json().encode()
        with self._lock:
            self._body, self._at = body, now
        return body

    def invalidate(self) -> None:
        with self._lock:
            self._body = None


overview_cache = _OverviewCache()
