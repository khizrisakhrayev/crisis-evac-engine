from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal, get_db
from ..errors import api_error
from ..schemas import RoadOut, RouteOut, RoutingStatusOut
from ..services import evacuation, roads
from ..services.routing_provider import breaker, routing_status
from ..services.ws import publish
from .auth import PRIORITY_ROLES, current_role, require_role

router = APIRouter(tags=["routing"])
OPERATOR = Depends(require_role("dispatcher", "simulator"))


@router.get("/route", response_model=RouteOut)
def get_route(
    from_lat: float = Query(ge=-90, le=90),
    from_lon: float = Query(ge=-180, le=180),
    shelter_id: int | None = None,
    accessible: bool = False,
    role: str = Depends(current_role),
    db: Session = Depends(get_db),
):
    accessible_only = accessible or role in PRIORITY_ROLES  # forced for priority citizens
    try:
        return evacuation.recommend(db, from_lat, from_lon, shelter_id, accessible_only=accessible_only)
    except evacuation.ShelterNotFound:
        raise api_error(404, "shelter_not_found", "Shelter not found")
    except evacuation.NoShelterAvailable:
        raise api_error(503, "no_open_shelter", "No open shelter available")


@router.get("/roads", response_model=list[RoadOut])
def list_roads(db: Session = Depends(get_db)):
    return roads.list_roads(db)


def _set_closed(db: Session, road_id: int, closed: bool):
    road = roads.set_closed(db, road_id, closed)
    if road is None:
        raise api_error(404, "road_not_found", "Road not found")
    publish("road_updated", road)
    return road


@router.post("/roads/{road_id}/close", response_model=RoadOut, dependencies=[OPERATOR])
def close_road(road_id: int, db: Session = Depends(get_db)):
    return _set_closed(db, road_id, True)


@router.post("/roads/{road_id}/open", response_model=RoadOut, dependencies=[OPERATOR])
def open_road(road_id: int, db: Session = Depends(get_db)):
    return _set_closed(db, road_id, False)


EXTERNAL_MODES = {"up": "up", "down": "down_503", "slow": "slow"}


def _on_breaker_change(old: str, new: str) -> None:
    """Broadcast every circuit-breaker state change to dispatchers."""
    with SessionLocal() as s:
        publish("routing_status", routing_status(s))


breaker.on_state_change = _on_breaker_change


@router.get("/routing/status", response_model=RoutingStatusOut)
def get_routing_status(db: Session = Depends(get_db)):
    return routing_status(db)


@router.post("/routing/external/{state}", response_model=RoutingStatusOut, dependencies=[OPERATOR])
def toggle_external(state: Literal["up", "down", "slow"], db: Session = Depends(get_db)):
    config.EXTERNAL_MODE = EXTERNAL_MODES[state]  # simulate the external API: up | HTTP 503 | >5 s responses
    status = routing_status(db)
    publish("routing_status", status)
    return status
