"""Live evacuation simulation (Stage 3)."""
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models import Shelter
from backend.app.services.simulation import ARRIVED, Simulation
from tests.helpers import STAFF


def total_occupancy():
    with SessionLocal() as db:
        return sum(s.current for s in db.scalars(select(Shelter)))


def test_twenty_citizens_at_high_speed_finish_and_raise_occupancy(client):
    before = total_occupancy()
    sim = Simulation()
    with SessionLocal() as db:
        st = sim.start(db, citizens=20, zone_id=None, speed=200, seed=7)
        assert st["spawned"] == 20 and st["running"]
        for _ in range(60):
            out = sim.tick(db)
            if not out["running"]:
                break
    assert not sim.running and out["moving"] == 0
    arrived = sum(1 for w in sim.walkers if w.status == ARRIVED)
    assert arrived == out["arrived"] >= 18
    assert total_occupancy() == before + arrived
    assert len(out["positions"]) == 20


def test_full_shelter_reroutes_walkers(client):
    sim = Simulation()
    with SessionLocal() as db:
        sim.start(db, citizens=10, zone_id=None, speed=5, seed=3)
        target = sim.walkers[0].shelter_id
        s = db.get(Shelter, target)
        s.current = s.capacity  # becomes full while they walk
        db.commit()
        sim.tick(db)
    assert sim.counters["rerouted"] >= 1
    assert all(w.shelter_id != target for w in sim.walkers if w.status == 0)


def test_simulate_api_requires_staff_and_stops(client):
    assert client.post("/api/demo/simulate", json={"citizens": 5}).status_code == 401
    r = client.post("/api/demo/simulate", json={"citizens": 5, "speed": 10}, headers=STAFF)
    assert r.status_code == 200 and r.json()["spawned"] == 5
    stop = client.post("/api/demo/simulate/stop", headers=STAFF)
    assert stop.status_code == 200 and stop.json()["running"] is False
    assert client.post("/api/demo/simulate", json={"citizens": 5, "zone_id": 999}, headers=STAFF).status_code == 404
