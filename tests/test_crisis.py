"""B4: Red Alert rules, one-click confirm, dispatcher overview, demo helpers, live WS events."""
from datetime import datetime, timedelta
from types import SimpleNamespace

from sqlalchemy import update

from backend.app import config
from backend.app.db import SessionLocal
from backend.app.models import SOS, Brigade, Shelter
from backend.app.services import crisis, geo
from backend.app.services.clock import utcnow

OP = {"X-Role": "dispatcher"}
SIM = {"X-Role": "simulator"}
KHATAI = (40.3777, 49.8920)
KHATAI_SHELTER = 10  # capacity 500

# --- pure rules (fake time) ---------------------------------------------------

NOW = datetime(2026, 11, 15, 12, 0, 0)


def fake(i, cid, lat=40.3800, lon=49.9000, zone=5, mins_ago=1.0, priority=2, status="active"):
    return SimpleNamespace(id=i, citizen_id=cid, lat=lat, lon=lon, zone_id=zone, priority=priority,
                           status=status, created_at=NOW - timedelta(minutes=mins_ago))


def test_rule_three_vs_four_distinct():
    three = [fake(i, f"c{i}") for i in range(1, 4)]
    assert crisis.find_sos_cluster(three[-1], three, NOW) is None
    four = three + [fake(4, "c4")]
    assert [s.id for s in crisis.find_sos_cluster(four[-1], four, NOW)] == [1, 2, 3, 4]


def test_rule_same_citizen_counts_once():
    same = [fake(i, "same") for i in range(1, 5)]
    assert crisis.find_sos_cluster(same[-1], same, NOW) is None


def test_rule_window_excludes_old_sos():
    sos = [fake(1, "c1", mins_ago=config.SOS_CLUSTER_WINDOW_MIN + 1)] + [fake(i, f"c{i}") for i in range(2, 5)]
    assert crisis.find_sos_cluster(sos[-1], sos, NOW) is None


def test_rule_radius_across_two_zones():
    # ~100 m apart, alternating zones: counted by radius even though zones differ.
    sos = [fake(i, f"c{i}", lat=40.3800 + i * 0.0003, zone=1 + i % 2) for i in range(1, 5)]
    assert crisis.find_sos_cluster(sos[-1], sos, NOW) is not None


def test_rule_far_apart_different_zones():
    sos = [fake(i, f"c{i}", lat=40.3400 + i * 0.02, zone=i) for i in range(1, 5)]  # ~2.2 km apart
    assert crisis.find_sos_cluster(sos[-1], sos, NOW) is None


def test_rule_summary_priority_and_centre():
    sos = [fake(1, "c1", priority=1), *(fake(i, f"c{i}") for i in range(2, 5))]
    summary = crisis.cluster_summary(crisis.find_sos_cluster(sos[-1], sos, NOW))
    assert summary["has_priority_sos"] is True and summary["sos_count"] == 4
    assert abs(summary["lat"] - 40.38) < 1e-9


def test_rule_overflow_threshold():
    assert crisis.is_overflowing(475, 500) is False  # 95.0 %
    assert crisis.is_overflowing(480, 500) is True   # 96.0 %


# --- API: SOS cluster -----------------------------------------------------------

def post_sos(client, cid, i=0, headers=None):
    lat, lon = KHATAI
    body = {"lat": lat + i * 0.0002, "lon": lon, "hazard_type": "fire", "citizen_id": cid}
    r = client.post("/api/sos", json=body, headers=headers or {})
    assert r.status_code == 201
    return r.json()


def alerts(client, **params):
    return client.get("/api/dispatch/alerts", params=params, headers=OP).json()


def test_cluster_alert_fires_once(client):
    for i in range(3):
        post_sos(client, f"cl-{i}", i)
    assert alerts(client) == []
    post_sos(client, "cl-3", 3)
    a = alerts(client)
    assert len(a) == 1 and a[0]["kind"] == "sos_cluster" and a[0]["status"] == "open"
    assert a[0]["severity"] == "red" and a[0]["action_code"] == "dispatch_brigade_and_open_shelter"
    assert a[0]["sos_count"] == 4 and len(a[0]["sos_ids"]) == 4 and a[0]["confirmed_at"] is None
    assert a[0]["zone_id"] == geo.zone_by_name("Khatai").id and a[0]["has_priority_sos"] is False
    post_sos(client, "cl-4", 4)
    a = alerts(client)
    assert len(a) == 1 and a[0]["sos_count"] == 5


def test_same_citizen_four_times_no_alert(client):
    for i in range(4):
        post_sos(client, "cl-same", i)
    assert alerts(client) == []


def test_old_sos_outside_window_not_counted(client):
    with SessionLocal() as db:
        db.add(SOS(citizen_id="cl-old", lat=KHATAI[0], lon=KHATAI[1], hazard_type="fire", status="active",
                   zone_id=geo.zone_by_name("Khatai").id, created_at=utcnow() - timedelta(minutes=10)))
        db.commit()
    for i in range(3):
        post_sos(client, f"cl-new-{i}", i)
    assert alerts(client) == []


def test_priority_sos_flags_alert(client):
    post_sos(client, "cl-prio", 0, headers={"X-Role": "priority_citizen"})
    for i in range(1, 4):
        post_sos(client, f"cl-p-{i}", i)
    assert alerts(client)[0]["has_priority_sos"] is True


# --- API: shelter overflow -------------------------------------------------------

def set_occ(client, current, sid=KHATAI_SHELTER):
    assert client.post(f"/api/shelters/{sid}/occupancy", json={"current": current}, headers=OP).status_code == 200


def test_shelter_overflow_alert(client):
    set_occ(client, 475)  # 95 %
    assert alerts(client) == []
    set_occ(client, 480)  # 96 %
    a = alerts(client)
    assert len(a) == 1 and a[0]["kind"] == "shelter_overflow" and a[0]["shelter_id"] == KHATAI_SHELTER
    set_occ(client, 490)  # still open -> no duplicate
    assert len(alerts(client)) == 1


# --- API: confirm ---------------------------------------------------------------------

def burst(client, headers=OP):
    lat, lon = KHATAI
    r = client.post("/api/demo/sos-burst", json={"lat": lat, "lon": lon, "count": 4, "hazard_type": "fire"},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def confirm(client, alert_id):
    return client.post(f"/api/dispatch/alerts/{alert_id}/confirm", headers=OP)


def test_burst_creates_alert(client):
    out = burst(client, SIM)
    assert len(out["sos"]) == 4 and len({s["citizen_id"] for s in out["sos"]}) == 4
    assert len(out["alerts"]) == 1 and out["alerts"][0]["kind"] == "sos_cluster"


def test_bigger_burst_lists_alert_once(client):
    lat, lon = KHATAI
    out = client.post("/api/demo/sos-burst", json={"lat": lat, "lon": lon, "count": 6}, headers=OP).json()
    assert len(out["alerts"]) == 1 and out["alerts"][0]["sos_count"] == 6


def test_confirm_dispatches_brigade_and_opens_reserve(client):
    alert = burst(client)["alerts"][0]
    r = confirm(client, alert["id"])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alert"]["status"] == "confirmed" and body["alert"]["confirmed_at"].endswith("Z")
    brigade, shelter = body["brigade"], body["shelter"]
    assert brigade["status"] == "dispatched" and brigade["alert_id"] == alert["id"]
    assert brigade["target_zone_id"] == alert["zone_id"] and body["alert"]["brigade_id"] == brigade["id"]
    assert shelter["is_reserve"] and shelter["is_open"] and body["alert"]["new_shelter_id"] == shelter["id"]
    assert shelter["name"] == "Reserve: Khatai Sports Complex"  # nearest reserve to the alert
    near = client.get("/api/shelters/nearest", params={"lat": alert["lat"], "lon": alert["lon"], "limit": 50}).json()
    assert shelter["id"] in [s["id"] for s in near]

    second = confirm(client, alert["id"])
    assert second.status_code == 409 and second.json()["detail"]["code"] == "alert_already_confirmed"
    assert confirm(client, 999_999).status_code == 404

    # Same incident keeps sending SOS: no new alert right after confirmation.
    post_sos(client, "cl-after", 1)
    assert alerts(client, status="open") == []

    released = client.post(f"/api/dispatch/brigades/{brigade['id']}/release", headers=OP).json()
    assert released["status"] == "available" and released["alert_id"] is None
    assert client.post("/api/dispatch/brigades/999/release", headers=OP).status_code == 404


def test_confirm_with_no_brigade_available(client):
    with SessionLocal() as db:
        db.execute(update(Brigade).values(status="dispatched"))
        db.commit()
    body = confirm(client, burst(client)["alerts"][0]["id"]).json()
    assert body["brigade"] is None and body["alert"]["brigade_id"] is None
    assert body["alert"]["brigade_shortage"] is True and body["alert"]["status"] == "confirmed"


def test_confirm_without_reserves_creates_temporary_shelter(client):
    with SessionLocal() as db:
        db.execute(update(Shelter).where(Shelter.is_reserve.is_(True)).values(is_open=True))
        db.commit()
    body = confirm(client, burst(client)["alerts"][0]["id"]).json()
    s = body["shelter"]
    khatai = geo.zone_by_name("Khatai")
    assert s["is_temporary"] and s["is_open"] and s["capacity"] == config.TEMP_SHELTER_CAPACITY
    assert s["type"] == "assembly_point" and (s["lat"], s["lon"]) == (khatai.lat, khatai.lon)


# --- overview / roles / demo ---------------------------------------------------------

def test_overview_requires_dispatcher(client):
    assert client.get("/api/dispatch/overview").status_code == 403
    assert client.get("/api/dispatch/overview", headers=SIM).status_code == 403
    assert client.get("/api/dispatch/overview", headers={"X-Role": "citizen"}).status_code == 403
    assert client.get("/api/dispatch/alerts").status_code == 403


def test_overview_content(client):
    post_sos(client, "ov-prio", 0, headers={"X-Role": "priority_citizen"})
    burst(client)
    ov = client.get("/api/dispatch/overview", headers=OP).json()
    assert set(ov) == {"sos", "shelters", "brigades", "alerts", "zones", "routing"}
    assert ov["sos"][0]["priority"] == 1 and len(ov["sos"]) == 5
    assert len(ov["shelters"]) == 14 and all("occupancy_pct" in s and "is_open" in s for s in ov["shelters"])
    assert len(ov["brigades"]) == 6 and ov["alerts"][0]["status"] == "open"
    khatai = next(z for z in ov["zones"] if z["name"] == "Khatai")
    assert khatai["active_sos"] == 5 and khatai["priority_sos"] == 1
    assert ov["routing"]["mode"] == "online" and ov["routing"]["active_provider"] == "external"
    assert ov["routing"]["breaker"]["state"] == "closed"


def test_demo_requires_role_and_reset_clears(client):
    assert client.post("/api/demo/sos-burst", json={"lat": 40.38, "lon": 49.9}).status_code == 403
    assert client.post("/api/demo/reset").status_code == 403
    confirm(client, burst(client)["alerts"][0]["id"])
    assert client.post("/api/demo/reset", headers=SIM).json() == {"status": "ok"}
    ov = client.get("/api/dispatch/overview", headers=OP).json()
    assert ov["sos"] == [] and ov["alerts"] == []
    assert all(b["status"] == "available" for b in ov["brigades"])
    assert not any(s["is_open"] for s in ov["shelters"] if s["is_reserve"])


# --- live events -----------------------------------------------------------------------

def test_websocket_receives_alert_created(client):
    with client.websocket_connect("/api/ws/dispatch") as ws:
        assert ws.receive_json()["type"] == "hello"
        burst(client)
        client.post("/api/routing/external/up", headers=OP)  # sentinel: last event we expect
        types = []
        for _ in range(50):
            msg = ws.receive_json()
            types.append(msg["type"])
            if msg["type"] == "routing_status":
                break
    assert types.count("sos_created") == 4 and "alert_created" in types
    assert types[-1] == "routing_status"
