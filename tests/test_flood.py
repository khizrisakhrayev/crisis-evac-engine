"""Challenge Drop 3: SOS flood protection, JWT / RBAC on dispatcher operations, overview cache."""
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.app import config
from backend.app.services.auth import create_token
from backend.app.services.rate_limit import SlidingWindowLimiter
from tests.conftest import DROP3_DEFAULTS
from tests.helpers import STAFF

KHATAI = (40.3777, 49.8920)


@pytest.fixture
def real_limits(monkeypatch):
    for k, v in DROP3_DEFAULTS.items():
        if k != "OVERVIEW_CACHE_TTL_S":
            monkeypatch.setattr(config, k, v)


def sos(client, cid, i=0, headers=None, hazard="fire"):
    body = {"lat": KHATAI[0] + i * 0.0003, "lon": KHATAI[1], "hazard_type": hazard, "citizen_id": cid}
    return client.post("/api/sos", json=body, headers=headers or {})


def alerts(client):
    return client.get("/api/dispatch/alerts", headers=STAFF).json()


# --- rate limiting ---------------------------------------------------------------------------------------

def test_limiter_sliding_window_with_fake_clock():
    now = [1000.0]
    lim = SlidingWindowLimiter(clock=lambda: now[0])
    assert [lim.hit("k", 3, 60)[0] for _ in range(3)] == [True, True, True]
    assert lim.hit("k", 3, 60) == (False, 60)          # full: retry when the oldest hit leaves the window
    now[0] += 30
    assert lim.hit("k", 3, 60) == (False, 30)
    assert lim.hit("other", 3, 60)[0]                  # keys are independent
    now[0] += 30                                       # all hits (t=1000) slide out at t=1060
    assert [lim.hit("k", 3, 60)[0] for _ in range(4)] == [True, True, True, False]  # rejected hits not recorded


def test_sos_rate_limited_per_citizen_with_retry_after(client, real_limits):
    codes = [sos(client, "rl-cit", i).status_code for i in range(4)]
    assert codes == [201, 201, 201, 429]  # first creates, two refreshes, then 3/min per citizen is spent
    r = sos(client, "rl-cit", 9)
    assert r.status_code == 429 and r.json()["detail"]["code"] == "rate_limited"
    assert 1 <= int(r.headers["Retry-After"]) <= 60


def test_sos_rate_limited_per_ip(client, monkeypatch):
    monkeypatch.setattr(config, "SOS_RATE_PER_IP", 5)
    codes = [sos(client, f"rl-ip-{i}", i).status_code for i in range(7)]
    assert codes.count(201) == 5 and codes[-2:] == [429, 429]
    ov = client.get("/api/dispatch/overview", headers=STAFF).json()
    assert ov["spam_blocked"]["rate_limited"] == 2


# --- duplicates / idempotency -------------------------------------------------------------------------

def test_duplicate_payload_returns_existing_sos(client, real_limits):
    first = sos(client, "dup-1")
    second = sos(client, "dup-1")
    assert first.status_code == 201 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert client.get("/api/dispatch/overview", headers=STAFF).json()["spam_blocked"]["duplicates"] == 1


def test_idempotency_key_never_creates_two_records(client):
    h = {"Idempotency-Key": "idem-abc"}
    a = sos(client, "idem-1", 0, headers=h)
    b = sos(client, "idem-2", 5, headers=h)  # different payload, same key -> replay
    assert a.status_code == 201 and b.status_code == 200 and b.json()["id"] == a.json()["id"]
    ids = [s["citizen_id"] for s in client.get("/api/sos").json()]
    assert "idem-2" not in ids


# --- spam from one IP -----------------------------------------------------------------------------------

def test_many_citizen_ids_from_one_ip_are_suspected_and_raise_no_alert(client, real_limits):
    out = [sos(client, f"spam-{i}", i).json() for i in range(5 + 6)]
    assert [s["suspected_spam"] for s in out[:5]] == [False] * 5
    assert all(s["suspected_spam"] for s in out[5:])
    # 5 legit SOS from 5 citizens do cluster; the suspected ones never grow or create alerts
    cluster = [a for a in alerts(client) if a["kind"] == "sos_cluster"]
    assert len(cluster) == 1 and not set(cluster[0]["sos_ids"]) & {s["id"] for s in out[5:]}
    ov = client.get("/api/dispatch/overview", headers=STAFF).json()
    assert ov["spam_blocked"]["suspected"] == 6 and ov["sos_total"] == 5
    assert not any(s["suspected_spam"] for s in ov["sos"])
    assert len(client.get("/api/sos", params={"include_spam": True}).json()) == 11


def test_suspected_only_flood_raises_no_alert(client, monkeypatch):
    monkeypatch.setattr(config, "SPAM_DISTINCT_CITIZENS_PER_IP", 0)  # every SOS from this IP is suspected
    assert all(sos(client, f"sp-{i}", i).json()["suspected_spam"] for i in range(8))
    assert alerts(client) == []


def test_priority_citizen_never_marked_spam(client, monkeypatch):
    monkeypatch.setattr(config, "SPAM_DISTINCT_CITIZENS_PER_IP", 0)
    r = sos(client, "prio-flood", headers={"X-Role": "priority_citizen"})
    assert r.status_code == 201 and r.json()["suspected_spam"] is False and r.json()["priority_label"] == "critical"


def test_legitimate_burst_still_raises_one_alert(client, real_limits):
    for i in range(10):  # flood first: this IP is now spamming
        sos(client, f"pre-flood-{i}", i)
    burst = client.post("/api/demo/sos-burst", json={"lat": 40.4093, "lon": 49.8671, "count": 4}, headers=STAFF)
    assert burst.status_code == 200 and len(burst.json()["alerts"]) == 1


# --- JWT / RBAC -------------------------------------------------------------------------------------------

def test_login(client):
    bad = client.post("/api/auth/login", json={"username": "dispatcher", "password": "nope"})
    assert bad.status_code == 401 and bad.json()["detail"]["code"] == "invalid_credentials"
    ok = client.post("/api/auth/login", json={"username": "admin", "password": config.STAFF_USERS["admin"][1]})
    assert ok.status_code == 200 and ok.json()["role"] == "admin" and ok.json()["expires_in"] == 8 * 3600
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {ok.json()['access_token']}"}).json()
    assert me == {"role": "admin", "username": "admin"}


def test_login_rate_limited(client):
    codes = [client.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code for _ in range(6)]
    assert codes == [401] * 5 + [429]


def test_x_role_dispatcher_is_401(client):
    assert client.get("/api/dispatch/overview", headers={"X-Role": "dispatcher"}).status_code == 401
    assert client.post("/api/demo/reset", headers={"X-Role": "admin"}).status_code == 401


def test_confirm_token_checks(client):
    alert_id = client.post("/api/demo/sos-burst", json={"lat": 40.4093, "lon": 49.8671}, headers=STAFF
                           ).json()["alerts"][0]["id"]
    url = f"/api/dispatch/alerts/{alert_id}/confirm"
    token = STAFF["Authorization"].split()[1]
    tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")
    expired = create_token("dispatcher", "dispatcher", expires_s=-10)
    citizen = create_token("someone", "citizen")
    assert client.post(url, headers={"Authorization": f"Bearer {tampered}"}).status_code == 401
    assert client.post(url, headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    r = client.post(url, headers={"Authorization": f"Bearer {citizen}"})
    assert r.status_code == 403 and r.json()["detail"]["code"] == "forbidden_role"
    assert client.post(url, headers=STAFF).status_code == 200


def test_admin_token_is_staff(client):
    admin = create_token("admin", "admin")
    assert client.get("/api/dispatch/overview", headers={"Authorization": f"Bearer {admin}"}).status_code == 200


def test_websocket_requires_token(client):
    for url in ("/api/ws/dispatch", "/api/ws/dispatch?token=garbage",
                f"/api/ws/dispatch?token={create_token('c', 'citizen')}"):
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(url) as ws:
                ws.receive_json()


# --- latency helpers ---------------------------------------------------------------------------------------

def test_overview_capped_and_cached(client, monkeypatch):
    monkeypatch.setattr(config, "OVERVIEW_SOS_LIMIT", 3)
    for i in range(5):
        sos(client, f"cap-{i}", i * 30)
    ov = client.get("/api/dispatch/overview", headers=STAFF).json()
    assert len(ov["sos"]) == 3 and ov["sos_total"] == 5
    monkeypatch.setattr(config, "OVERVIEW_CACHE_TTL_S", 60)
    client.get("/api/dispatch/overview", headers=STAFF)
    sos(client, "cap-new", 200)
    assert client.get("/api/dispatch/overview", headers=STAFF).json()["sos_total"] == 5   # cached
    client.post("/api/routing/external/up", headers=STAFF)                                 # operator change invalidates
    assert client.get("/api/dispatch/overview", headers=STAFF).json()["sos_total"] == 6
