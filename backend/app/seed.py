"""Idempotent seed for Baku: 5 zones, 10 shelters + 4 closed reserves, 6 brigades, 25-node / 45-edge road graph.

Coordinates are approximate (real landmarks, rounded); good enough for a demo map.
"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Brigade, RoadEdge, RoadNode, Shelter, Zone
from .services.geo import haversine_m

ZONES = {  # name: (center_lat, center_lon)
    "Nasimi": (40.3800, 49.8320),
    "Sabail": (40.3620, 49.8330),
    "Yasamal": (40.3850, 49.8050),
    "Narimanov": (40.4030, 49.8680),
    "Khatai": (40.3850, 49.9050),
}

SHELTERS = [  # name, type, zone, lat, lon, capacity, current
    ("Sahil Park (Seaside Boulevard)", "park", "Sabail", 40.3666, 49.8442, 3000, 450),
    ("Fountain Square", "park", "Sabail", 40.3707, 49.8372, 1500, 300),
    ("Samad Vurgun Park", "park", "Nasimi", 40.3790, 49.8470, 1200, 180),
    ("Nasimi Civil Defence Shelter", "shelter", "Nasimi", 40.3830, 49.8290, 400, 120),
    ("Yasamal Park", "park", "Yasamal", 40.3870, 49.8080, 1800, 270),
    ("Yasamal School Shelter", "shelter", "Yasamal", 40.3930, 49.8000, 350, 70),
    ("Tofiq Bahramov Republican Stadium", "stadium", "Narimanov", 40.3962, 49.8611, 10000, 1500),
    ("Ataturk Park", "park", "Narimanov", 40.4050, 49.8710, 2000, 400),
    ("Baku Olympic Stadium", "stadium", "Narimanov", 40.4300, 49.9197, 15000, 1200),
    ("Khatai District Shelter", "shelter", "Khatai", 40.3880, 49.9020, 500, 150),
]

# Basement / stair-access shelters: not wheelchair accessible (7 of 10 remain accessible).
INACCESSIBLE_SHELTERS = {"Nasimi Civil Defence Shelter", "Yasamal School Shelter", "Khatai District Shelter"}

# Reserve assembly points: closed until a confirmed Red Alert opens the nearest one.
RESERVE_SHELTERS = [  # name, type, zone, lat, lon, capacity, is_accessible
    ("Reserve: Baku Crystal Hall Grounds", "stadium", "Sabail", 40.3443, 49.8500, 8000, True),
    ("Reserve: Khatai Sports Complex", "stadium", "Khatai", 40.3800, 49.9110, 3000, True),
    ("Reserve: Narimanov Park", "park", "Narimanov", 40.4085, 49.8620, 2500, True),
    ("Reserve: Yasamal School No. 2 Gym", "shelter", "Yasamal", 40.3800, 49.8000, 600, False),
]

BRIGADES = [  # name, zone
    ("Fire Brigade 1", "Nasimi"),
    ("Medical Team 1", "Sabail"),
    ("Rescue Unit 1", "Yasamal"),
    ("Fire Brigade 2", "Narimanov"),
    ("Medical Team 2", "Khatai"),
    ("Rescue Unit 2", "Nasimi"),
]

# 5 nodes per zone: center + 4 compass points (~650 m away).
NODE_OFFSETS = {"C": (0, 0), "N": (0.006, 0), "E": (0, 0.008), "S": (-0.006, 0), "W": (0, -0.008)}
# Per zone: hub-and-spoke (4) + ring (4) = 8 edges -> 40 total.
INTRA_EDGES = [("C", "N"), ("C", "E"), ("C", "S"), ("C", "W"), ("N", "E"), ("E", "S"), ("S", "W"), ("W", "N")]
# Stairs / steep ring links (not wheelchair accessible): 2 per zone + 1 extra in the hilly old-town zones
# -> 13 inaccessible, 32 accessible (71%). Spokes and inter-zone links stay accessible, so the
# accessible sub-graph is connected and every zone reaches an accessible shelter.
INACCESSIBLE_RING = {("E", "S"), ("W", "N")}
OLD_TOWN_ZONES = {"Nasimi", "Sabail", "Yasamal"}
OLD_TOWN_EXTRA = {("S", "W")}
INTER_EDGES = [  # 5 links between neighbouring zones -> 45 total
    (("Sabail", "N"), ("Nasimi", "S")),
    (("Nasimi", "W"), ("Yasamal", "E")),
    (("Nasimi", "E"), ("Narimanov", "W")),
    (("Narimanov", "E"), ("Khatai", "N")),
    (("Sabail", "E"), ("Khatai", "W")),
]


def seed_if_empty(db: Session) -> bool:
    """Seed the DB if it has no zones. Returns True if seeding happened."""
    if db.scalar(select(Zone.id).limit(1)) is not None:
        return False

    zones = {name: Zone(name=name, center_lat=lat, center_lon=lon) for name, (lat, lon) in ZONES.items()}
    db.add_all(zones.values())
    db.flush()

    db.add_all(
        Shelter(name=n, type=t, zone_id=zones[z].id, lat=la, lon=lo, capacity=cap, current=cur, is_open=True,
                is_accessible=n not in INACCESSIBLE_SHELTERS)
        for n, t, z, la, lo, cap, cur in SHELTERS
    )
    db.add_all(
        Shelter(name=n, type=t, zone_id=zones[z].id, lat=la, lon=lo, capacity=cap, current=0, is_open=False,
                is_accessible=acc, is_reserve=True)
        for n, t, z, la, lo, cap, acc in RESERVE_SHELTERS
    )
    db.add_all(Brigade(name=n, status="available", zone_id=zones[z].id) for n, z in BRIGADES)

    nodes: dict[tuple[str, str], RoadNode] = {}
    for zname, zone in zones.items():
        for key, (dlat, dlon) in NODE_OFFSETS.items():
            nodes[(zname, key)] = RoadNode(
                name=f"{zname} {key}", lat=round(zone.center_lat + dlat, 6),
                lon=round(zone.center_lon + dlon, 6), zone_id=zone.id,
            )
    db.add_all(nodes.values())
    db.flush()

    def accessible(z: str, link: tuple[str, str]) -> bool:
        return link not in INACCESSIBLE_RING and not (z in OLD_TOWN_ZONES and link in OLD_TOWN_EXTRA)

    pairs = [((z, a), (z, b), accessible(z, (a, b))) for z in zones for a, b in INTRA_EDGES]
    pairs += [(a, b, True) for a, b in INTER_EDGES]
    for a, b, ok in pairs:
        na, nb = nodes[a], nodes[b]
        db.add(RoadEdge(from_node=na.id, to_node=nb.id, is_closed=False, is_accessible=ok,
                        length_m=round(haversine_m(na.lat, na.lon, nb.lat, nb.lon), 1)))
    db.commit()
    return True
