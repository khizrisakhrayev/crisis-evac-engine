"""Evacuation recommendation: pick a shelter, route to it, reroute when the shelter is full or roads are closed.

accessible_only (priority citizens): only accessible shelters and accessible edges, never a straight line;
if nothing is reachable, answer "no_accessible_route" + needs_medical_transport instead of a route.
"""
import math

from sqlalchemy.orm import Session

from .. import config
from ..models import Shelter
from .routing_provider import (DIRECT_WALK, RoutingUnavailable, get_route, graph_route, load_graph, routing_mode,
                               walking_estimate)
from .shelters import open_shelters_by_distance, to_nearest_out


class ShelterNotFound(Exception):
    pass


class NoShelterAvailable(Exception):
    pass


def _eta_min(distance_m: int) -> int:
    return math.ceil(distance_m / (config.WALKING_SPEED_KMH * 1000 / 60))


NOTICE_OFFLINE = "offline_backup_routing"


def _degradation(degraded: bool) -> dict:
    return dict(degraded=degraded, mode="fallback" if degraded else "online",
                notice_code=NOTICE_OFFLINE if degraded else None)


def _no_accessible_route() -> dict:
    return dict(shelter=None, path=[], distance_m=None, eta_min=None, rerouted=False,
                reason="no_accessible_route", original_shelter_id=None, provider=None, edge_ids=[], approach=[], approach_m=0,
                accessible=True, needs_medical_transport=True,
                **_degradation(routing_mode() != "online"))  # no route at all: report the routing mode


def recommend(db: Session, from_lat: float, from_lon: float, shelter_id: int | None = None,
              accessible_only: bool = False) -> dict:
    open_items = open_shelters_by_distance(db, from_lat, from_lon)
    if accessible_only:
        open_items = [i for i in open_items if i.is_accessible]
    # Rank by total walking distance (approach + streets + access, or a direct walk), not straight distance.
    graph = load_graph(db)
    walk = {i.id: walking_estimate(graph, from_lat, from_lon, i, accessible_only) for i in open_items}
    open_items.sort(key=lambda i: (walk[i.id], i.distance_m))

    if shelter_id is not None:
        s = db.get(Shelter, shelter_id)
        if s is None:
            raise ShelterNotFound(shelter_id)
        target = to_nearest_out(s, from_lat, from_lon)
    elif open_items:
        target = open_items[0]
    elif accessible_only:
        return _no_accessible_route()
    else:
        raise NoShelterAvailable()

    # 1. Shelter choice: the target unless closed/full (>= REROUTE_OCCUPANCY_PCT, via is_full)
    #    or, in accessible mode, not accessible.
    rerouted, reason, original_id = False, None, None
    available = [i for i in open_items if not i.is_full and i.id != target.id]
    unusable_reason = None
    if accessible_only and not target.is_accessible:
        unusable_reason = "shelter_not_accessible"
    elif not target.is_open or target.is_full:
        unusable_reason = "shelter_full"

    if unusable_reason is None:
        candidates = [target] + available
    elif available:
        candidates = available
        rerouted, reason, original_id = True, unusable_reason, target.id
    elif accessible_only:
        return _no_accessible_route()  # never send a priority citizen to an unusable shelter
    else:
        candidates = [target]
        reason = "all_shelters_full"

    # 2. Route to the first candidate reachable on open (and, if required, accessible) roads.
    chosen, route = candidates[0], None
    for c in candidates:
        try:
            route = get_route(db, from_lat, from_lon, c, allow_last_resort=False, accessible_only=accessible_only)
            chosen = c
            break
        except RoutingUnavailable:
            continue
    if route is None and accessible_only:
        return _no_accessible_route()

    # 3. Was the normal (closure-free) shortest path blocked by a closed road?
    try:
        ideal = graph_route(graph, from_lat, from_lon, chosen.lat, chosen.lon, respect_closures=False,
                            accessible_only=accessible_only, shelter_id=chosen.id)
        blocked = any(eid in graph.closed for eid in ideal.edge_ids)
    except RoutingUnavailable:
        blocked = False  # no road path even ignoring closures: not a closure problem
    if route is not None and route.provider == DIRECT_WALK:
        blocked = False  # no roads used
    if route is None:
        route = get_route(db, from_lat, from_lon, chosen, allow_last_resort=True)  # static-matrix last resort
    elif chosen.id != candidates[0].id:
        blocked = True  # first choice was unreachable on open roads

    if blocked and reason is None:
        rerouted, reason = True, "road_closed"
    if chosen.id != target.id and original_id is None:
        rerouted, original_id = True, target.id

    return dict(
        shelter=chosen, path=route.path, distance_m=route.distance_m, eta_min=_eta_min(route.distance_m),
        rerouted=rerouted, reason=reason, original_shelter_id=original_id,
        provider=route.provider, edge_ids=route.edge_ids, approach=route.approach, approach_m=route.approach_m,
        accessible=accessible_only, needs_medical_transport=False,
        **_degradation(routing_mode() != "online" if route.provider == DIRECT_WALK else route.provider != "external"),
    )
