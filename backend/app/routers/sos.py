from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..schemas import SOSCreate, SOSOut, SOSStatus
from ..services import crisis
from ..services import sos as svc

router = APIRouter(tags=["sos"])


@router.post("/sos", response_model=SOSOut, status_code=201)
def create_sos(body: SOSCreate, db: Session = Depends(get_db)):
    sos = svc.submit_sos(db, body)
    crisis.on_sos_created(db, sos)
    return sos


@router.get("/sos", response_model=list[SOSOut])
def list_sos(status: SOSStatus | None = None, zone_id: int | None = None, db: Session = Depends(get_db)):
    return svc.list_sos(db, status, zone_id)


@router.post("/sos/{sos_id}/safe", response_model=SOSOut)
def mark_safe(sos_id: int, db: Session = Depends(get_db)):
    sos = svc.mark_safe(db, sos_id)
    if sos is None:
        raise HTTPException(404, "SOS not found")
    return sos
