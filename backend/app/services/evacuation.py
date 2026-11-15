"""Evacuation recommendation: pick a shelter, route to it, reroute when the shelter is full or roads are closed."""
import math

from sqlalchemy.orm import Session

from .. import config
from ..models import Shelter
from .routing_provider import RoutingUnavailable, get_route, graph_route, load_graph
from .shelters import open_shelters_by_distance, to_nearest_out


class ShelterNotFound(Exception):
    pass


class NoShelterAvailable(Exception):
    pass


def _eta_min(distance_m: int) -> int:
    return math.ceil(distance_m / (config.WALKING_SPEED_KMH * 1000 / 60))


def recommend(db: Session, from_lat: float, from_lon: float, shelter_id: int | None = None) -> dict:
    open_items = open_shelters_by_distance(db, from_lat, from_lon)
    if shelter_id is not None:
        s = db.get(Shelter, shelter_id)
        if s is None:
            raise ShelterNotFound(shelter_id)
        target = to_nearest_out(s, from_lat, from_lon)
    elif open_items:
        target = open_items[0]
    else:
        raise NoShelterAvailable()

    # 1. Shelter choice: the target unless closed/full (>= REROUTE_OCCUPANCY_PCT, via is_full).
    rerouted, reason, original_id = False, None, None
    available = [i for i in open_items if not i.is_full and i.id != target.id]
    if target.is_open and not target.is_full:
        candidates = [target] + available
    elif available:
        candidates = available
        rerouted, reason, original_id = True, "shelter_full", target.id
    else:
        candidates = [target]
        reason = "all_shelters_full"

    # 2. Route to the first candidate reachable on open roads; straight line only if none is.
    chosen, route = candidates[0], None
    for c in candidates:
        try:
            route = get_route(db, from_lat, from_lon, c.lat, c.lon, allow_straight_line=False)
            chosen = c
            break
        except RoutingUnavailable:
            continue

    # 3. Was the normal (closure-free) shortest path blocked by a closed road?
    graph = load_graph(db)
    try:
        ideal = graph_route(graph, from_lat, from_lon, chosen.lat, chosen.lon, respect_closures=False)
        blocked = any(eid in graph.closed for eid in ideal.edge_ids)
    except RoutingUnavailable:
        blocked = False  # no road path even ignoring closures: not a closure problem
    if route is None:
        route = get_route(db, from_lat, from_lon, chosen.lat, chosen.lon, allow_straight_line=True)
    elif chosen.id != candidates[0].id:
        blocked = True  # first choice was unreachable on open roads

    if blocked and reason is None:
        rerouted, reason = True, "road_closed"
    if chosen.id != target.id and original_id is None:
        rerouted, original_id = True, target.id

    return dict(
        shelter=chosen, path=route.path, distance_m=route.distance_m, eta_min=_eta_min(route.distance_m),
        rerouted=rerouted, reason=reason, original_shelter_id=original_id,
        provider=route.provider, edge_ids=route.edge_ids,
    )
