"""P1: routes follow real streets (precomputed OSM foot geometry)."""
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models import RoadEdge, Shelter
from backend.app.seed import SEED_REPORT
from backend.app.services.geo import haversine_m

ORIGIN = {"from_lat": 40.3777, "from_lon": 49.8920}  # Khatai, off any road node
OP = {"X-Role": "dispatcher"}


def route(client, **params):
    r = client.get("/api/route", params={**ORIGIN, **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_seed_uses_real_geometry():
    with SessionLocal() as db:
        edges = list(db.scalars(select(RoadEdge)))
        shelters = list(db.scalars(select(Shelter)))
    assert all(e.geometry and len(e.geometry) > 2 for e in edges)  # not the straight fallback
    assert all(s.access_path and s.access_node_id for s in shelters if not s.is_temporary)
    assert any("Sabail C–Sabail W" in d for d in SEED_REPORT["dropped"]) or not SEED_REPORT["dropped"]


def test_route_follows_streets(client):
    for shelter_id in (None, 7):  # nearest shelter and a cross-district one
        r = route(client, **({"shelter_id": shelter_id} if shelter_id else {}))
        nodes = len(r["edge_ids"]) + 1
        assert len(r["path"]) > 5 * nodes, (len(r["path"]), nodes)
        gaps = [haversine_m(*p, *q) for p, q in zip(r["path"], r["path"][1:])]
        assert max(gaps) <= 300


def test_distance_is_edges_plus_access_plus_approach(client):
    r = route(client, shelter_id=7)
    with SessionLocal() as db:
        edges = {e.id: e.length_m for e in db.scalars(select(RoadEdge))}
        shelter = db.get(Shelter, 7)
        # routing picks the cheapest of the shelter's entry options; find the one this path ends with
        option = next(o for o in shelter.access_options if r["path"][-len(o["path"]):] == o["path"])
        expected = sum(edges[e] for e in r["edge_ids"]) + option["m"]
    street = r["distance_m"] - r["approach_m"]
    assert abs(street - expected) <= 0.01 * expected
    assert r["approach_m"] == round(haversine_m(*r["approach"][0], *r["approach"][1]))
    assert r["path"][-1] == [shelter.lat, shelter.lon]  # ends at the shelter entrance


def test_roads_api_has_geometry(client):
    roads = client.get("/api/roads").json()
    assert all(len(r["geometry"]) > 2 for r in roads)
    r0 = roads[0]
    assert r0["geometry"][0] == [r0["from_lat"], r0["from_lon"]] and r0["geometry"][-1] == [r0["to_lat"], r0["to_lon"]]


def test_fallback_routes_keep_street_geometry(client, monkeypatch):
    from backend.app.services import routing_provider as rp
    warm = route(client)
    client.post("/api/routing/external/down", headers=OP)
    local = route(client)
    assert local["provider"] == "local-graph" and local["path"] == warm["path"]

    def fail(*a, **k):
        raise rp.RoutingUnavailable("mocked")
    monkeypatch.setattr(rp.LocalGraphProvider, "route", fail)
    cached = route(client)
    assert cached["provider"] == "route-cache" and cached["path"] == warm["path"]
    assert cached["distance_m"] == warm["distance_m"] and cached["approach"] == warm["approach"]
