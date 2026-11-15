"""Challenge Drop 2: external routing API outage -> circuit breaker + local backup routing chain."""
import time

import pytest
from sqlalchemy import delete, func, select

from backend.app import config
from backend.app.db import SessionLocal
from backend.app.models import DistanceMatrix, RouteCache, Shelter, Zone
from backend.app.services import routing_provider as rp
from backend.app.services.circuit_breaker import CircuitBreaker

OP = {"X-Role": "dispatcher"}
PRIO = {"X-Role": "priority_citizen"}
ORIGIN = {"from_lat": 40.3777, "from_lon": 49.8920}


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = FakeClock()
    monkeypatch.setattr(rp.breaker, "clock", c)  # installed before any failure is recorded
    return c


def route(client, headers=None, **params):
    r = client.get("/api/route", params={**ORIGIN, **params}, headers=headers or {})
    assert r.status_code == 200, r.text
    return r.json()


def set_mode(client, mode):
    assert client.post(f"/api/routing/external/{mode}", headers=OP).status_code == 200


# --- circuit breaker unit tests ----------------------------------------------------

def make_breaker():
    c = FakeClock()
    changes = []
    b = CircuitBreaker(2, 30, clock=c, on_state_change=lambda old, new: changes.append((old, new)))
    return b, c, changes


def test_breaker_opens_after_two_failures_and_skips_calls():
    b, c, changes = make_breaker()
    assert b.allow_request()
    b.record_failure("503")
    assert b.state == "closed" and b.consecutive_failures == 1
    assert b.allow_request()
    b.record_failure("503")
    assert b.state == "open" and changes == [("closed", "open")]
    assert b.allow_request() is False  # skipped immediately while open
    assert b.snapshot()["seconds_until_retry"] == 30 and b.snapshot()["last_error"] == "503"


def test_breaker_half_open_after_cooldown_then_closes_on_success():
    b, c, changes = make_breaker()
    b.record_failure("x")
    b.record_failure("x")
    c.now += 29
    assert b.allow_request() is False
    c.now += 1
    assert b.state == "half_open"
    assert b.allow_request() is True        # the single trial call
    assert b.allow_request() is False       # no second trial while one is in flight
    b.record_success()
    assert b.state == "closed" and b.consecutive_failures == 0
    assert changes == [("closed", "open"), ("open", "half_open"), ("half_open", "closed")]


def test_breaker_reopens_when_trial_fails():
    b, c, _ = make_breaker()
    b.record_failure("x")
    b.record_failure("x")
    c.now += 31
    assert b.allow_request()
    b.record_failure("still down")
    assert b.state == "open" and b.allow_request() is False
    assert b.seconds_until_retry() == 30


def test_external_unexpected_exception_still_resolves_half_open(monkeypatch, clock):
    rp.breaker.record_failure("x")
    rp.breaker.record_failure("x")
    clock.now += config.BREAKER_COOLDOWN_S
    monkeypatch.setattr(rp.ExternalRoutingProvider, "_remote", lambda *a, **k: 1 / 0)
    from types import SimpleNamespace
    with pytest.raises(rp.ExternalAPIError):
        rp.EXTERNAL.route(None, None, 40.38, 49.9, SimpleNamespace(id=1, lat=40.38, lon=49.91))
    assert rp.breaker.state == "open"  # trial failure recorded -> re-opened, not stuck in half_open


# --- external API down (HTTP 503) -----------------------------------------------------

def test_down_503_falls_back_and_breaker_opens(client, clock):
    set_mode(client, "down")
    r = route(client)
    assert r["degraded"] is True and r["mode"] == "fallback" and r["provider"] == "local-graph"
    assert r["notice_code"] == "offline_backup_routing" and r["distance_m"] > 0 and len(r["path"]) >= 3
    route(client)
    status = client.get("/api/routing/status").json()
    assert status["breaker"]["state"] == "open" and status["breaker"]["consecutive_failures"] == 2
    assert status["mode"] == "fallback" and status["active_provider"] == "local-graph"

    calls = rp.EXTERNAL.calls
    for _ in range(3):
        assert route(client)["provider"] == "local-graph"
    assert rp.EXTERNAL.calls == calls  # circuit open: external API not called at all


def test_slow_api_times_out_quickly(client, clock, monkeypatch):
    monkeypatch.setattr(config, "EXTERNAL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(config, "EXTERNAL_SLOW_LATENCY_S", 0.5)
    set_mode(client, "slow")
    t0 = time.monotonic()
    r = route(client)
    assert time.monotonic() - t0 < 1.0
    assert r["degraded"] is True and r["provider"] == "local-graph"
    assert "timeout" in client.get("/api/routing/status").json()["breaker"]["last_error"]


def test_recovers_to_online_after_cooldown(client, clock):
    set_mode(client, "down")
    route(client)
    route(client)
    assert client.get("/api/routing/status").json()["breaker"]["state"] == "open"
    set_mode(client, "up")
    assert route(client)["degraded"] is True  # still open: cooldown not elapsed
    clock.now += config.BREAKER_COOLDOWN_S
    r = route(client)  # half-open trial succeeds
    assert r["degraded"] is False and r["mode"] == "online" and r["provider"] == "external"
    assert r["notice_code"] is None
    assert client.get("/api/routing/status").json()["mode"] == "online"


# --- local backup chain -----------------------------------------------------------------

def _break_local_graph(monkeypatch):
    def fail(*a, **k):
        raise rp.RoutingUnavailable("mocked local graph failure")
    monkeypatch.setattr(rp.LocalGraphProvider, "route", fail)


def test_route_cache_then_static_matrix(client, clock, monkeypatch):
    warm = route(client)  # online: fills the cache
    assert warm["provider"] == "external"
    assert client.get("/api/routing/status").json()["cache_size"] >= 1
    set_mode(client, "down")
    _break_local_graph(monkeypatch)
    cached = route(client)
    assert cached["provider"] == "route-cache" and cached["degraded"] is True
    assert cached["path"] == warm["path"] and cached["shelter"]["id"] == warm["shelter"]["id"]

    with SessionLocal() as db:
        db.execute(delete(RouteCache))
        db.commit()
    r = route(client)
    assert r["provider"] == "static-matrix" and len(r["path"]) == 2 and r["distance_m"] > 0
    assert r["notice_code"] == "offline_backup_routing"


def test_cache_rejected_when_a_cached_road_is_closed(client, clock, monkeypatch):
    warm = route(client)
    set_mode(client, "down")
    _break_local_graph(monkeypatch)
    client.post(f"/api/roads/{warm['edge_ids'][0]}/close", headers=OP)
    assert route(client)["provider"] == "static-matrix"


def test_priority_citizen_with_external_down(client, clock, monkeypatch):
    set_mode(client, "down")
    r = route(client, PRIO)
    assert r["accessible"] is True and r["provider"] == "local-graph" and r["degraded"] is True
    _break_local_graph(monkeypatch)
    cached = route(client, PRIO)  # accessible route cached above
    assert cached["provider"] == "route-cache" and cached["accessible"] is True
    with SessionLocal() as db:
        db.execute(delete(RouteCache))
        db.commit()
    none = route(client, PRIO)
    assert none["reason"] == "no_accessible_route" and none["provider"] is None  # never static-matrix
    assert none["needs_medical_transport"] is True and none["degraded"] is True


def test_normal_cache_not_used_for_priority(client, clock, monkeypatch):
    route(client)  # caches a non-accessible route for a normal citizen
    set_mode(client, "down")
    _break_local_graph(monkeypatch)
    with SessionLocal() as db:
        db.execute(delete(RouteCache).where(RouteCache.accessible.is_(True)))
        db.commit()
    assert route(client, PRIO)["reason"] == "no_accessible_route"


# --- status / health / matrix ---------------------------------------------------------------

def test_health_always_200(client, clock, monkeypatch):
    monkeypatch.setattr(config, "EXTERNAL_TIMEOUT_S", 0.2)
    monkeypatch.setattr(config, "EXTERNAL_SLOW_LATENCY_S", 0.3)
    for mode, expected in (("up", "online"), ("down", "fallback"), ("slow", "fallback")):
        set_mode(client, mode)
        r = client.get("/api/health")
        assert r.status_code == 200 and r.json() == {"status": "ok", "routing_mode": expected}


def test_status_shape_and_roles(client):
    s = client.get("/api/routing/status").json()
    assert set(s) == {"mode", "external_mode", "external_up", "breaker", "active_provider", "cache_size"}
    assert set(s["breaker"]) >= {"state", "consecutive_failures", "seconds_until_retry", "last_error"}
    for mode in ("up", "down", "slow"):
        assert client.post(f"/api/routing/external/{mode}").status_code == 403
    assert client.post("/api/routing/external/slow", headers={"X-Role": "simulator"}).json()["external_mode"] == "slow"
    ov = client.get("/api/dispatch/overview", headers=OP).json()
    assert ov["routing"]["external_mode"] == "slow"


def test_distance_matrix_precomputed(client):
    with SessionLocal() as db:
        n = db.scalar(select(func.count()).select_from(DistanceMatrix))
        zones = db.scalar(select(func.count()).select_from(Zone))
        shelters = db.scalar(select(func.count(Shelter.id)).where(Shelter.is_temporary.is_(False)))
    assert n == zones * shelters
