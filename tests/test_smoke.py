from sqlalchemy import func, select

from backend.app.db import SessionLocal
from backend.app.models import Brigade, RoadEdge, RoadNode, Shelter, Zone
from backend.app.seed import seed_if_empty

BAKU_LAT = (40.33, 40.46)
BAKU_LON = (49.78, 49.96)


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_shelters_seeded(client):
    data = client.get("/api/shelters").json()
    assert len(data) == 14  # 10 open + 4 closed reserves
    assert sum(s["is_open"] for s in data) == 10 and sum(s["is_reserve"] for s in data) == 4
    assert all("occupancy_pct" in s for s in data)


def test_seed_counts_and_idempotent(client):
    with SessionLocal() as db:
        assert seed_if_empty(db) is False
        count = lambda m: db.scalar(select(func.count()).select_from(m))  # noqa: E731
        assert count(Zone) == 5
        assert count(Shelter) == 14
        assert count(Brigade) == 6
        assert count(RoadNode) == 25
        assert count(RoadEdge) == 45


def test_seed_coords_inside_baku(client):
    with SessionLocal() as db:
        points = [(s.lat, s.lon) for s in db.scalars(select(Shelter))]
        points += [(n.lat, n.lon) for n in db.scalars(select(RoadNode))]
    for lat, lon in points:
        assert BAKU_LAT[0] <= lat <= BAKU_LAT[1] and BAKU_LON[0] <= lon <= BAKU_LON[1], (lat, lon)


def test_frontend_pages(client):
    assert client.get("/").status_code == 200
    assert client.get("/dispatcher").status_code == 200  # follows redirect
    assert client.get("/shared/i18n.js").status_code == 200


def test_confirm_requires_dispatcher_role(client):
    assert client.post("/api/dispatch/alerts/1/confirm").status_code == 403
    r = client.post("/api/dispatch/alerts/999/confirm", headers={"X-Role": "dispatcher"})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "alert_not_found"


def test_sqlite_wal_enabled(client):
    from sqlalchemy import text

    from backend.app.db import engine
    with engine.connect() as conn:
        assert conn.execute(text("PRAGMA journal_mode")).scalar() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000
