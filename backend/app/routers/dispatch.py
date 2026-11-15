from typing import Literal

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import api_error
from ..schemas import AlertOut, BrigadeOut, ConfirmOut, OverviewOut, ShelterOut
from ..services import dispatch as svc
from ..services.ws import manager, publish
from .auth import require_role

router = APIRouter(tags=["dispatch"])
DISPATCHER = [Depends(require_role("dispatcher"))]


@router.get("/dispatch/overview", response_model=OverviewOut, dependencies=DISPATCHER)
def overview(db: Session = Depends(get_db)):
    return svc.overview(db)


@router.get("/dispatch/alerts", response_model=list[AlertOut], dependencies=DISPATCHER)
def list_alerts(status: Literal["open", "confirmed"] | None = None, db: Session = Depends(get_db)):
    return svc.list_alerts(db, status)


@router.post("/dispatch/alerts/{alert_id}/confirm", response_model=ConfirmOut, dependencies=DISPATCHER)
def confirm_alert(alert_id: int, db: Session = Depends(get_db)):
    try:
        alert, brigade, shelter = svc.confirm_alert(db, alert_id)
    except svc.AlertNotFound:
        raise api_error(404, "alert_not_found", "Alert not found")
    except svc.AlertAlreadyConfirmed:
        raise api_error(409, "alert_already_confirmed", "Alert already confirmed")
    out = ConfirmOut(alert=AlertOut.model_validate(alert),
                     brigade=BrigadeOut.model_validate(brigade) if brigade else None,
                     shelter=ShelterOut.model_validate(shelter))
    publish("alert_confirmed", out.alert)
    if out.brigade:
        publish("brigade_updated", out.brigade)
    publish("shelter_updated", out.shelter)
    return out


@router.post("/dispatch/brigades/{brigade_id}/release", response_model=BrigadeOut, dependencies=DISPATCHER)
def release_brigade(brigade_id: int, db: Session = Depends(get_db)):
    brigade = svc.release_brigade(db, brigade_id)
    if brigade is None:
        raise api_error(404, "brigade_not_found", "Brigade not found")
    out = BrigadeOut.model_validate(brigade)
    publish("brigade_updated", out)
    return out


@router.websocket("/ws/dispatch")
async def ws_dispatch(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "hello", "data": None})
        while True:
            await ws.receive_text()  # keep-alive; client messages ignored for now
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
