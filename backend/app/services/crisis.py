"""Critical Crisis Algorithm: Red Alert detection. Thresholds come from config.py.

Rules are pure functions (find_sos_cluster, is_overflowing) so they can be unit-tested with fake
timestamps; on_sos_created / on_shelter_updated wrap them with DB access and alert de-duplication.
Times are naive UTC (services.clock.utcnow).
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..models import SOS, Alert, Shelter
from ..schemas import occupancy_pct
from .clock import utcnow
from .geo import haversine_m

SOS_CLUSTER = "sos_cluster"
SHELTER_OVERFLOW = "shelter_overflow"

AlertEvent = tuple[str, Alert]  # ("alert_created" | "alert_updated", alert)


# --- pure rules ---------------------------------------------------------------

def find_sos_cluster(new, active, now: datetime) -> list | None:
    """Rule 1. `new` and items of `active` need: id, citizen_id, lat, lon, zone_id, status, priority, created_at.

    Counts active SOS from the last SOS_CLUSTER_WINDOW_MIN minutes that are in the same zone as `new`
    OR within SOS_CLUSTER_RADIUS_M of it. Returns the members (one per citizen, newest) if the number of
    distinct citizens >= SOS_CLUSTER_COUNT, else None.
    """
    since = now - timedelta(minutes=config.SOS_CLUSTER_WINDOW_MIN)
    candidates = list(active)
    if all(s.id != new.id for s in candidates):
        candidates.append(new)
    latest: dict[str, object] = {}
    for s in candidates:
        if s.status != "active" or s.created_at < since:
            continue
        same_zone = new.zone_id is not None and s.zone_id == new.zone_id
        if same_zone or haversine_m(new.lat, new.lon, s.lat, s.lon) <= config.SOS_CLUSTER_RADIUS_M:
            cur = latest.get(s.citizen_id)
            if cur is None or (s.created_at, s.id) > (cur.created_at, cur.id):
                latest[s.citizen_id] = s
    if len(latest) < config.SOS_CLUSTER_COUNT:
        return None
    return sorted(latest.values(), key=lambda s: s.id)


def is_overflowing(current: int, capacity: int) -> bool:
    """Rule 2: occupancy strictly above ALERT_OCCUPANCY_PCT (same rounding as the API)."""
    return occupancy_pct(current, capacity) > config.ALERT_OCCUPANCY_PCT


def cluster_summary(members: list) -> dict:
    return dict(
        lat=sum(s.lat for s in members) / len(members),
        lon=sum(s.lon for s in members) / len(members),
        sos_count=len(members),
        sos_ids=[s.id for s in members],
        has_priority_sos=any(s.priority == config.SOS_PRIORITY_CRITICAL for s in members),
    )


# --- DB wrappers --------------------------------------------------------------

def _zone_filter(zone_id):
    return Alert.zone_id.is_(None) if zone_id is None else Alert.zone_id == zone_id


def on_sos_created(db: Session, sos: SOS, now: datetime | None = None) -> AlertEvent | None:
    """HOOK called after every SOS create/refresh. Creates or grows the zone's open sos_cluster alert."""
    now = now or utcnow()
    since = now - timedelta(minutes=config.SOS_CLUSTER_WINDOW_MIN)
    active = db.scalars(select(SOS).where(SOS.status == "active", SOS.created_at >= since)).all()
    members = find_sos_cluster(sos, active, now)
    if not members:
        return None
    summary = cluster_summary(members)

    base = select(Alert).where(Alert.kind == SOS_CLUSTER, _zone_filter(sos.zone_id))
    existing = db.scalar(base.where(Alert.status == "open"))
    if existing is not None:
        if summary["sos_count"] <= existing.sos_count and set(summary["sos_ids"]) <= set(existing.sos_ids):
            return None
        for k, v in summary.items():
            setattr(existing, k, list(v) if k == "sos_ids" else v)  # new list: JSON column change tracking
        existing.has_priority_sos = existing.has_priority_sos or summary["has_priority_sos"]
        db.commit()
        return "alert_updated", existing

    # Already handled: a confirmed alert for this zone inside the window -> don't re-alert the same incident.
    if db.scalar(base.where(Alert.status == "confirmed", Alert.confirmed_at >= since)) is not None:
        return None

    alert = Alert(kind=SOS_CLUSTER, zone_id=sos.zone_id, **summary)
    return _insert(db, alert)


def on_shelter_updated(db: Session, shelter: Shelter, previous_current: int | None = None) -> AlertEvent | None:
    """Called after a shelter's occupancy changes. Alert only when crossing above the threshold."""
    if not is_overflowing(shelter.current, shelter.capacity):
        return None
    if previous_current is not None and is_overflowing(previous_current, shelter.capacity):
        return None  # was already over the threshold
    open_q = select(Alert).where(Alert.kind == SHELTER_OVERFLOW, Alert.shelter_id == shelter.id,
                                 Alert.status == "open")
    if db.scalar(open_q) is not None:
        return None
    alert = Alert(kind=SHELTER_OVERFLOW, zone_id=shelter.zone_id, shelter_id=shelter.id,
                  lat=shelter.lat, lon=shelter.lon, sos_count=0, sos_ids=[], has_priority_sos=False)
    return _insert(db, alert)


def _insert(db: Session, alert: Alert) -> AlertEvent | None:
    db.add(alert)
    try:
        db.commit()
    except IntegrityError:  # a concurrent request created the open alert first
        db.rollback()
        return None
    return "alert_created", alert
