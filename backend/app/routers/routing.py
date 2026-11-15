from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..schemas import RoadOut, RouteOut, RoutingStatusOut
from ..services import evacuation, roads
from ..services.routing_provider import active_provider
from .auth import require_role

router = APIRouter(tags=["routing"])
OPERATOR = Depends(require_role("dispatcher", "simulator"))


@router.get("/route", response_model=RouteOut)
def get_route(
    from_lat: float = Query(ge=-90, le=90),
    from_lon: float = Query(ge=-180, le=180),
    shelter_id: int | None = None,
    db: Session = Depends(get_db),
):
    try:
        return evacuation.recommend(db, from_lat, from_lon, shelter_id)
    except evacuation.ShelterNotFound:
        raise HTTPException(404, "Shelter not found")
    except evacuation.NoShelterAvailable:
        raise HTTPException(503, "No open shelter available")


@router.get("/roads", response_model=list[RoadOut])
def list_roads(db: Session = Depends(get_db)):
    return roads.list_roads(db)


def _set_closed(db: Session, road_id: int, closed: bool):
    road = roads.set_closed(db, road_id, closed)
    if road is None:
        raise HTTPException(404, "Road not found")
    return road


@router.post("/roads/{road_id}/close", response_model=RoadOut, dependencies=[OPERATOR])
def close_road(road_id: int, db: Session = Depends(get_db)):
    return _set_closed(db, road_id, True)


@router.post("/roads/{road_id}/open", response_model=RoadOut, dependencies=[OPERATOR])
def open_road(road_id: int, db: Session = Depends(get_db)):
    return _set_closed(db, road_id, False)


@router.get("/routing/status", response_model=RoutingStatusOut)
def routing_status():
    return {"external_up": config.EXTERNAL_ROUTING_UP, "active_provider": active_provider()}


@router.post("/routing/external/{state}", response_model=RoutingStatusOut, dependencies=[OPERATOR])
def toggle_external(state: Literal["up", "down"]):
    config.EXTERNAL_ROUTING_UP = state == "up"  # runtime switch to demo an external API outage
    return routing_status()
