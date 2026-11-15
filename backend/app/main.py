import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import models  # noqa: F401  (register tables)
from .db import Base, SessionLocal, engine
from .routers import auth, demo, dispatch, routing, shelters, sos
from .seed import seed_if_empty
from .services import geo, ws
from .services.auth import seed_users
from .services.flood_gate import SOSFloodGate
from .services.routing_provider import build_distance_matrix

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_if_empty(db)
        geo.load_zones(db)
        build_distance_matrix(db)  # static backup distances (no-op if already built)
        seed_users(db)             # staff accounts (passwords from env)
    drain = asyncio.create_task(ws.drain_forever())  # WebSocket events: queued, coalesced, never block requests
    yield
    drain.cancel()


app = FastAPI(title="Urban Crisis & Crowd Evacuation Engine", lifespan=lifespan)
app.add_middleware(SOSFloodGate)  # Drop 3: 429 for flooding IPs before routing / parsing / thread pool


@app.exception_handler(RequestValidationError)
async def validation_error(_request: Request, exc: RequestValidationError):
    # Same language-neutral shape as api_error(): {"detail": {"code", "message", ...}}
    fields = [{"loc": list(e.get("loc", ())), "type": e.get("type")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": {
        "code": "validation_error", "message": "Request validation failed", "fields": fields}})


@app.exception_handler(Exception)
async def unhandled_error(_request: Request, exc: Exception):
    # Last line of defence: never leak a raw traceback to clients.
    logging.getLogger("app").exception("unhandled error", exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": {"code": "internal_error", "message": "Internal error"}})


for r in (shelters, routing, sos, dispatch, demo, auth):
    app.include_router(r.router, prefix="/api")


@app.api_route("/dispatcher", methods=["GET", "HEAD"], include_in_schema=False)
def dispatcher_redirect():
    return RedirectResponse("/dispatcher/")


app.mount("/shared", StaticFiles(directory=FRONTEND / "shared"), name="shared")
app.mount("/vendor", StaticFiles(directory=FRONTEND / "vendor"), name="vendor")  # vendored Leaflet (no CDN)
app.mount("/dispatcher", StaticFiles(directory=FRONTEND / "dispatcher", html=True), name="dispatcher")
app.mount("/", StaticFiles(directory=FRONTEND / "citizen", html=True), name="citizen")  # keep last
