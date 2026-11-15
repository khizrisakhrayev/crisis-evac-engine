"""Challenge Drop 1: priority_citizen role, critical SOS, accessible-only routing, coded errors."""
from sqlalchemy import select

from backend.app.db import SessionLocal
from backend.app.models import RoadEdge, Shelter, Zone
from backend.app.services import routing_provider as rp

PRIO = {"X-Role": "priority_citizen"}
OP = {"X-Role": "dispatcher"}
ORIGIN = {"from_lat": 40.3777, "from_lon": 49.8920}  # Khatai
KHATAI_SHELTER = 10  # not accessible (basement)
STADIUM = 7


def sos(client, cid, headers=None, **extra):
    body = {"lat": 40.3777, "lon": 49.8920, "hazard_type": "medical", "citizen_id": cid, **extra}
    r = client.post("/api/sos", json=body, headers=headers or {})
    assert r.status_code == 201, r.text
    return r.json()


def roads(client):
    return {r["id"]: r for r in client.get("/api/roads").json()}


def route(client, headers=None, **params):
    r = client.get("/api/route", params={**ORIGIN, **params}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def assert_accessible_route(client, r):
    assert r["provider"] in ("external", "local-graph") and r["accessible"] is True
    assert r["edge_ids"], "route must actually use roads"
    rd = roads(client)
    assert all(rd[e]["is_accessible"] and not rd[e]["is_closed"] for e in r["edge_ids"])
    assert r["shelter"]["is_accessible"] is True and r["needs_medical_transport"] is False


# --- role -------------------------------------------------------------------

def test_auth_me_roles(client):
    assert client.get("/api/auth/me", headers=PRIO).json() == {"role": "priority_citizen"}
    assert client.get("/api/auth/me", headers={"X-Role": "hacker"}).json() == {"role": "citizen"}


# --- priority SOS -----------------------------------------------------------

def test_priority_citizen_sos_is_critical(client):
    s = sos(client, "p-crit", PRIO)
    assert s["priority"] == 1 and s["priority_label"] == "critical" and s["is_priority_citizen"] is True


def test_normal_sos_and_body_cannot_override(client):
    s = sos(client, "p-norm")
    assert s["priority"] == 2 and s["priority_label"] == "normal" and s["is_priority_citizen"] is False
    s = sos(client, "p-cheat", priority=1, is_priority_citizen=True)
    assert s["priority"] == 2 and s["is_priority_citizen"] is False


def test_repeat_sos_never_downgrades(client):
    first = sos(client, "p-repeat", PRIO)
    again = sos(client, "p-repeat")  # same citizen, header missing this time
    assert again["id"] == first["id"] and again["priority"] == 1 and again["is_priority_citizen"] is True


def test_list_orders_priority_first(client):
    sos(client, "p-order-crit", PRIO)
    sos(client, "p-order-newer")  # newer, normal
    ids = [s["citizen_id"] for s in client.get("/api/sos", params={"status": "active"}).json()]
    assert ids.index("p-order-crit") < ids.index("p-order-newer")
    crit = client.get("/api/sos", params={"priority": 1}).json()
    assert crit and all(s["priority"] == 1 for s in crit)
    assert client.get("/api/sos", params={"priority": 3}).status_code == 422


# --- accessible routing -----------------------------------------------------

def test_priority_route_is_accessible(client):
    r = route(client, PRIO)
    assert_accessible_route(client, r)
    assert r["shelter"]["id"] != KHATAI_SHELTER  # nearest shelter is a basement


def test_priority_route_avoids_stairs_used_by_normal_route(client):
    prio = route(client, PRIO, shelter_id=STADIUM)
    normal = route(client, shelter_id=STADIUM)
    rd = roads(client)
    assert any(not rd[e]["is_accessible"] for e in normal["edge_ids"])  # normal takes stairs
    assert_accessible_route(client, prio)
    assert prio["distance_m"] > normal["distance_m"]


def test_priority_citizen_cannot_opt_out(client):
    assert route(client, PRIO, accessible="false")["accessible"] is True


def test_normal_citizen_can_opt_in(client):
    r = route(client, accessible="true")
    assert_accessible_route(client, r)


def test_normal_citizen_route_unchanged(client):
    r = route(client)
    assert r["shelter"]["id"] == KHATAI_SHELTER and r["accessible"] is False
    with SessionLocal() as db:
        s = db.get(Shelter, KHATAI_SHELTER)
        expected = rp.graph_route(rp.load_graph(db), ORIGIN["from_lat"], ORIGIN["from_lon"], s.lat, s.lon, shelter_id=s.id)
    assert r["path"] == expected.path and r["edge_ids"] == expected.edge_ids


def test_priority_requested_inaccessible_shelter_reroutes(client):
    r = route(client, PRIO, shelter_id=KHATAI_SHELTER)
    assert r["reason"] == "shelter_not_accessible" and r["original_shelter_id"] == KHATAI_SHELTER
    assert_accessible_route(client, r)


def test_priority_full_shelter_rule_still_applies(client):
    first = route(client, PRIO)["shelter"]
    client.post(f"/api/shelters/{first['id']}/occupancy", json={"current": first["capacity"]}, headers=OP)
    r = route(client, PRIO)
    assert r["shelter"]["id"] != first["id"] and r["reason"] == "shelter_full"
    assert_accessible_route(client, r)


def test_closed_edge_on_accessible_route(client):
    original = route(client, PRIO)
    edge = original["edge_ids"][0]
    client.post(f"/api/roads/{edge}/close", headers=OP)
    r = route(client, PRIO)
    assert r["provider"] != "straight-line"
    if r["reason"] == "no_accessible_route":
        assert r["needs_medical_transport"] is True and r["shelter"] is None
    else:
        assert edge not in r["edge_ids"] and r["rerouted"] is True
        assert_accessible_route(client, r)


def test_no_accessible_route_needs_medical_transport(client):
    snap = route(client, PRIO)["path"][0]  # street path starts at the snapped road node
    touching = [e for e in roads(client).values()
                if e["is_accessible"] and snap in ([e["from_lat"], e["from_lon"]], [e["to_lat"], e["to_lon"]])]
    assert touching
    for e in touching:
        client.post(f"/api/roads/{e['id']}/close", headers=OP)
    r = route(client, PRIO)
    assert r["reason"] == "no_accessible_route" and r["needs_medical_transport"] is True
    assert r["shelter"] is None and r["path"] == [] and r["provider"] is None and r["accessible"] is True
    # A normal citizen can still use the remaining (stairs) road.
    normal = route(client)
    assert normal["shelter"] is not None and normal["provider"] != "straight-line"


# --- seed -------------------------------------------------------------------

def test_seed_accessibility(client):
    with SessionLocal() as db:
        shelters = list(db.scalars(select(Shelter)))
        edges = list(db.scalars(select(RoadEdge)))
        zones = list(db.scalars(select(Zone)))
        g = rp.load_graph(db)
    accessible_shelters = [s for s in shelters if s.is_accessible]
    assert len(accessible_shelters) >= 6
    assert 0.65 <= sum(e.is_accessible for e in edges) / len(edges) <= 0.75
    for z in zones:  # every zone reaches at least one accessible shelter on accessible roads
        reachable = 0
        for s in accessible_shelters:
            try:
                rp.graph_route(g, z.center_lat, z.center_lon, s.lat, s.lon, accessible_only=True)
                reachable += 1
            except rp.RoutingUnavailable:
                pass
        assert reachable >= 1, z.name


def test_shelter_items_include_is_accessible(client):
    assert all("is_accessible" in s for s in client.get("/api/shelters").json())
    near = client.get("/api/shelters/nearest", params={"lat": 40.38, "lon": 49.83}).json()
    assert all("is_accessible" in s for s in near)


# --- language-neutral errors ------------------------------------------------

def test_errors_are_coded(client):
    for r, code in [
        (client.post("/api/sos/999999/safe"), "sos_not_found"),
        (client.post("/api/roads/1/close"), "forbidden_role"),
        (client.get("/api/shelters/nearest"), "point_or_district_required"),
        (client.get("/api/route", params={**ORIGIN, "shelter_id": 9999}), "shelter_not_found"),
        (client.post("/api/sos", json={"lat": 1, "lon": 1, "hazard_type": "x", "citizen_id": "e"}), "validation_error"),
    ]:
        detail = r.json()["detail"]
        assert detail["code"] == code and isinstance(detail["message"], str), r.json()
