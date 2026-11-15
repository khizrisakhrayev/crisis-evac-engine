import os

collect_ignore = ["load"]  # tests/load/flood_test.py is a standalone load script
import tempfile

import pytest

# Point the app at a throwaway DB before backend modules are imported.
_tmpdir = tempfile.mkdtemp(prefix="crisis-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"
os.environ["LIVE_STREET_GEOMETRY"] = "0"  # never call the public OSM router from tests

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402


from backend.app import config  # noqa: E402
from tests.helpers import STAFF  # noqa: E402

# Drop 3 defaults, saved so flood tests can restore the real limits (monkeypatch).
DROP3_DEFAULTS = {k: getattr(config, k) for k in (
    "SOS_RATE_PER_IP", "SOS_RATE_PER_CITIZEN", "SPAM_DISTINCT_CITIZENS_PER_IP", "OVERVIEW_CACHE_TTL_S")}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # runs lifespan -> create_all + seed
        yield c


@pytest.fixture(scope="session", autouse=True)
def auth_headers(client):
    """One dispatcher login per session; every staff call in the suite uses these headers (tests.helpers.STAFF)."""
    r = client.post("/api/auth/login", json={"username": "dispatcher", "password": config.STAFF_USERS["dispatcher"][1]})
    assert r.status_code == 200, r.text
    STAFF.clear()
    STAFF["Authorization"] = f"Bearer {r.json()['access_token']}"
    return STAFF


@pytest.fixture(autouse=True)
def relaxed_flood_limits(monkeypatch):
    """The whole suite shares one client IP: lift SOS limits / spam rule / overview cache except in flood tests."""
    monkeypatch.setattr(config, "SOS_RATE_PER_IP", 10_000)
    monkeypatch.setattr(config, "SOS_RATE_PER_CITIZEN", 10_000)
    monkeypatch.setattr(config, "SPAM_DISTINCT_CITIZENS_PER_IP", 10_000)
    monkeypatch.setattr(config, "OVERVIEW_CACHE_TTL_S", 0)


def reset_state():
    """Demo reset: clears SOS/alerts, frees brigades, closes reserves, reopens roads, seed occupancy."""
    from backend.app.db import SessionLocal
    from backend.app.services import demo

    with SessionLocal() as db:
        demo.reset(db)


@pytest.fixture(autouse=True)
def clean_state(client):
    reset_state()
    yield
    reset_state()
