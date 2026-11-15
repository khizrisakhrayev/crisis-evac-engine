from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect

from ..services.ws import manager
from .auth import require_role

router = APIRouter(tags=["dispatch"])


@router.get("/dispatch/overview")
def overview():
    return {"sos": [], "shelters": [], "brigades": [], "alerts": []}  # TODO


@router.post("/dispatch/alerts/{alert_id}/confirm", dependencies=[Depends(require_role("dispatcher"))])
def confirm_alert(alert_id: int):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.websocket("/ws/dispatch")
async def ws_dispatch(ws: WebSocket):
    await manager.connect(ws)
    try:
        await ws.send_json({"type": "hello"})
        while True:
            await ws.receive_text()  # keep-alive; client messages ignored for now
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)
