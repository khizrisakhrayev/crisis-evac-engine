from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import config
from ..models import SOS
from ..schemas import SOSCreate
from . import geo
from .clock import utcnow


def _active_for(db: Session, citizen_id: str) -> SOS | None:
    return db.scalar(select(SOS).where(SOS.citizen_id == citizen_id, SOS.status == "active"))


def submit_sos(db: Session, data: SOSCreate, priority_citizen: bool = False, suspected_spam: bool = False,
               source_ip: str | None = None) -> SOS:
    """Create an SOS, or refresh the citizen's existing active one (one active SOS per citizen).

    Priority comes from the caller's role only (never the body): priority citizens get CRITICAL.
    A refresh never downgrades an existing active SOS's priority.
    """
    zone = geo.nearest_zone(data.lat, data.lon)
    priority = config.SOS_PRIORITY_CRITICAL if priority_citizen else config.SOS_PRIORITY_NORMAL
    fields = dict(lat=data.lat, lon=data.lon, hazard_type=data.hazard_type,
                  zone_id=zone.id if zone else None, created_at=utcnow())
    for _ in range(2):  # retry once if a concurrent request inserted the active SOS first
        sos = _active_for(db, data.citizen_id)
        if sos is None:
            sos = SOS(citizen_id=data.citizen_id, status="active", priority=priority,
                      is_priority_citizen=priority_citizen, suspected_spam=suspected_spam,
                      source_ip=source_ip, **fields)
            db.add(sos)
        else:
            for k, v in fields.items():
                setattr(sos, k, v)
            sos.priority = min(sos.priority, priority)
            sos.is_priority_citizen = sos.is_priority_citizen or priority_citizen
        try:
            db.commit()
            return sos
        except IntegrityError:
            db.rollback()
    raise RuntimeError("could not upsert SOS")


def mark_safe(db: Session, sos_id: int) -> SOS | None:
    sos = db.get(SOS, sos_id)
    if sos is None:
        return None
    sos.status = "safe"
    db.commit()
    return sos


def list_sos(db: Session, status: str | None = None, zone_id: int | None = None,
             priority: int | None = None, include_spam: bool = False, limit: int | None = None) -> list[SOS]:
    """Most urgent first (priority asc), then newest first. Suspected spam excluded unless asked for."""
    q = select(SOS).order_by(SOS.priority.asc(), SOS.created_at.desc(), SOS.id.desc())
    if not include_spam:
        q = q.where(SOS.suspected_spam.is_(False))
    if limit is not None:
        q = q.limit(limit)
    if status:
        q = q.where(SOS.status == status)
    if zone_id is not None:
        q = q.where(SOS.zone_id == zone_id)
    if priority is not None:
        q = q.where(SOS.priority == priority)
    return list(db.scalars(q))
