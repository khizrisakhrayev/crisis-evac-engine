"""Live events for dispatchers over WS /api/ws/dispatch. Message shape: {"type": <code>, "data": {...}}.

publish() never blocks a request: it appends to a thread-safe queue. A background task (started in the
app lifespan) drains it at most WS_MAX_MESSAGES_PER_S times per second; when several events are waiting
they are coalesced into one {"type": "batch", "data": [event, ...]} message.
"""
import asyncio
import collections
import logging

from fastapi import WebSocket
from fastapi.encoders import jsonable_encoder

from .. import config

log = logging.getLogger(__name__)
MAX_QUEUE = 2000  # oldest events dropped beyond this (UI refetches the overview anyway)


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
_queue: collections.deque = collections.deque(maxlen=MAX_QUEUE)


def _invalidate_overview(event_type: str) -> None:
    if event_type not in ("sos_created", "sim_tick"):  # floods / sim ticks rely on the 1 s TTL
        from .dispatch import overview_cache

        overview_cache.invalidate()


def publish(event_type: str, data=None) -> None:
    """Queue an event from sync or async code. Never raises, never blocks."""
    try:
        _invalidate_overview(event_type)
        if manager.active:
            _queue.append({"type": event_type, "data": jsonable_encoder(data)})
    except Exception:
        log.warning("publish %s failed", event_type, exc_info=True)


async def flush() -> None:
    if not _queue:
        return
    events = []
    while _queue:
        events.append(_queue.popleft())
    await manager.broadcast(events[0] if len(events) == 1 else {"type": "batch", "data": events})


async def drain_forever() -> None:
    while True:
        try:
            await flush()
        except Exception:
            log.warning("ws flush failed", exc_info=True)
        await asyncio.sleep(1 / config.WS_MAX_MESSAGES_PER_S)


def publish_alert(event) -> None:
    """Publish an (event_type, Alert) tuple returned by services.crisis, if any."""
    if event:
        from ..schemas import AlertOut

        publish(event[0], AlertOut.model_validate(event[1]))
