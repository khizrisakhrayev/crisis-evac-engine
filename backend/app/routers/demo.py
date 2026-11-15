"""Demo helpers for the jury demo and the simulator (dispatcher, simulator roles)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import AlertOut, BurstOut, SOSBurst, SOSOut
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
    svc.reset(db)
    publish("demo_reset", {})
    return {"status": "ok"}
