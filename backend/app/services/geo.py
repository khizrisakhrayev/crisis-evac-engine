import math
from typing import NamedTuple

EARTH_RADIUS_M = 6_371_000


class ZoneRef(NamedTuple):
    id: int
    name: str
    lat: float
    lon: float


# Zone cache (zones are static seed data). Filled by load_zones() at startup; call again if zones change.
_ZONES: list[ZoneRef] = []


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def load_zones(db) -> list[ZoneRef]:
    from ..models import Zone  # local import keeps geo free of DB deps for pure helpers

    _ZONES[:] = [ZoneRef(z.id, z.name, z.center_lat, z.center_lon) for z in db.query(Zone).all()]
    return _ZONES


def zones() -> list[ZoneRef]:
    return _ZONES


def zone_by_name(name: str) -> ZoneRef | None:
    return next((z for z in _ZONES if z.name.lower() == name.strip().lower()), None)


def zone_by_id(zone_id: int) -> ZoneRef | None:
    return next((z for z in _ZONES if z.id == zone_id), None)


def nearest_zone(lat: float, lon: float, zones: list[ZoneRef] | None = None) -> ZoneRef | None:
    """Zone whose centre is closest to the point (None if no zones loaded)."""
    candidates = _ZONES if zones is None else zones
    return min(candidates, key=lambda z: haversine_m(lat, lon, z.lat, z.lon), default=None)
