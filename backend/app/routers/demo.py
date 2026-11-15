"""Demo helpers for the jury demo and the simulator (dispatcher, simulator roles)."""
import asyncio

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal, get_db
from ..errors import api_error
from ..schemas import AlertOut, BurstOut, SimulateIn, SOSBurst, SOSOut
from ..services.simulation import simulation
from ..services import demo as svc
from ..services.ws import publish, publish_alert
from .auth import require_staff

router = APIRouter(tags=["demo"], dependencies=[Depends(require_staff)])


@router.post("/demo/sos-burst", response_model=BurstOut)
def sos_burst(body: SOSBurst, db: Session = Depends(get_db)):
    created, alert_events = svc.sos_burst(db, body)
    unique_alerts = {a.id: a for _, a in alert_events}  # created then updated -> one entry, latest state
    out = BurstOut(sos=[SOSOut.model_validate(s) for s in created],
                   alerts=[AlertOut.model_validate(a) for a in unique_alerts.values()])
    for s in out.sos:
        publish("sos_created", s)
    for event in alert_events:
        publish_alert(event)
    return out


@router.post("/demo/reset")
def reset(db: Session = Depends(get_db)):
    simulation.stop()
    svc.reset(db)
    publish("demo_reset", {})
    return {"status": "ok"}


def _tick() -> dict:
    with SessionLocal() as db:
        return simulation.tick(db)


async def _runner(generation: int) -> None:
    """One tick per SIM_TICK_S until the simulation stops, finishes or is restarted."""
    while simulation.running and simulation.generation == generation:
        await run_in_threadpool(_tick)
        await asyncio.sleep(config.SIM_TICK_S)


_tasks: set = set()


@router.post("/demo/simulate")
async def simulate(body: SimulateIn):
    def start():
        with SessionLocal() as db:
            return simulation.start(db, body.citizens, body.zone_id, body.speed)
    try:
        status = await run_in_threadpool(start)
    except ValueError:
        raise api_error(404, "unknown_zone", "Unknown zone")
    task = asyncio.create_task(_runner(simulation.generation))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    publish("sim_tick", simulation.status(positions=True))
    return status


@router.post("/demo/simulate/stop")
def simulate_stop():
    status = simulation.stop()
    publish("sim_tick", status)
    return status
