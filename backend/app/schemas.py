from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, computed_field

from . import config

HazardType = Literal["fire", "collapse", "flood", "medical"]
SOSStatus = Literal["active", "safe", "resolved"]

# DB stores naive UTC; emit ISO-8601 with 'Z' so browsers don't read it as local time.
UTCDateTime = Annotated[datetime, PlainSerializer(lambda d: d.isoformat(timespec="seconds") + "Z", return_type=str)]


def occupancy_pct(current: int, capacity: int) -> float:
    """Single definition of occupancy % (1 decimal) used by API output and alert rules."""
    return round(100 * current / capacity, 1) if capacity else 100.0


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
    is_reserve: bool = False
    is_temporary: bool = False

    @computed_field
    @property
    def occupancy_pct(self) -> float:
        return occupancy_pct(self.current, self.capacity)


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
    status: str  # available | dispatched
    zone_id: int
    target_zone_id: int | None = None
    alert_id: int | None = None


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
    suspected_spam: bool = False
    created_at: UTCDateTime

    @computed_field
    @property
    def priority_label(self) -> str:  # code, translated by the UI
        return config.SOS_PRIORITY_LABELS.get(self.priority, "normal")


class AlertOut(ORM):
    id: int
    kind: str  # sos_cluster | shelter_overflow
    severity: str  # red
    zone_id: int | None
    shelter_id: int | None
    lat: float
    lon: float
    sos_count: int
    sos_ids: list[int]
    has_priority_sos: bool
    status: str  # open | confirmed
    action_code: str  # dispatch_brigade_and_open_shelter
    created_at: UTCDateTime
    confirmed_at: UTCDateTime | None = None
    brigade_id: int | None = None
    new_shelter_id: int | None = None
    brigade_shortage: bool = False


class SOSBurst(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    count: int = Field(4, ge=1, le=50)
    hazard_type: HazardType = "fire"


class OccupancyUpdate(BaseModel):
    current: int


class RouteOut(BaseModel):
    shelter: NearestShelterOut | None  # None only when reason == "no_accessible_route"
    path: list[list[float]]  # street geometry [[lat, lon], ...] from the first road node to the shelter; [] if none
    approach: list[list[float]] = []  # straight leg citizen -> first road node (draw dashed); [] for static-matrix
    approach_m: int = 0  # included in distance_m / eta_min
    distance_m: int | None
    eta_min: int | None
    rerouted: bool = False
    # shelter_full | road_closed | all_shelters_full | shelter_not_accessible | no_accessible_route
    reason: str | None = None
    original_shelter_id: int | None = None
    provider: str | None  # external | local-graph | route-cache | static-matrix (never static-matrix if accessible)
    edge_ids: list[int] = []
    accessible: bool = False  # route restricted to wheelchair-accessible edges and shelters
    needs_medical_transport: bool = False
    degraded: bool = False  # answer did not come from the external provider
    mode: str = "online"  # online | fallback
    notice_code: str | None = None  # offline_backup_routing when degraded


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
    geometry: list[list[float]]  # real street polyline from -> to


class BreakerOut(BaseModel):
    state: str  # closed | open | half_open
    consecutive_failures: int
    seconds_until_retry: float
    last_error: str | None = None


class RoutingStatusOut(BaseModel):
    mode: str  # online | fallback
    external_mode: str  # up | down_503 | slow
    external_up: bool
    breaker: BreakerOut
    active_provider: str
    cache_size: int


class ZoneStatsOut(BaseModel):
    id: int
    name: str
    active_sos: int
    priority_sos: int


class SpamBlockedOut(BaseModel):
    rate_limited: int
    duplicates: int
    suspected: int


class OverviewOut(BaseModel):
    sos: list[SOSOut]  # active, priority first, capped at config.OVERVIEW_SOS_LIMIT
    sos_total: int
    sos_priority_total: int
    spam_blocked: SpamBlockedOut
    shelters: list[ShelterOut]
    brigades: list[BrigadeOut]
    alerts: list[AlertOut]
    zones: list[ZoneStatsOut]
    routing: RoutingStatusOut


class ConfirmOut(BaseModel):
    alert: AlertOut
    brigade: BrigadeOut | None
    shelter: ShelterOut


class BurstOut(BaseModel):
    sos: list[SOSOut]
    alerts: list[AlertOut]
