import pytest
from sqlalchemy import update

from backend.app import config
from backend.app.db import SessionLocal
from backend.app.models import RoadEdge, Shelter
from backend.app.seed import SHELTERS
from backend.app.services import routing_provider as rp
from backend.app.services.geo import haversine_m

OP = {"X-Role": "dispatcher"}
ORIGIN = {"from_lat": 40.3777, "from_lon": 49.8920}  # Khatai
KHATAI_SHELTER = 10  # Khatai District Shelter, capacity 500
STADIUM = 7  # Tofiq Bahramov Republican Stadium (Narimanov)


def _reset():
    config.EXTERNAL_ROUTING_UP = True
    with SessionLocal() as db:
        db.execute(update(RoadEdge).values(is_closed=False))
        for i, (*_, current) in enumerate(SHELTERS, start=1):
            db.execute(update(Shelter).where(Shelter.id == i).values(current=current, is_open=True))
        db.commit()


@pytest.fixture(autouse=True)
def clean_state(client):
    _reset()
    yield
    _reset()


def route(client, **params):
    r = client.get("/api/route", params={**ORIGIN, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_route_basic_external(client):
    r = route(client, shelter_id=STADIUM)
    assert r["provider"] == "external"
    assert len(r["path"]) >= 3 and r["path"][0] == [ORIGIN["from_lat"], ORIGIN["from_lon"]]
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
    assert s == {"external_up": False, "active_provider": "local-graph"}
    assert client.get("/api/routing/status").json()["external_up"] is False

    down = route(client, shelter_id=STADIUM)
    assert down["provider"] == "local-graph" and down["path"] == up["path"]

    client.post("/api/routing/external/up", headers=OP)
    assert route(client, shelter_id=STADIUM)["provider"] == "external"


def test_disconnected_origin_falls_back_to_straight_line(client):
    snap = route(client)["path"][1]  # origin's snapped node
    touching = [e["id"] for e in client.get("/api/roads").json()
                if snap in ([e["from_lat"], e["from_lon"]], [e["to_lat"], e["to_lon"]])]
    assert touching
    for eid in touching:
        client.post(f"/api/roads/{eid}/close", headers=OP)
    r = route(client)
    assert r["provider"] == "straight-line" and len(r["path"]) == 2
    assert r["rerouted"] is True and r["reason"] == "road_closed"


def test_roads_list(client):
    roads = client.get("/api/roads").json()
    assert len(roads) == 45
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


def test_straight_line_provider():
    r = rp.StraightLineProvider().route(None, 40.0, 49.0, 40.01, 49.01)
    assert r.provider == "straight-line" and r.distance_m == round(haversine_m(40.0, 49.0, 40.01, 49.01))


def test_external_timeout_simulation(monkeypatch):
    monkeypatch.setattr(config, "EXTERNAL_ROUTING_LATENCY_S", 5.0)
    with pytest.raises(rp.RoutingUnavailable):
        rp.ExternalRoutingProvider(timeout_s=2.0).route(None, 40.0, 49.0, 40.01, 49.01)
