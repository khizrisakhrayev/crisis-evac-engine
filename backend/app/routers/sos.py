from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import api_error
from ..schemas import SOSCreate, SOSOut, SOSStatus
from ..services import crisis
from ..services import sos as svc
from .auth import PRIORITY_ROLES, current_role

router = APIRouter(tags=["sos"])


@router.post("/sos", response_model=SOSOut, status_code=201)
def create_sos(body: SOSCreate, role: str = Depends(current_role), db: Session = Depends(get_db)):
    sos = svc.submit_sos(db, body, priority_citizen=role in PRIORITY_ROLES)
    crisis.on_sos_created(db, sos)
    return sos


@router.get("/sos", response_model=list[SOSOut])
def list_sos(status: SOSStatus | None = None, zone_id: int | None = None,
             priority: int | None = Query(None, ge=1, le=2), db: Session = Depends(get_db)):
    return svc.list_sos(db, status, zone_id, priority)


@router.post("/sos/{sos_id}/safe", response_model=SOSOut)
def mark_safe(sos_id: int, db: Session = Depends(get_db)):
    sos = svc.mark_safe(db, sos_id)
    if sos is None:
        raise api_error(404, "sos_not_found", "SOS not found")
    return sos
