"""Routing behind a provider interface with a circuit breaker and a local backup chain.

Chain: external (simulated third-party API, guarded by a circuit breaker + hard timeout)
       -> local-graph (Dijkstra over SQLite road graph)
       -> route-cache (last good route for this origin node + shelter)
       -> static-matrix (precomputed zone->shelter distances; last resort, never for accessible routing).
No real HTTP calls. The external API mode is switched at runtime via config.EXTERNAL_MODE.
"""
import heapq
import logging
import threading
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .. import config
from ..models import DistanceMatrix, RoadEdge, RoadNode, RouteCache, Shelter, Zone
from . import geo
from .circuit_breaker import CircuitBreaker
from .clock import utcnow
from .geo import haversine_m

log = logging.getLogger(__name__)


class RoutingUnavailable(Exception):
    pass


class ExternalAPIError(RoutingUnavailable):
    def __init__(self, status: int = 503):
        super().__init__(f"external API HTTP {status}")
        self.status = status


class ExternalAPITimeout(RoutingUnavailable):
    def __init__(self, timeout_s: float):
        super().__init__(f"external API timeout after {timeout_s}s")


@dataclass
class RouteResult:
    path: list[list[float]]          # street geometry: first road node ... shelter entrance
    distance_m: int                  # total incl. approach
    provider: str
    edge_ids: list[int] = field(default_factory=list)
    approach: list[list[float]] = field(default_factory=list)  # straight leg: citizen -> first road node
    approach_m: int = 0


class RoutingProvider(Protocol):
    name: str

    def route(self, db: Session, graph: "Graph", from_lat: float, from_lon: float, shelter,
              accessible_only: bool = False) -> RouteResult:
        """Return a route to `shelter` (needs id, lat, lon) or raise RoutingUnavailable."""
        ...


# --- road graph -------------------------------------------------------------

@dataclass
class Graph:
    nodes: dict[int, tuple[float, float]]
    adj: dict[int, list[tuple[int, int, float]]]  # node -> [(neighbour, edge_id, length_m)]
    closed: set[int]                               # ids of closed edges
    inaccessible: set[int] = field(default_factory=set)  # ids of stairs/steep edges
    ends: dict[int, tuple[int, int]] = field(default_factory=dict)        # edge -> (from_node, to_node)
    geometry: dict[int, list[list[float]]] = field(default_factory=dict)  # edge -> street polyline from -> to
    access: dict[int, list[tuple[int, list[list[float]], float]]] = field(default_factory=dict)  # shelter -> [(node, path, m)]


_CACHE_KEY = "road_graph"
_STATIC: dict = {}  # geometry/access never change after seeding: cached per process


def _static(db: Session) -> dict:
    if not _STATIC:
        _STATIC["geometry"] = {e.id: e.geometry for e in db.query(RoadEdge).all() if e.geometry}
        _STATIC["access"] = {
            s.id: [(o["node_id"], o["path"], o["m"]) for o in (s.access_options or [])]
            or [(s.access_node_id, s.access_path, s.access_m)]
            for s in db.query(Shelter).filter(Shelter.access_node_id.isnot(None)).all()}
    return _STATIC


def load_graph(db: Session) -> Graph:
    """Graph for this DB session (loaded once per request; invalidate after road changes)."""
    if _CACHE_KEY not in db.info:
        nodes = {n.id: (n.lat, n.lon) for n in db.query(RoadNode).all()}
        adj: dict[int, list[tuple[int, int, float]]] = {nid: [] for nid in nodes}
        closed, inaccessible, ends = set(), set(), {}
        for e in db.query(RoadEdge.id, RoadEdge.from_node, RoadEdge.to_node, RoadEdge.length_m,
                           RoadEdge.is_closed, RoadEdge.is_accessible).all():
            adj[e.from_node].append((e.to_node, e.id, e.length_m))
            adj[e.to_node].append((e.from_node, e.id, e.length_m))
            ends[e.id] = (e.from_node, e.to_node)
            if e.is_closed:
                closed.add(e.id)
            if not e.is_accessible:
                inaccessible.add(e.id)
        static = _static(db)
        db.info[_CACHE_KEY] = Graph(nodes, adj, closed, inaccessible, ends, static["geometry"], static["access"])
    return db.info[_CACHE_KEY]


def invalidate_graph(db: Session) -> None:
    db.info.pop(_CACHE_KEY, None)


def snap(g: Graph, lat: float, lon: float) -> int:
    return min(g.nodes, key=lambda nid: haversine_m(lat, lon, *g.nodes[nid]))


def graph_route(g: Graph, from_lat, from_lon, to_lat, to_lon, respect_closures=True, provider="local-graph",
                accessible_only=False, shelter_id: int | None = None) -> RouteResult:
    """Dijkstra from the node nearest to the origin to the shelter's access node; raises RoutingUnavailable if no path.

    Path follows the stored street geometry (oriented by travel direction) plus the shelter's access path; the
    straight citizen -> first node leg is returned separately as `approach`.
    respect_closures: skip closed edges. accessible_only: also skip stairs/steep (is_accessible=False) edges.
    """
    if not g.nodes:
        raise RoutingUnavailable("empty road graph")
    src = snap(g, from_lat, from_lon)
    options = g.access.get(shelter_id) if shelter_id is not None else None
    if not options:  # no stored access (temporary shelter / unit graphs): nearest node + straight last leg
        near = snap(g, to_lat, to_lon)
        options = [(near, [list(g.nodes[near]), [to_lat, to_lon]], haversine_m(*g.nodes[near], to_lat, to_lon))]
    targets = {node for node, _, _ in options}
    dist = {src: 0.0}
    prev: dict[int, tuple[int, int]] = {}  # node -> (previous node, edge id)
    heap = [(0.0, src)]
    while heap:
        d, u = heapq.heappop(heap)
        targets.discard(u)
        if not targets:
            break  # every candidate entry node settled
        if d > dist[u]:
            continue
        for v, eid, length in g.adj[u]:
            if (respect_closures and eid in g.closed) or (accessible_only and eid in g.inaccessible):
                continue
            nd = d + length
            if nd < dist.get(v, float("inf")):
                dist[v], prev[v] = nd, (u, eid)
                heapq.heappush(heap, (nd, v))
    reachable = [(dist[node] + m, node, tail, m) for node, tail, m in options if node in dist]
    if not reachable:
        raise RoutingUnavailable("no path in road graph")
    _, dst, tail, tail_m = min(reachable, key=lambda r: r[0])  # cheapest street walk + access path

    node_seq, edge_ids, n = [dst], [], dst
    while n != src:
        n, eid = prev[n]
        node_seq.append(n)
        edge_ids.append(eid)
    node_seq.reverse()
    edge_ids.reverse()

    path = [list(g.nodes[src])]
    for i, eid in enumerate(edge_ids):
        u, v = node_seq[i], node_seq[i + 1]
        geom = g.geometry.get(eid)
        if geom:
            if g.ends.get(eid, (u, v))[0] != u:
                geom = geom[::-1]  # stored from -> to; we travel to -> from
        else:
            geom = [list(g.nodes[u]), list(g.nodes[v])]
        path.extend(geom[1:])
    path.extend(tail[1:])
    approach_m = haversine_m(from_lat, from_lon, *g.nodes[src])
    total = approach_m + dist[dst] + tail_m
    return RouteResult(path=path, distance_m=round(total), provider=provider, edge_ids=edge_ids,
                       approach=[[from_lat, from_lon], list(g.nodes[src])], approach_m=round(approach_m))


# --- circuit breaker for the external API ---------------------------------------

breaker = CircuitBreaker(failure_threshold=lambda: config.BREAKER_FAILURE_THRESHOLD,
                         cooldown_s=lambda: config.BREAKER_COOLDOWN_S)

_shutdown = threading.Event()  # lets simulated slow calls end early


def _call_with_timeout(fn, timeout_s: float):
    """Run fn in a daemon thread; give up after timeout_s (the thread is abandoned, never joined)."""
    box: dict = {}

    def run():
        try:
            box["result"] = fn()
        except BaseException as e:  # noqa: BLE001 - re-raised in the caller thread
            box["error"] = e

    t = threading.Thread(target=run, daemon=True, name="external-routing-call")
    t.start()
    t.join(timeout_s)
    if t.is_alive():
        raise ExternalAPITimeout(timeout_s)
    if "error" in box:
        raise box["error"]
    return box["result"]


# --- providers --------------------------------------------------------------------

class ExternalRoutingProvider:
    """Simulated external Map & Routing API: up | down_503 | slow (config.EXTERNAL_MODE)."""
    name = "external"

    def __init__(self):
        self.calls = 0  # real (non-skipped) calls, for tests and monitoring

    def _remote(self, graph, from_lat, from_lon, to_lat, to_lon, accessible_only, shelter_id=None):
        mode = config.EXTERNAL_MODE
        if mode == "down_503":
            raise ExternalAPIError(503)
        if mode == "slow":
            _shutdown.wait(config.EXTERNAL_SLOW_LATENCY_S)
        return graph_route(graph, from_lat, from_lon, to_lat, to_lon, provider=self.name,
                           accessible_only=accessible_only, shelter_id=shelter_id)

    def route(self, db, graph, from_lat, from_lon, shelter, accessible_only=False):
        if not breaker.allow_request():
            raise RoutingUnavailable("circuit open: external API skipped")
        self.calls += 1
        try:
            result = _call_with_timeout(
                lambda: self._remote(graph, from_lat, from_lon, shelter.lat, shelter.lon, accessible_only, shelter.id),
                config.EXTERNAL_TIMEOUT_S)
        except (ExternalAPIError, ExternalAPITimeout) as e:
            breaker.record_failure(e)
            raise
        except RoutingUnavailable:
            breaker.record_success()  # the API answered; there is just no path
            raise
        except Exception as e:  # anything unexpected counts as an API failure
            breaker.record_failure(e)
            raise ExternalAPIError(500) from e
        breaker.record_success()
        return result


class LocalGraphProvider:
    """Dijkstra over the local RoadNode/RoadEdge graph in SQLite, skipping closed edges."""
    name = "local-graph"

    def route(self, db, graph, from_lat, from_lon, shelter, accessible_only=False):
        return graph_route(graph, from_lat, from_lon, shelter.lat, shelter.lon, provider=self.name,
                           accessible_only=accessible_only, shelter_id=shelter.id)


class RouteCacheProvider:
    """Last good route for (snapped origin node, shelter, accessible); rejected if one of its edges is now closed."""
    name = "route-cache"

    def route(self, db, graph, from_lat, from_lon, shelter, accessible_only=False):
        if not graph.nodes:
            raise RoutingUnavailable("empty road graph")
        row = db.scalar(select(RouteCache).where(
            RouteCache.origin_node_id == snap(graph, from_lat, from_lon),
            RouteCache.shelter_id == shelter.id, RouteCache.accessible.is_(bool(accessible_only))))
        if row is None:
            raise RoutingUnavailable("route cache miss")
        if any(eid in graph.closed for eid in row.edge_ids_json):
            raise RoutingUnavailable("cached route uses a closed road")
        cached = row.path_json
        if len(cached) < 2:
            raise RoutingUnavailable("bad cache row")
        # Cached street path starts at the road node; the straight approach is re-built for the real start point.
        approach_m = haversine_m(from_lat, from_lon, *cached[0])
        return RouteResult(path=cached, distance_m=round(row.distance_m + approach_m), provider=self.name,
                           edge_ids=list(row.edge_ids_json), approach=[[from_lat, from_lon], cached[0]],
                           approach_m=round(approach_m))


class StaticMatrixProvider:
    """Last resort for normal citizens: precomputed zone->shelter distance, drawn as a direct line."""
    name = "static-matrix"

    def route(self, db, graph, from_lat, from_lon, shelter, accessible_only=False):
        if accessible_only:
            raise RoutingUnavailable("static matrix cannot guarantee an accessible route")
        direct = haversine_m(from_lat, from_lon, shelter.lat, shelter.lon)
        zone = geo.nearest_zone(from_lat, from_lon)
        known = db.scalar(select(DistanceMatrix.distance_m).where(
            DistanceMatrix.zone_id == zone.id, DistanceMatrix.shelter_id == shelter.id)) if zone else None
        distance = known if known is not None else direct * config.STATIC_MATRIX_DETOUR_FACTOR
        return RouteResult(path=[[from_lat, from_lon], [shelter.lat, shelter.lon]],
                           distance_m=round(max(distance, direct)), provider=self.name)


EXTERNAL = ExternalRoutingProvider()
LOCAL_GRAPH = LocalGraphProvider()
ROUTE_CACHE = RouteCacheProvider()
STATIC_MATRIX = StaticMatrixProvider()
CACHEABLE = {"external", "local-graph"}


def _remember(db: Session, graph: Graph, from_lat, from_lon, shelter, accessible_only, r: RouteResult) -> None:
    """Upsert the route into RouteCache; skipped when the cached edges are identical. Never raises."""
    try:
        origin = snap(graph, from_lat, from_lon)
        existing = db.scalar(select(RouteCache.edge_ids_json).where(
            RouteCache.origin_node_id == origin, RouteCache.shelter_id == shelter.id,
            RouteCache.accessible.is_(bool(accessible_only))))
        if existing is not None and list(existing) == list(r.edge_ids):
            return
        values = dict(origin_node_id=origin, shelter_id=shelter.id, accessible=bool(accessible_only),
                      path_json=r.path, distance_m=r.distance_m - r.approach_m,  # stored without the approach leg
                      edge_ids_json=r.edge_ids, updated_at=utcnow())
        stmt = sqlite_insert(RouteCache).values(**values)
        stmt = stmt.on_conflict_do_update(index_elements=["origin_node_id", "shelter_id", "accessible"],
                                          set_={k: stmt.excluded[k] for k in ("path_json", "distance_m",
                                                                               "edge_ids_json", "updated_at")})
        db.execute(stmt)
        db.commit()
    except Exception:
        db.rollback()
        log.warning("route cache upsert failed", exc_info=True)


def get_route(db: Session, from_lat: float, from_lon: float, shelter, *, allow_last_resort: bool = True,
              accessible_only: bool = False) -> RouteResult:
    """external -> local-graph -> route-cache [-> static-matrix]; first success wins, nothing ever raises raw.

    accessible_only never uses static-matrix (and only accessible cache entries).
    """
    graph = load_graph(db)
    providers = [EXTERNAL, LOCAL_GRAPH, ROUTE_CACHE]
    if allow_last_resort and not accessible_only:
        providers.append(STATIC_MATRIX)
    for p in providers:
        try:
            result = p.route(db, graph, from_lat, from_lon, shelter, accessible_only=accessible_only)
        except RoutingUnavailable:
            continue
        except Exception:
            log.warning("routing provider %s failed", p.name, exc_info=True)
            continue
        if p.name in CACHEABLE:
            _remember(db, graph, from_lat, from_lon, shelter, accessible_only, result)
        return result
    raise RoutingUnavailable("no provider could route")


# --- static distance matrix ---------------------------------------------------------

def build_distance_matrix(db: Session, force: bool = False) -> int:
    """Zone centre -> every shelter over the road graph ignoring closures (haversine x factor if unreachable)."""
    if not force and db.scalar(select(func.count()).select_from(DistanceMatrix)):
        return 0
    db.execute(delete(DistanceMatrix))
    graph = load_graph(db)
    rows = []
    for z in db.scalars(select(Zone)):
        for s in db.scalars(select(Shelter)):
            try:
                d = graph_route(graph, z.center_lat, z.center_lon, s.lat, s.lon, respect_closures=False,
                                shelter_id=s.id).distance_m
            except RoutingUnavailable:
                d = round(haversine_m(z.center_lat, z.center_lon, s.lat, s.lon) * config.STATIC_MATRIX_DETOUR_FACTOR)
            rows.append(DistanceMatrix(zone_id=z.id, shelter_id=s.id, distance_m=d))
    db.add_all(rows)
    db.commit()
    return len(rows)


# --- status ---------------------------------------------------------------------------

def routing_mode() -> str:
    """online = external API up and circuit closed; otherwise fallback (local backup routing)."""
    return "online" if config.EXTERNAL_MODE == "up" and breaker.state == "closed" else "fallback"


def active_provider() -> str:
    return "external" if routing_mode() == "online" else "local-graph"


def routing_status(db: Session | None = None) -> dict:
    cache_size = db.scalar(select(func.count()).select_from(RouteCache)) if db is not None else 0
    return dict(mode=routing_mode(), external_mode=config.EXTERNAL_MODE, external_up=config.EXTERNAL_MODE == "up",
                breaker=breaker.snapshot(), active_provider=active_provider(), cache_size=cache_size or 0)
