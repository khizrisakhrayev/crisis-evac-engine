from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Shelter
from ..schemas import OccupancyUpdate, ShelterOut

router = APIRouter(tags=["shelters"])


@router.get("/health")
def health():
    return {"status": "ok"}


@router.get("/shelters", response_model=list[ShelterOut])
def list_shelters(db: Session = Depends(get_db)):
    return db.scalars(select(Shelter).order_by(Shelter.id)).all()


@router.get("/shelters/nearest", response_model=list[ShelterOut])
def nearest_shelters(lat: float, lon: float, district: str | None = None, limit: int = 5):
    return []  # TODO: sort by distance via services


@router.post("/shelters/{shelter_id}/occupancy", response_model=ShelterOut)
def update_occupancy(shelter_id: int, body: OccupancyUpdate):
    raise HTTPException(status_code=501, detail="Not implemented")
