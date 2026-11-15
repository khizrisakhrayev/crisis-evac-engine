from fastapi import APIRouter, HTTPException

from ..schemas import SOSCreate, SOSOut

router = APIRouter(tags=["sos"])


@router.post("/sos", response_model=SOSOut)
def create_sos(body: SOSCreate):
    raise HTTPException(status_code=501, detail="Not implemented")


@router.post("/sos/{sos_id}/safe", response_model=SOSOut)
def mark_safe(sos_id: int):
    raise HTTPException(status_code=501, detail="Not implemented")
