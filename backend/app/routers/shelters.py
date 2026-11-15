from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import api_error
from ..models import Shelter
from ..schemas import NearestShelterOut, OccupancyUpdate, ShelterOut, ZoneOut
from ..services import geo
from ..services import crisis
from ..services import shelters as svc
from ..services.routing_provider import routing_mode
from ..services.ws import publish, publish_alert
from .auth import PRIORITY_ROLES, current_role, require_role

router = APIRouter(tags=["shelters"])


@router.get("/health")
def health():
    return {"status": "ok", "routing_mode": routing_mode()}  # stays 200 even when the external API is down


@router.get("/zones", response_model=list[ZoneOut])
def list_zones():
    return [ZoneOut(id=z.id, name=z.name, center_lat=z.lat, center_lon=z.lon) for z in geo.zones()]


@router.get("/shelters", response_model=list[ShelterOut])
def list_shelters(db: Session = Depends(get_db)):
    return db.scalars(select(Shelter).order_by(Shelter.id)).all()


@router.get("/shelters/nearest", response_model=list[NearestShelterOut])
def nearest_shelters(
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    district: str | None = None,
    limit: int = Query(5, ge=1, le=50),
    accessible: bool = False,
    role: str = Depends(current_role),
    db: Session = Depends(get_db),
):
    has_point = lat is not None and lon is not None
    if not has_point and not district:
        raise api_error(422, "point_or_district_required", "Provide lat and lon, or district")
    if (lat is None) != (lon is None):
        raise api_error(422, "lat_lon_together", "lat and lon must be given together")
    zone = None
    if district:
        zone = geo.zone_by_name(district)
        if zone is None:
            raise api_error(404, "unknown_district", f"Unknown district: {district}")
    accessible_only = accessible or role in PRIORITY_ROLES  # forced for priority citizens
    return svc.nearest_shelters(db, lat, lon, zone, limit, accessible_only=accessible_only)


@router.post("/shelters/{shelter_id}/occupancy", response_model=ShelterOut,
             dependencies=[Depends(require_role("dispatcher", "simulator"))])
def update_occupancy(shelter_id: int, body: OccupancyUpdate, db: Session = Depends(get_db)):
    result = svc.set_occupancy(db, shelter_id, body.current)
    if result is None:
        raise api_error(404, "shelter_not_found", "Shelter not found")
    shelter, previous = result
    out = ShelterOut.model_validate(shelter)
    alert_event = crisis.on_shelter_updated(db, shelter, previous)
    publish("shelter_updated", out)
    publish_alert(alert_event)
    return out
