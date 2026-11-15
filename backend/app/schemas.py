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
    is_accessible: bool

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
    priority: int
    is_priority_citizen: bool
    created_at: UTCDateTime

    @computed_field
    @property
    def priority_label(self) -> str:  # code, translated by the UI
        return config.SOS_PRIORITY_LABELS.get(self.priority, "normal")


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
    shelter: NearestShelterOut | None  # None only when reason == "no_accessible_route"
    path: list[list[float]]  # [[lat, lon], ...]; [] when no accessible route
    distance_m: int | None
    eta_min: int | None
    rerouted: bool = False
    # shelter_full | road_closed | all_shelters_full | shelter_not_accessible | no_accessible_route
    reason: str | None = None
    original_shelter_id: int | None = None
    provider: str | None  # external | local-graph | straight-line (never straight-line when accessible)
    edge_ids: list[int] = []
    accessible: bool = False  # route restricted to wheelchair-accessible edges and shelters
    needs_medical_transport: bool = False


class RoadOut(BaseModel):
    id: int
    from_node: int
    to_node: int
    from_lat: float
    from_lon: float
    to_lat: float
    to_lon: float
    length_m: float
    is_closed: bool
    is_accessible: bool


class RoutingStatusOut(BaseModel):
    external_up: bool
    active_provider: str
