"""Idempotent seed for Baku: 5 zones, 10 shelters + 4 closed reserves, 6 brigades, 25-node / ~45-edge road graph.

Shelter coordinates are approximate real landmarks. Road nodes, street geometry, real walking lengths and shelter
access paths come from data/road_geometry.json (OSM, generated once by backend/scripts/snap_roads.py).
"""
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import config
from .models import Brigade, RoadEdge, RoadNode, Shelter, Zone
from .services.geo import haversine_m

log = logging.getLogger(__name__)

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


GEOMETRY_FILE = Path(__file__).resolve().parent / "data" / "road_geometry.json"
SEED_REPORT: dict[str, list[str]] = {"dropped": [], "relinked": []}


def load_geometry() -> dict | None:
    """Precomputed OSM street geometry (backend/scripts/snap_roads.py); None -> straight synthetic graph."""
    try:
        return json.loads(GEOMETRY_FILE.read_text())
    except (OSError, ValueError):
        log.warning("road geometry file missing/invalid - using straight synthetic roads")
        return None


def seed_if_empty(db: Session) -> bool:
    """Seed the DB if it has no zones. Returns True if seeding happened."""
    if db.scalar(select(Zone.id).limit(1)) is not None:
        return False
    geo = load_geometry()

    zones = {name: Zone(name=name, center_lat=lat, center_lon=lon) for name, (lat, lon) in ZONES.items()}
    db.add_all(zones.values())
    db.flush()

    nodes: dict[str, RoadNode] = {}
    for zname, zone in zones.items():
        for key, (dlat, dlon) in NODE_OFFSETS.items():
            name = f"{zname} {key}"
            lat, lon = (geo["nodes"][name] if geo else (round(zone.center_lat + dlat, 6), round(zone.center_lon + dlon, 6)))
            nodes[name] = RoadNode(name=name, lat=lat, lon=lon, zone_id=zone.id)
    db.add_all(nodes.values())
    db.flush()

    def access_for(name):
        a = geo["shelters"].get(name) if geo else None
        if not a:
            return {}
        options = [dict(node_id=nodes[o["node"]].id, path=o["geometry"], m=o["distance_m"]) for o in a.get("options", [a])]
        return dict(access_node_id=nodes[a["node"]].id, access_path=a["geometry"], access_m=a["distance_m"],
                    access_options=options)

    db.add_all(
        Shelter(name=n, type=t, zone_id=zones[z].id, lat=la, lon=lo, capacity=cap, current=cur, is_open=True,
                is_accessible=n not in INACCESSIBLE_SHELTERS, **access_for(n))
        for n, t, z, la, lo, cap, cur in SHELTERS
    )
    db.add_all(
        Shelter(name=n, type=t, zone_id=zones[z].id, lat=la, lon=lo, capacity=cap, current=0, is_open=False,
                is_accessible=acc, is_reserve=True, **access_for(n))
        for n, t, z, la, lo, cap, acc in RESERVE_SHELTERS
    )
    db.add_all(Brigade(name=n, status="available", zone_id=zones[z].id) for n, z in BRIGADES)

    def accessible(z: str, link: tuple[str, str]) -> bool:
        return link not in INACCESSIBLE_RING and not (z in OLD_TOWN_ZONES and link in OLD_TOWN_EXTRA)

    pairs = [(f"{z} {a}", f"{z} {b}", accessible(z, (a, b))) for z in zones for a, b in INTRA_EDGES]
    pairs += [(f"{a[0]} {a[1]}", f"{b[0]} {b[1]}", True) for a, b in INTER_EDGES]
    edges: list[RoadEdge] = []
    SEED_REPORT["dropped"].clear()
    SEED_REPORT["relinked"].clear()
    for a, b, ok in pairs:
        na, nb = nodes[a], nodes[b]
        g = geo["edges"].get(f"{a}|{b}") if geo else None
        if g and g["distance_m"] > config.MAX_EDGE_DETOUR_RATIO * max(g["straight_m"], 1):
            SEED_REPORT["dropped"].append(f"{a}–{b} ({g['distance_m'] / g['straight_m']:.2f}x)")
            continue  # real walk is a big detour: not a sensible direct road
        edges.append(RoadEdge(from_node=na.id, to_node=nb.id, is_closed=False, is_accessible=ok,
                              length_m=g["distance_m"] if g else round(haversine_m(na.lat, na.lon, nb.lat, nb.lon), 1),
                              geometry=g["geometry"] if g else None))
    # Re-link: a node left without any accessible road gets its shortest remaining road marked accessible.
    for node in nodes.values():
        touching = [e for e in edges if node.id in (e.from_node, e.to_node)]
        if touching and not any(e.is_accessible for e in touching):
            best = min(touching, key=lambda e: e.length_m)
            best.is_accessible = True
            SEED_REPORT["relinked"].append(f"{node.name}: road {best.from_node}-{best.to_node} marked accessible")
    db.add_all(edges)
    db.commit()
    if SEED_REPORT["dropped"] or SEED_REPORT["relinked"]:
        log.warning("road seed adjustments: %s", SEED_REPORT)
    return True
