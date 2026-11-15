"""Route entry choice (ENTRY_CANDIDATES) and direct walk for nearby shelters."""
import math

from sqlalchemy import select

from backend.app import config
from backend.app.db import SessionLocal
from backend.app.models import Shelter
from backend.app.services import routing_provider as rp
from backend.app.services.geo import haversine_m

M = 111_320


def offset(lat, lon, north_m=0.0, east_m=0.0):
    return lat + north_m / M, lon + east_m / (M * math.cos(math.radians(lat)))


def open_shelters():
    with SessionLocal() as db:
        return list(db.scalars(select(Shelter).where(Shelter.is_open.is_(True))))


def test_origin_100m_from_shelter_walks_directly(client):
    s = next(x for x in open_shelters() if x.is_accessible)
    lat, lon = offset(s.lat, s.lon, north_m=100)
    r = client.get("/api/route", params={"from_lat": lat, "from_lon": lon}).json()
    assert r["shelter"]["id"] == s.id and r["provider"] == "direct-walk"
    assert r["distance_m"] < 200 and r["approach"] == r["path"] and len(r["path"]) == 2
    assert r["reason"] is None and r["rerouted"] is False


def test_multi_entry_never_longer_than_single_snap(client, monkeypatch):
    """Origins whose nearest node lies away from the shelter: total walk <= old single-node snap."""
    monkeypatch.setattr(config, "DIRECT_WALK_M", 0)  # compare graph routes only
    improved = 0
    with SessionLocal() as db:
        g = rp.load_graph(db)
        for s in [x for x in open_shelters() if x.access_options][:6]:
            for north, east in ((400, 0), (-400, 0), (0, 400), (0, -400), (600, 600)):
                lat, lon = offset(s.lat, s.lon, north, east)
                monkeypatch.setattr(config, "ENTRY_CANDIDATES", 1)
                old = rp.graph_route(g, lat, lon, s.lat, s.lon, shelter_id=s.id).distance_m
                monkeypatch.setattr(config, "ENTRY_CANDIDATES", 4)
                new = rp.graph_route(g, lat, lon, s.lat, s.lon, shelter_id=s.id).distance_m
                assert new <= old
                improved += new < old
    assert improved >= 1  # some origins really had a badly placed nearest node


def test_accessible_mode_never_direct_walks_to_inaccessible_shelter(client):
    s = next(x for x in open_shelters() if not x.is_accessible)
    lat, lon = offset(s.lat, s.lon, east_m=50)
    with SessionLocal() as db:
        r = rp.get_route(db, lat, lon, s, allow_last_resort=False, accessible_only=False)
        assert r.provider == "direct-walk"  # a normal citizen would walk straight there
        try:
            acc = rp.get_route(db, lat, lon, s, allow_last_resort=False, accessible_only=True)
            assert acc.provider != "direct-walk"
        except rp.RoutingUnavailable:
            pass
    prio = client.get("/api/route", params={"from_lat": lat, "from_lon": lon},
                      headers={"X-Role": "priority_citizen"}).json()
    assert prio["provider"] != "direct-walk" or prio["shelter"]["is_accessible"]
    assert prio["shelter"] is None or prio["shelter"]["id"] != s.id
    assert haversine_m(lat, lon, s.lat, s.lon) < config.DIRECT_WALK_M
