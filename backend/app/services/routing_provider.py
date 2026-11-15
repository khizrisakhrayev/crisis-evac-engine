"""Routing behind a provider interface with fallback: external (simulated) -> local-graph -> straight-line.

No real HTTP calls: ExternalRoutingProvider simulates a third-party routing API on top of our road
graph and can be switched off at runtime (config.EXTERNAL_ROUTING_UP) to demo an outage.
"""
import heapq
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy.orm import Session

from .. import config
from ..models import RoadEdge, RoadNode
from .geo import haversine_m


class RoutingUnavailable(Exception):
    pass


@dataclass
class RouteResult:
    path: list[list[float]]
    distance_m: int
    provider: str
    edge_ids: list[int] = field(default_factory=list)


class RoutingProvider(Protocol):
    name: str

    def route(self, db: Session, from_lat: float, from_lon: float, to_lat: float, to_lon: float,
              accessible_only: bool = False) -> RouteResult:
        """Return a route or raise RoutingUnavailable. accessible_only: skip non-accessible edges."""
        ...


# --- road graph -------------------------------------------------------------

@dataclass
class Graph:
    nodes: dict[int, tuple[float, float]]
    adj: dict[int, list[tuple[int, int, float]]]  # node -> [(neighbour, edge_id, length_m)]
    closed: set[int]                               # ids of closed edges
    inaccessible: set[int] = field(default_factory=set)  # ids of stairs/steep edges


_CACHE_KEY = "road_graph"


def load_graph(db: Session) -> Graph:
    """Graph for this DB session (loaded once per request; invalidate after road changes)."""
    if _CACHE_KEY not in db.info:
        nodes = {n.id: (n.lat, n.lon) for n in db.query(RoadNode).all()}
        adj: dict[int, list[tuple[int, int, float]]] = {nid: [] for nid in nodes}
        closed, inaccessible = set(), set()
        for e in db.query(RoadEdge).all():
            adj[e.from_node].append((e.to_node, e.id, e.length_m))
            adj[e.to_node].append((e.from_node, e.id, e.length_m))
            if e.is_closed:
                closed.add(e.id)
            if not e.is_accessible:
                inaccessible.add(e.id)
        db.info[_CACHE_KEY] = Graph(nodes, adj, closed, inaccessible)
    return db.info[_CACHE_KEY]


def invalidate_graph(db: Session) -> None:
    db.info.pop(_CACHE_KEY, None)


def _snap(g: Graph, lat: float, lon: float) -> int:
    return min(g.nodes, key=lambda nid: haversine_m(lat, lon, *g.nodes[nid]))


def graph_route(g: Graph, from_lat, from_lon, to_lat, to_lon, respect_closures=True, provider="local-graph",
                accessible_only=False) -> RouteResult:
    """Dijkstra between the nodes nearest to origin and destination. Raises RoutingUnavailable if no path.

    respect_closures: skip closed edges. accessible_only: also skip stairs/steep (is_accessible=False) edges.
    """
    if not g.nodes:
        raise RoutingUnavailable("empty road graph")
    src, dst = _snap(g, from_lat, from_lon), _snap(g, to_lat, to_lon)
    dist = {src: 0.0}
    prev: dict[int, tuple[int, int]] = {}  # node -> (previous node, edge id)
    heap = [(0.0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        if u == dst:
            break
        if d > dist[u]:
            continue
        for v, eid, length in g.adj[u]:
            if (respect_closures and eid in g.closed) or (accessible_only and eid in g.inaccessible):
                continue
            nd = d + length
            if nd < dist.get(v, float("inf")):
                dist[v], prev[v] = nd, (u, eid)
                heapq.heappush(heap, (nd, v))
    if dst not in dist:
        raise RoutingUnavailable("no path in road graph")

    node_seq, edge_ids, n = [dst], [], dst
    while n != src:
        n, eid = prev[n]
        node_seq.append(n)
        edge_ids.append(eid)
    node_seq.reverse()
    edge_ids.reverse()

    path = [[from_lat, from_lon]] + [list(g.nodes[n]) for n in node_seq] + [[to_lat, to_lon]]
    total = haversine_m(from_lat, from_lon, *g.nodes[src]) + dist[dst] + haversine_m(*g.nodes[dst], to_lat, to_lon)
    return RouteResult(path=path, distance_m=round(total), provider=provider, edge_ids=edge_ids)


# --- providers --------------------------------------------------------------

class ExternalRoutingProvider:
    """Simulated external map/routing API (same road graph, closures respected)."""
    name = "external"

    def __init__(self, timeout_s: float | None = None):
        self.timeout_s = config.EXTERNAL_ROUTING_TIMEOUT_S if timeout_s is None else timeout_s

    def route(self, db, from_lat, from_lon, to_lat, to_lon, accessible_only=False):
        if not config.EXTERNAL_ROUTING_UP:
            raise RoutingUnavailable("external routing API is down")
        if config.EXTERNAL_ROUTING_LATENCY_S > self.timeout_s:
            raise RoutingUnavailable("external routing API timed out")
        return graph_route(load_graph(db), from_lat, from_lon, to_lat, to_lon, provider=self.name,
                           accessible_only=accessible_only)


class LocalGraphProvider:
    """Dijkstra over the local RoadNode/RoadEdge graph, skipping closed edges."""
    name = "local-graph"

    def route(self, db, from_lat, from_lon, to_lat, to_lon, accessible_only=False):
        return graph_route(load_graph(db), from_lat, from_lon, to_lat, to_lon, provider=self.name,
                           accessible_only=accessible_only)


class StraightLineProvider:
    """Last resort: direct line. Never used for accessible-only routing (could cross stairs)."""
    name = "straight-line"

    def route(self, db, from_lat, from_lon, to_lat, to_lon, accessible_only=False):
        if accessible_only:
            raise RoutingUnavailable("straight line cannot guarantee an accessible route")
        return RouteResult(path=[[from_lat, from_lon], [to_lat, to_lon]],
                           distance_m=round(haversine_m(from_lat, from_lon, to_lat, to_lon)), provider=self.name)


GRAPH_PROVIDERS: list[RoutingProvider] = [ExternalRoutingProvider(), LocalGraphProvider()]
FALLBACK_PROVIDER: RoutingProvider = StraightLineProvider()


def get_route(db, from_lat, from_lon, to_lat, to_lon, allow_straight_line=True, accessible_only=False) -> RouteResult:
    """Try providers in order (external -> local-graph [-> straight-line]); first success wins.

    accessible_only never falls back to straight-line.
    """
    providers = GRAPH_PROVIDERS + ([FALLBACK_PROVIDER] if allow_straight_line and not accessible_only else [])
    for p in providers:
        try:
            return p.route(db, from_lat, from_lon, to_lat, to_lon, accessible_only=accessible_only)
        except RoutingUnavailable:
            continue
    raise RoutingUnavailable("no provider could route")


def active_provider() -> str:
    return "external" if config.EXTERNAL_ROUTING_UP else "local-graph"
