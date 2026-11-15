"""Demo helpers: SOS burst (fires a Red Alert) and full demo reset. Also used by the test suite."""
import math
import uuid

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from .. import config
from ..models import SOS, Alert, Brigade, RoadEdge, Shelter
from ..schemas import SOSBurst, SOSCreate
from ..seed import SHELTERS
from . import crisis
from . import sos as sos_svc
from .routing_provider import invalidate_graph

M_PER_DEG_LAT = 111_320


def burst_points(lat: float, lon: float, count: int, radius_m: float) -> list[tuple[float, float]]:
    """Deterministic scatter: evenly spaced angles, alternating half/full radius."""
    pts = []
    for i in range(count):
        angle = 2 * math.pi * i / count
        r = radius_m if i % 2 else radius_m / 2
        pts.append((lat + r * math.cos(angle) / M_PER_DEG_LAT,
                    lon + r * math.sin(angle) / (M_PER_DEG_LAT * math.cos(math.radians(lat)))))
    return pts


def sos_burst(db: Session, body: SOSBurst) -> tuple[list[SOS], list]:
    """`count` SOS from distinct citizens through the normal SOS service, so alert rules fire."""
    tag = uuid.uuid4().hex[:6]
    created, alert_events = [], []
    for i, (la, lo) in enumerate(burst_points(body.lat, body.lon, body.count, config.DEMO_BURST_RADIUS_M)):
        s = sos_svc.submit_sos(db, SOSCreate(lat=la, lon=lo, hazard_type=body.hazard_type,
                                             citizen_id=f"demo-{tag}-{i + 1}"))
        created.append(s)
        event = crisis.on_sos_created(db, s)
        if event:
            alert_events.append(event)
    return created, alert_events


def reset(db: Session) -> None:
    """Clear SOS/alerts, free brigades, drop temporary and close reserve shelters, reopen roads, seed occupancy."""
    db.execute(delete(Alert))
    db.execute(delete(SOS))
    db.execute(update(Brigade).values(status="available", target_zone_id=None, alert_id=None))
    db.execute(delete(Shelter).where(Shelter.is_temporary.is_(True)))
    db.execute(update(Shelter).where(Shelter.is_reserve.is_(True)).values(is_open=False, current=0))
    for name, *_, current in SHELTERS:
        db.execute(update(Shelter).where(Shelter.name == name, Shelter.is_reserve.is_(False))
                   .values(current=current, is_open=True))
    db.execute(update(RoadEdge).values(is_closed=False))
    db.commit()
    invalidate_graph(db)
    config.EXTERNAL_ROUTING_UP = True
