import pytest

from backend.app import config
from backend.app.services import routing_provider as rp
from backend.app.services.geo import haversine_m

OP = {"X-Role": "dispatcher"}
ORIGIN = {"from_lat": 40.3777, "from_lon": 49.8920}  # Khatai
KHATAI_SHELTER = 10  # Khatai District Shelter, capacity 500
STADIUM = 7  # Tofiq Bahramov Republican Stadium (Narimanov)

# Road/shelter/toggle state is reset around every test by the `clean_state` fixture in conftest.py.


def route(client, **params):
    r = client.get("/api/route", params={**ORIGIN, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_route_basic_external(client):
    r = route(client, shelter_id=STADIUM)
    assert r["provider"] == "external"
    assert len(r["path"]) >= 3 and r["approach"][0] == [ORIGIN["from_lat"], ORIGIN["from_lon"]]
    assert r["approach"][-1] == r["path"][0]  # dashed approach joins the street path at the first road node
    assert r["shelter"]["id"] == STADIUM and {"occupancy_pct", "is_full", "zone"} <= r["shelter"].keys()
    assert r["rerouted"] is False and r["reason"] is None and r["original_shelter_id"] is None
    assert r["distance_m"] > 0 and r["eta_min"] >= 1 and r["edge_ids"]


def test_route_defaults_to_nearest_shelter(client):
    assert route(client)["shelter"]["id"] == KHATAI_SHELTER


def test_closed_road_detour_and_restore(client):
    original = route(client, shelter_id=STADIUM)
    edge = original["edge_ids"][len(original["edge_ids"]) // 2]
    assert client.post(f"/api/roads/{edge}/close", headers=OP).json()["is_closed"] is True

    detour = route(client, shelter_id=STADIUM)
    assert detour["path"] != original["path"] and edge not in detour["edge_ids"]
    assert detour["rerouted"] is True and detour["reason"] == "road_closed"
    assert detour["shelter"]["id"] == STADIUM and detour["distance_m"] > original["distance_m"]

    client.post(f"/api/roads/{edge}/open", headers=OP)
    restored = route(client, shelter_id=STADIUM)
    assert restored["path"] == original["path"] and restored["rerouted"] is False


def test_full_shelter_reroutes_at_threshold(client):
    client.post(f"/api/shelters/{KHATAI_SHELTER}/occupancy", json={"current": 445}, headers=OP)  # 89%
    r = route(client)
    assert r["shelter"]["id"] == KHATAI_SHELTER and r["rerouted"] is False

    client.post(f"/api/shelters/{KHATAI_SHELTER}/occupancy", json={"current": 450}, headers=OP)  # 90%
    r = route(client)
    assert r["shelter"]["id"] != KHATAI_SHELTER and r["shelter"]["is_full"] is False
    assert r["rerouted"] is True and r["reason"] == "shelter_full"
    assert r["original_shelter_id"] == KHATAI_SHELTER


def test_requested_full_shelter_reroutes(client):
    client.post(f"/api/shelters/{STADIUM}/occupancy", json={"current": 10_000}, headers=OP)
    r = route(client, shelter_id=STADIUM)
    assert r["shelter"]["id"] != STADIUM and r["reason"] == "shelter_full" and r["original_shelter_id"] == STADIUM


def test_external_down_falls_back_to_local_graph(client):
    up = route(client, shelter_id=STADIUM)
    s = client.post("/api/routing/external/down", headers=OP).json()
    assert s["external_mode"] == "down_503" and s["mode"] == "fallback" and s["external_up"] is False
    assert client.get("/api/routing/status").json()["external_mode"] == "down_503"

    down = route(client, shelter_id=STADIUM)
    assert down["provider"] == "local-graph" and down["path"] == up["path"] and down["degraded"] is True

    client.post("/api/routing/external/up", headers=OP)  # one failure only: circuit still closed
    assert route(client, shelter_id=STADIUM)["provider"] == "external"


def test_disconnected_origin_falls_back_to_static_matrix(client):
    from sqlalchemy import select

    from backend.app.db import SessionLocal
    from backend.app.models import RoadNode, Shelter
    with SessionLocal() as db:  # an origin node that is no shelter's entry node, so it needs roads to go anywhere
        entries = {o["node_id"] for s in db.scalars(select(Shelter)) for o in (s.access_options or [])}
        node = next(n for n in db.scalars(select(RoadNode)) if n.id not in entries)
        origin = {"from_lat": node.lat, "from_lon": node.lon}
    snap = [node.lat, node.lon]
    touching = [e["id"] for e in client.get("/api/roads").json()
                if snap in ([e["from_lat"], e["from_lon"]], [e["to_lat"], e["to_lon"]])]
    assert touching
    for eid in touching:
        client.post(f"/api/roads/{eid}/close", headers=OP)
    r = client.get("/api/route", params=origin).json()
    assert r["provider"] == "static-matrix" and len(r["path"]) == 2 and r["degraded"] is True
    assert r["rerouted"] is True and r["reason"] == "road_closed"


def test_roads_list(client):
    roads = client.get("/api/roads").json()
    assert len(roads) == 44  # 45 seeded links minus Sabail C–W (real walk 2.78x straight, dropped by the seed)
    assert {"from_lat", "from_lon", "to_lat", "to_lon", "is_closed", "length_m"} <= roads[0].keys()


def test_role_and_404_checks(client):
    assert client.post("/api/roads/1/close").status_code == 403
    assert client.post("/api/roads/1/open").status_code == 403
    assert client.post("/api/routing/external/down").status_code == 403
    assert client.post("/api/roads/1/close", headers={"X-Role": "citizen"}).status_code == 403
    assert client.post("/api/roads/9999/close", headers=OP).status_code == 404
    assert client.post("/api/routing/external/sideways", headers=OP).status_code == 422
    assert client.get("/api/route", params={**ORIGIN, "shelter_id": 9999}).status_code == 404
    assert client.get("/api/route", params={"from_lat": 40.38}).status_code == 422
    # simulator role is accepted too
    assert client.post("/api/roads/1/close", headers={"X-Role": "simulator"}).status_code == 200


def test_graph_route_unit():
    g = rp.Graph(nodes={1: (40.0, 49.0), 2: (40.0, 49.01), 3: (40.01, 49.005)},
                 adj={1: [(2, 10, 850.0), (3, 11, 1200.0)], 2: [(1, 10, 850.0), (3, 12, 1200.0)],
                      3: [(1, 11, 1200.0), (2, 12, 1200.0)]}, closed=set())
    assert rp.graph_route(g, 40.0, 49.0, 40.0, 49.01).edge_ids == [10]
    g.closed = {10}
    assert rp.graph_route(g, 40.0, 49.0, 40.0, 49.01).edge_ids == [11, 12]
    assert rp.graph_route(g, 40.0, 49.0, 40.0, 49.01, respect_closures=False).edge_ids == [10]
    g.closed = {10, 11}
    with pytest.raises(rp.RoutingUnavailable):
        rp.graph_route(g, 40.0, 49.0, 40.0, 49.01)


def test_static_matrix_never_shorter_than_direct_line(client):
    from types import SimpleNamespace

    from backend.app.db import SessionLocal
    target = SimpleNamespace(id=999, lat=40.01, lon=49.01)  # unknown shelter: haversine x factor
    with SessionLocal() as db:
        r = rp.StaticMatrixProvider().route(db, None, 40.0, 49.0, target)
    direct = haversine_m(40.0, 49.0, 40.01, 49.01)
    assert r.provider == "static-matrix" and r.distance_m == round(direct * config.STATIC_MATRIX_DETOUR_FACTOR)
    with pytest.raises(rp.RoutingUnavailable):
        rp.StaticMatrixProvider().route(None, None, 40.0, 49.0, target, accessible_only=True)
