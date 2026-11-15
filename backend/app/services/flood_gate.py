"""Raw ASGI fast path for SOS floods: an IP already over SOS_RATE_PER_IP gets 429 before FastAPI routing,
body parsing, validation or the thread pool. Everything else (duplicates, per-citizen limit, spam) stays
in routers/sos.py; this gate only rejects what that router would reject anyway.
"""
import json

from .. import config
from .rate_limit import limiter
from .spam import spam_filter


class SOSFloodGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"] == "/api/sos":
            ip = scope["client"][0] if scope.get("client") else "unknown"
            retry = limiter.blocked(f"sos-ip:{ip}", config.SOS_RATE_PER_IP, config.RATE_WINDOW_S)
            if retry:
                spam_filter.count("rate_limited")
                body = json.dumps({"detail": {"code": "rate_limited", "message": "Too many SOS requests",
                                              "retry_after": retry}}).encode()
                await send({"type": "http.response.start", "status": 429, "headers": [
                    (b"content-type", b"application/json"), (b"retry-after", str(retry).encode()),
                    (b"content-length", str(len(body)).encode())]})
                await send({"type": "http.response.body", "body": body})
                return
        await self.app(scope, receive, send)
