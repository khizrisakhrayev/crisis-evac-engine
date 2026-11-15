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
    """Reopen all roads, restore seeded shelter occupancy/open flags, external routing up."""
    from sqlalchemy import update

    from backend.app import config
    from backend.app.db import SessionLocal
    from backend.app.models import RoadEdge, Shelter
    from backend.app.seed import SHELTERS

    config.EXTERNAL_ROUTING_UP = True
    with SessionLocal() as db:
        db.execute(update(RoadEdge).values(is_closed=False))
        for i, (*_, current) in enumerate(SHELTERS, start=1):
            db.execute(update(Shelter).where(Shelter.id == i).values(current=current, is_open=True))
        db.commit()


@pytest.fixture(autouse=True)
def clean_state(client):
    reset_state()
    yield
    reset_state()
