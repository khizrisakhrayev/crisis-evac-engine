from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, computed_field

from . import config

HazardType = Literal["fire", "collapse", "flood", "medical"]
SOSStatus = Literal["active", "safe", "resolved"]

# DB stores naive UTC; emit ISO-8601 with 'Z' so browsers don't read it as local time.
UTCDateTime = Annotated[datetime, PlainSerializer(lambda d: d.isoformat(timespec="seconds") + "Z", return_type=str)]


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

    @computed_field
    @property
    def occupancy_pct(self) -> float:
        return round(100 * self.current / self.capacity, 1) if self.capacity else 100.0


class NearestShelterOut(ShelterOut):
    distance_m: int
    zone: str

    @computed_field
    @property
    def is_full(self) -> bool:
        return self.occupancy_pct >= config.REROUTE_OCCUPANCY_PCT


class BrigadeOut(ORM):
    id: int
    name: str
    status: str
    zone_id: int


class SOSCreate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    hazard_type: HazardType
    citizen_id: str = Field(min_length=1, max_length=64)


class SOSOut(ORM):
    id: int
    citizen_id: str
    lat: float
    lon: float
    hazard_type: str
    status: str
    zone_id: int | None
    created_at: UTCDateTime


class AlertOut(ORM):
    id: int
    kind: str
    reason: str
    zone_id: int | None
    shelter_id: int | None
    status: str
    created_at: UTCDateTime


class OccupancyUpdate(BaseModel):
    current: int


class RouteOut(BaseModel):
    shelter: ShelterOut
    path: list[list[float]]
    rerouted: bool = False
    reason: str | None = None
