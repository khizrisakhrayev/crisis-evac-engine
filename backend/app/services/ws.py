"""Live events for dispatchers over WS /api/ws/dispatch. Message shape: {"type": <code>, "data": {...}}."""
import logging

import anyio
from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, event: dict):
        for ws in list(self.active):
            try:
                await ws.send_json(event)
            except Exception:
                self.disconnect(ws)


manager = ConnectionManager()


def publish(event_type: str, data=None) -> None:
    """Broadcast from sync code (FastAPI runs sync routes in worker threads). Never raises."""
    if not manager.active:
        return
    try:
        anyio.from_thread.run(manager.broadcast, {"type": event_type, "data": jsonable_encoder(data)})
    except Exception:  # no event loop (e.g. called outside a request) or a send failure
        log.warning("publish %s failed", event_type, exc_info=True)


def publish_alert(event) -> None:
    """Publish an (event_type, Alert) tuple returned by services.crisis, if any."""
    if event:
        from ..schemas import AlertOut

        publish(event[0], AlertOut.model_validate(event[1]))
