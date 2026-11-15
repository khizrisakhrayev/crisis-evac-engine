from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Shelter
from ..schemas import NearestShelterOut, ShelterOut
from . import geo


def nearest_shelters(db: Session, lat: float | None, lon: float | None,
                     district: geo.ZoneRef | None, limit: int) -> list[NearestShelterOut]:
    """Open shelters sorted by distance from (lat, lon), or from the district centre if no point given.

    When a district is given, its shelters come first (each group sorted by distance).
    """
    if lat is None or lon is None:
        lat, lon = district.lat, district.lon
    items = []
    for s in db.scalars(select(Shelter).where(Shelter.is_open.is_(True))):
        zone = geo.zone_by_id(s.zone_id)
        items.append(NearestShelterOut(
            **ShelterOut.model_validate(s).model_dump(exclude={"occupancy_pct"}),
            distance_m=round(geo.haversine_m(lat, lon, s.lat, s.lon)),
            zone=zone.name if zone else "",
        ))
    in_other_zone = (lambda i: i.zone_id != district.id) if district else (lambda i: False)
    items.sort(key=lambda i: (in_other_zone(i), i.distance_m))
    return items[:limit]


def set_occupancy(db: Session, shelter_id: int, current: int) -> Shelter | None:
    shelter = db.get(Shelter, shelter_id)
    if shelter is None:
        return None
    shelter.current = max(0, min(current, shelter.capacity))
    db.commit()
    return shelter
