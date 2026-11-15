from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, computed_field

HazardType = Literal["fire", "collapse", "flood", "medical"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ZoneOut(ORM):
    id: int
    name: str
    center_lat: float
    center_lon: float


class ShelterOut(ORM):
    id: int
    name: str
    type: str
    lat: float
    lon: float
    capacity: int
    current: int
    zone_id: int
    is_open: bool
    distance_m: float | None = None

    @computed_field
    @property
    def occupancy_pct(self) -> float:
        return round(100 * self.current / self.capacity, 1) if self.capacity else 100.0


class BrigadeOut(ORM):
    id: int
    name: str
    status: str
    zone_id: int


class SOSCreate(BaseModel):
    lat: float
    lon: float
    hazard_type: HazardType
    citizen_id: str


class SOSOut(ORM):
    id: int
    citizen_id: str
    lat: float
    lon: float
    hazard_type: str
    status: str
    zone_id: int | None
    created_at: datetime


class AlertOut(ORM):
    id: int
    kind: str
    reason: str
    zone_id: int | None
    shelter_id: int | None
    status: str
    created_at: datetime


class OccupancyUpdate(BaseModel):
    current: int


class RouteOut(BaseModel):
    shelter: ShelterOut
    path: list[list[float]]
    rerouted: bool = False
    reason: str | None = None
