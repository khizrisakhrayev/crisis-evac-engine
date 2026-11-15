import os
import tempfile

import pytest

# Point the app at a throwaway DB before backend modules are imported.
_tmpdir = tempfile.mkdtemp(prefix="crisis-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir, 'test.db')}"

from fastapi.testclient import TestClient  # noqa: E402

from backend.app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:  # runs lifespan -> create_all + seed
        yield c


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
