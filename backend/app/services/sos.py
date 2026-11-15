from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..models import SOS
from ..schemas import SOSCreate
from . import geo
from .clock import utcnow


def _active_for(db: Session, citizen_id: str) -> SOS | None:
    return db.scalar(select(SOS).where(SOS.citizen_id == citizen_id, SOS.status == "active"))


def submit_sos(db: Session, data: SOSCreate) -> SOS:
    """Create an SOS, or refresh the citizen's existing active one (one active SOS per citizen)."""
    zone = geo.nearest_zone(data.lat, data.lon)
    fields = dict(lat=data.lat, lon=data.lon, hazard_type=data.hazard_type,
                  zone_id=zone.id if zone else None, created_at=utcnow())
    for _ in range(2):  # retry once if a concurrent request inserted the active SOS first
        sos = _active_for(db, data.citizen_id)
        if sos is None:
            sos = SOS(citizen_id=data.citizen_id, status="active", **fields)
            db.add(sos)
        else:
            for k, v in fields.items():
                setattr(sos, k, v)
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


def list_sos(db: Session, status: str | None = None, zone_id: int | None = None) -> list[SOS]:
    q = select(SOS).order_by(SOS.created_at.desc(), SOS.id.desc())
    if status:
        q = q.where(SOS.status == status)
    if zone_id is not None:
        q = q.where(SOS.zone_id == zone_id)
    return list(db.scalars(q))
