from sqlalchemy import select

from backend.app import config
from backend.app.db import SessionLocal
from backend.app.models import Shelter, Zone

from tests.helpers import STAFF as DISPATCHER


def test_nearest_by_point_sorted_with_occupancy(client):
    r = client.get("/api/shelters/nearest", params={"lat": 40.3777, "lon": 49.8920, "limit": 10})
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 10
    dists = [s["distance_m"] for s in data]
    assert dists == sorted(dists)
    assert all(isinstance(d, int) for d in dists)
    for s in data:
        assert {"occupancy_pct", "is_full", "zone", "capacity", "current"} <= s.keys()
        assert s["is_open"] is True
    assert data[0]["name"] == "Khatai District Shelter"


def test_nearest_default_limit_is_5(client):
    assert len(client.get("/api/shelters/nearest", params={"lat": 40.38, "lon": 49.83}).json()) == 5


def test_nearest_by_district_lists_zone_first(client):
    data = client.get("/api/shelters/nearest", params={"district": "narimanov"}).json()
    names = [s["name"] for s in data]
    assert "Baku Olympic Stadium" in names
    narimanov = [s for s in data if s["zone"] == "Narimanov"]
    assert len(narimanov) == 3
    assert data[:3] == narimanov  # district shelters come first


def test_olympic_stadium_seeded_in_narimanov(client):
    with SessionLocal() as db:
        s = db.scalar(select(Shelter).where(Shelter.name == "Baku Olympic Stadium"))
        assert db.get(Zone, s.zone_id).name == "Narimanov"


def test_nearest_validation(client):
    assert client.get("/api/shelters/nearest").status_code == 422
    assert client.get("/api/shelters/nearest", params={"lat": 40.38}).status_code == 422
    assert client.get("/api/shelters/nearest", params={"lat": 140, "lon": 49.8}).status_code == 422
    assert client.get("/api/shelters/nearest", params={"district": "Atlantis"}).status_code == 404


def test_closed_shelters_excluded(client):
    with SessionLocal() as db:
        s = db.get(Shelter, 1)
        s.is_open = False
        db.commit()
    try:
        data = client.get("/api/shelters/nearest", params={"lat": 40.38, "lon": 49.83, "limit": 50}).json()
        assert 1 not in [s["id"] for s in data]
    finally:
        with SessionLocal() as db:
            db.get(Shelter, 1).is_open = True
            db.commit()


def test_occupancy_requires_dispatcher(client):
    assert client.post("/api/shelters/1/occupancy", json={"current": 10}).status_code == 401
    assert client.post("/api/shelters/1/occupancy", json={"current": 10},
                       headers={"X-Role": "dispatcher"}).status_code == 401


def test_occupancy_clamps_and_is_full(client):
    original = client.get("/api/shelters").json()[0]
    sid, cap = original["id"], original["capacity"]
    try:
        r = client.post(f"/api/shelters/{sid}/occupancy", json={"current": cap * 10}, headers=DISPATCHER)
        assert r.status_code == 200 and r.json()["current"] == cap
        near = client.get("/api/shelters/nearest", params={"lat": original["lat"], "lon": original["lon"]}).json()
        assert near[0]["id"] == sid and near[0]["is_full"] is True
        assert near[0]["occupancy_pct"] >= config.REROUTE_OCCUPANCY_PCT

        r = client.post(f"/api/shelters/{sid}/occupancy", json={"current": -5}, headers=DISPATCHER)
        assert r.json()["current"] == 0
    finally:
        client.post(f"/api/shelters/{sid}/occupancy", json={"current": original["current"]}, headers=DISPATCHER)


def test_occupancy_unknown_shelter_404(client):
    assert client.post("/api/shelters/9999/occupancy", json={"current": 1}, headers=DISPATCHER).status_code == 404


def test_nearest_accessible_filter(client):
    params = {"lat": 40.3777, "lon": 49.8920, "limit": 50}
    default = client.get("/api/shelters/nearest", params=params).json()
    assert any(not s["is_accessible"] for s in default) and default[0]["id"] == 10  # Khatai District (basement)
    for r in (client.get("/api/shelters/nearest", params=params, headers={"X-Role": "priority_citizen"}),
              client.get("/api/shelters/nearest", params={**params, "accessible": "true"})):
        data = r.json()
        assert data and all(s["is_accessible"] for s in data) and 10 not in [s["id"] for s in data]
    forced = client.get("/api/shelters/nearest", params={**params, "accessible": "false"},
                        headers={"X-Role": "priority_citizen"}).json()
    assert all(s["is_accessible"] for s in forced)


def test_zones_endpoint(client):
    zones = client.get("/api/zones").json()
    assert len(zones) == 5 and {"id", "name", "center_lat", "center_lon"} <= zones[0].keys()
    assert "Khatai" in [z["name"] for z in zones]
