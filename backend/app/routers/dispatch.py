from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from ..db import SessionLocal, get_db
from ..errors import api_error
from ..schemas import AlertOut, BrigadeOut, ConfirmOut, OverviewOut, ShelterOut
from ..services import dispatch as svc
from ..services.ws import manager, publish
from ..services.auth import decode_token
from .auth import STAFF_ROLES, require_staff

router = APIRouter(tags=["dispatch"])
DISPATCHER = [Depends(require_staff)]


def _overview_body() -> bytes:
    with SessionLocal() as db:
        return svc.overview_cache.get(db)


@router.get("/dispatch/overview", response_model=OverviewOut, dependencies=DISPATCHER)
async def overview():
    # Cached 1 s: a cache hit is served straight from the event loop, a miss builds it in a worker thread.
    body = svc.overview_cache.fresh() or await run_in_threadpool(_overview_body)
    return Response(content=body, media_type="application/json")


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
async def ws_dispatch(ws: WebSocket, token: str | None = Query(default=None)):
    claims = decode_token(token) if token else None
    if claims is None or claims.get("role") not in STAFF_ROLES:
        await ws.close(code=4401)  # rejected before accept: no / bad / non-staff token
        return
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "hello", "data": None})
        while True:
            await ws.receive_text()  # keep-alive; client messages ignored for now
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
