from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Shelter
from ..schemas import NearestShelterOut, OccupancyUpdate, ShelterOut
from ..services import geo
from ..services import shelters as svc
from .auth import require_role

router = APIRouter(tags=["shelters"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/shelters", response_model=list[ShelterOut])
def list_shelters(db: Session = Depends(get_db)):
    return db.scalars(select(Shelter).order_by(Shelter.id)).all()


@router.get("/shelters/nearest", response_model=list[NearestShelterOut])
def nearest_shelters(
    lat: float | None = Query(None, ge=-90, le=90),
    lon: float | None = Query(None, ge=-180, le=180),
    district: str | None = None,
    limit: int = Query(5, ge=1, le=50),
    db: Session = Depends(get_db),
):
    has_point = lat is not None and lon is not None
    if not has_point and not district:
        raise HTTPException(422, "Provide lat and lon, or district")
    if (lat is None) != (lon is None):
        raise HTTPException(422, "lat and lon must be given together")
    zone = None
    if district:
        zone = geo.zone_by_name(district)
        if zone is None:
            raise HTTPException(404, f"Unknown district: {district}")
    return svc.nearest_shelters(db, lat, lon, zone, limit)


@router.post("/shelters/{shelter_id}/occupancy", response_model=ShelterOut,
             dependencies=[Depends(require_role("dispatcher"))])
def update_occupancy(shelter_id: int, body: OccupancyUpdate, db: Session = Depends(get_db)):
    shelter = svc.set_occupancy(db, shelter_id, body.current)
    if shelter is None:
        raise HTTPException(404, "Shelter not found")
    return shelter
