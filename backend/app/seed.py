"""Idempotent seed for Baku: 5 zones, 10 shelters, 6 brigades, 25-node / 45-edge road graph.

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
        Shelter(name=n, type=t, zone_id=zones[z].id, lat=la, lon=lo, capacity=cap, current=cur, is_open=True)
        for n, t, z, la, lo, cap, cur in SHELTERS
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

    pairs = [((z, a), (z, b)) for z in zones for a, b in INTRA_EDGES] + INTER_EDGES
    for a, b in pairs:
        na, nb = nodes[a], nodes[b]
        db.add(RoadEdge(from_node=na.id, to_node=nb.id,
                        length_m=round(haversine_m(na.lat, na.lon, nb.lat, nb.lon), 1), is_closed=False))
    db.commit()
    return True
