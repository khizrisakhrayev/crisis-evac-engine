from fastapi import APIRouter, Depends, HTTPException

from ..schemas import RouteOut
from .auth import require_role

router = APIRouter(tags=["routing"])


@router.get("/route", response_model=RouteOut)
def get_route(from_lat: float, from_lon: float, shelter_id: int | None = None):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/roads/{road_id}/close", dependencies=[Depends(require_role("dispatcher"))])
def close_road(road_id: int):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/roads/{road_id}/open", dependencies=[Depends(require_role("dispatcher"))])
def open_road(road_id: int):
    raise HTTPException(status_code=501, detail="Not implemented")
