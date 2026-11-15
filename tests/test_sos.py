from sqlalchemy import inspect

from backend.app.db import engine
from backend.app.services import geo


def sos(client, citizen_id, lat=40.3777, lon=49.8920, hazard="fire"):
    return client.post("/api/sos", json={"lat": lat, "lon": lon, "hazard_type": hazard, "citizen_id": citizen_id})


def active_for(client, citizen_id):
    return [s for s in client.get("/api/sos", params={"status": "active"}).json() if s["citizen_id"] == citizen_id]


def test_create_sos(client):
    r = sos(client, "t-create")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "active" and body["hazard_type"] == "fire"
    assert body["zone_id"] == geo.zone_by_name("Khatai").id
    assert body["created_at"].endswith("Z")


def test_invalid_payload_422(client):
    assert sos(client, "t-bad", hazard="earthquake").status_code == 422
    assert sos(client, "t-bad", lat=95).status_code == 422
    assert sos(client, "").status_code == 422


def test_same_citizen_updates_single_active_record(client):
    first = sos(client, "t-dup").json()
    second = sos(client, "t-dup", lat=40.3800, lon=49.8320, hazard="medical").json()
    assert second["id"] == first["id"]
    assert second["hazard_type"] == "medical" and second["lat"] == 40.38
    assert second["zone_id"] == geo.zone_by_name("Nasimi").id
    assert second["created_at"] >= first["created_at"]
    assert len(active_for(client, "t-dup")) == 1


def test_mark_safe_and_404(client):
    sid = sos(client, "t-safe").json()["id"]
    r = client.post(f"/api/sos/{sid}/safe")
    assert r.status_code == 200 and r.json()["status"] == "safe"
    assert active_for(client, "t-safe") == []
    assert client.post("/api/sos/999999/safe").status_code == 404
    # After being safe, a new SOS opens a fresh record.
    assert sos(client, "t-safe").json()["id"] != sid


def test_list_filters_and_order(client):
    sos(client, "t-list-a", lat=40.3620, lon=49.8330)  # Sabail
    sos(client, "t-list-b", lat=40.3620, lon=49.8330)
    sabail = geo.zone_by_name("Sabail").id
    data = client.get("/api/sos", params={"zone_id": sabail}).json()
    assert data and all(s["zone_id"] == sabail for s in data)
    ids = [s["citizen_id"] for s in data]
    assert ids.index("t-list-b") < ids.index("t-list-a")  # newest first
    assert client.get("/api/sos", params={"status": "bogus"}).status_code == 422


def test_active_sos_partial_unique_index_exists(client):  # client fixture creates tables
    idx = {i["name"]: i for i in inspect(engine).get_indexes("sos")}
    assert idx["uq_sos_active_citizen"]["unique"]
