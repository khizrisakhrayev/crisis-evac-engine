from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal, get_db
from ..errors import api_error
from ..schemas import SOSCreate, SOSOut, SOSStatus
from ..services import crisis
from ..services import sos as svc
from ..services.rate_limit import limiter
from ..services.spam import spam_filter
from ..services.ws import publish, publish_alert
from .auth import PRIORITY_ROLES, client_ip, current_role

router = APIRouter(tags=["sos"])


def _rate_limited(retry: int) -> JSONResponse:
    spam_filter.count("rate_limited")
    return JSONResponse(status_code=429, headers={"Retry-After": str(retry)}, content={"detail": {
        "code": "rate_limited", "message": "Too many SOS requests", "retry_after": retry}})


def _store(body: SOSCreate, priority: bool, suspected: bool, ip: str) -> SOSOut:
    """DB part of POST /sos (worker thread): insert/refresh, Red Alert check, live events."""
    with SessionLocal() as db:
        sos = svc.submit_sos(db, body, priority_citizen=priority, suspected_spam=suspected, source_ip=ip)
        out = SOSOut.model_validate(sos)
        if not sos.suspected_spam:
            alert_event = crisis.on_sos_created(db, sos)
            publish("sos_created", out)
            publish_alert(alert_event)
    return out


@router.post("/sos", response_model=SOSOut, status_code=201,
             responses={200: {"description": "Duplicate / idempotent replay: the existing SOS"},
                        429: {"description": "Rate limited (Retry-After header)"}})
async def create_sos(body: SOSCreate, request: Request, response: Response, role: str = Depends(current_role),
                     idempotency_key: str | None = Header(default=None, max_length=128)):
    """Flood protection runs in memory before any DB write: duplicate / idempotent replay -> 200 with the
    existing SOS; per-IP and per-citizen sliding-window limits -> 429; many citizen ids from one IP ->
    stored as suspected_spam (never for priority citizens), which never raises a Red Alert or a live event."""
    ip = client_ip(request)
    priority = role in PRIORITY_ROLES
    cached = spam_filter.existing(ip, body, idempotency_key, role)
    if cached is not None:
        response.status_code = 200
        return cached
    for key, limit in ((f"sos-ip:{ip}", config.SOS_RATE_PER_IP), (f"sos-cid:{body.citizen_id}", config.SOS_RATE_PER_CITIZEN)):
        ok, retry = limiter.hit(key, limit, config.RATE_WINDOW_S)
        if not ok:
            return _rate_limited(retry)
    suspected = not priority and spam_filter.is_suspected(ip, body.citizen_id)

    # Only accepted SOS reach the thread pool + DB; rejections above never leave the event loop.
    out = await run_in_threadpool(_store, body, priority, suspected, ip)
    spam_filter.remember(ip, body, idempotency_key, out, role)
    return out


@router.get("/sos", response_model=list[SOSOut])
def list_sos(status: SOSStatus | None = None, zone_id: int | None = None,
             priority: int | None = Query(None, ge=1, le=2), include_spam: bool = False,
             db: Session = Depends(get_db)):
    return svc.list_sos(db, status, zone_id, priority, include_spam=include_spam)


@router.post("/sos/{sos_id}/safe", response_model=SOSOut)
def mark_safe(sos_id: int, db: Session = Depends(get_db)):
    sos = svc.mark_safe(db, sos_id)
    if sos is None:
        raise api_error(404, "sos_not_found", "SOS not found")
    spam_filter.forget(sos_id)
    out = SOSOut.model_validate(sos)
    publish("sos_updated", out)
    return out
