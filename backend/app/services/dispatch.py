"""Dispatcher actions: one-click Red Alert confirmation, brigade release, alert list, overview."""
from datetime import datetime

from sqlalchemy import case, select, update
from sqlalchemy.orm import Session

from .. import config
from ..models import Alert, Brigade, Shelter
from . import geo
from . import sos as sos_svc
from .clock import utcnow
from .routing_provider import active_provider


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
    active = sos_svc.list_sos(db, status="active")  # priority first, newest first
    zones = [dict(id=z.id, name=z.name,
                  active_sos=sum(1 for s in active if s.zone_id == z.id),
                  priority_sos=sum(1 for s in active if s.zone_id == z.id
                                   and s.priority == config.SOS_PRIORITY_CRITICAL))
             for z in geo.zones()]
    return dict(
        sos=active,
        shelters=list(db.scalars(select(Shelter).order_by(Shelter.id))),
        brigades=list(db.scalars(select(Brigade).order_by(Brigade.id))),
        alerts=list_alerts(db, confirmed_limit=config.OVERVIEW_RECENT_CONFIRMED),
        zones=zones,
        routing=dict(external_up=config.EXTERNAL_ROUTING_UP, active_provider=active_provider()),
    )
