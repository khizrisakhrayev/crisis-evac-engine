from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Shelter
from ..schemas import NearestShelterOut, ShelterOut
from . import geo


def to_nearest_out(s: Shelter, lat: float, lon: float) -> NearestShelterOut:
    """Shelter as a 'nearest' item (distance from lat/lon, zone name, occupancy_pct, is_full)."""
    zone = geo.zone_by_id(s.zone_id)
    return NearestShelterOut(
        **ShelterOut.model_validate(s).model_dump(exclude={"occupancy_pct"}),
        distance_m=round(geo.haversine_m(lat, lon, s.lat, s.lon)),
        zone=zone.name if zone else "",
    )


def open_shelters_by_distance(db: Session, lat: float, lon: float) -> list[NearestShelterOut]:
    items = [to_nearest_out(s, lat, lon) for s in db.scalars(select(Shelter).where(Shelter.is_open.is_(True)))]
    items.sort(key=lambda i: i.distance_m)
    return items


def nearest_shelters(db: Session, lat: float | None, lon: float | None,
                     district: geo.ZoneRef | None, limit: int) -> list[NearestShelterOut]:
    """Open shelters sorted by distance from (lat, lon), or from the district centre if no point given.

    When a district is given, its shelters come first (each group sorted by distance).
    """
    if lat is None or lon is None:
        lat, lon = district.lat, district.lon
    items = open_shelters_by_distance(db, lat, lon)
    if district:
        items.sort(key=lambda i: i.zone_id != district.id)  # stable: keeps distance order within groups
    return items[:limit]


def set_occupancy(db: Session, shelter_id: int, current: int) -> tuple[Shelter, int] | None:
    """Clamp to 0..capacity. Returns (shelter, previous current) or None if missing."""
    shelter = db.get(Shelter, shelter_id)
    if shelter is None:
        return None
    previous = shelter.current
    shelter.current = max(0, min(current, shelter.capacity))
    db.commit()
    return shelter, previous
