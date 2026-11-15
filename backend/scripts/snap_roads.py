"""One-off: snap the seeded road graph onto real Baku streets with the public OSRM foot service.

Run manually (never at app startup):  python -m backend.scripts.snap_roads
Writes backend/app/data/road_geometry.json, which is committed; the app never calls the service at runtime.
Data (c) OpenStreetMap contributors, routed by routing.openstreetmap.de (FOSSGIS).
"""
import json
import math
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from backend.app.seed import (INTER_EDGES, INTRA_EDGES, NODE_OFFSETS, RESERVE_SHELTERS, SHELTERS, ZONES)
from backend.app.services.geo import haversine_m

BASE = "https://routing.openstreetmap.de/routed-foot"
UA = "evacuation-prototype/0.1 (hackathon demo)"
OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "road_geometry.json"
PAUSE_S = 0.25
MAX_SEG_M = 100  # densify so no stored segment is longer than this


def fetch(path: str) -> dict:
    url = f"{BASE}{path}"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read())
            if data.get("code") != "Ok":
                raise RuntimeError(f"OSRM {data.get('code')}: {data.get('message')}")
            time.sleep(PAUSE_S)
            return data
        except Exception as e:  # network error or bad answer: retry with backoff
            if attempt == 2:
                raise RuntimeError(f"request failed after 3 attempts: {url}: {e}") from e
            time.sleep(1.5 * (attempt + 1))


def nearest(lat: float, lon: float) -> list[float]:
    lon_s, lat_s = fetch(f"/nearest/v1/foot/{lon:.6f},{lat:.6f}")["waypoints"][0]["location"]
    return [round(lat_s, 6), round(lon_s, 6)]


def route(a: list[float], b: list[float]) -> tuple[list[list[float]], float]:
    data = fetch(f"/route/v1/foot/{a[1]:.6f},{a[0]:.6f};{b[1]:.6f},{b[0]:.6f}?overview=full&geometries=geojson")
    r = data["routes"][0]
    coords = [[round(lat, 6), round(lon, 6)] for lon, lat in r["geometry"]["coordinates"]]
    return coords, float(r["distance"])


def densify(points: list[list[float]]) -> list[list[float]]:
    out = [points[0]]
    for p, q in zip(points, points[1:]):
        n = max(1, math.ceil(haversine_m(*p, *q) / MAX_SEG_M))
        for i in range(1, n + 1):
            out.append([round(p[0] + (q[0] - p[0]) * i / n, 6), round(p[1] + (q[1] - p[1]) * i / n, 6)])
    return out


def pinned(geometry: list[list[float]], start: list[float], end: list[float]) -> list[list[float]]:
    """Force exact node endpoints so consecutive edges join without gaps."""
    pts = [start] + geometry[1:-1] + [end] if len(geometry) >= 2 else [start, end]
    return densify(pts)


def main() -> int:
    if "--shelters-only" in sys.argv and OUT.exists():  # reuse snapped nodes/edges, recompute shelter access
        old = json.loads(OUT.read_text())
        return write(old["nodes"], old["edges"], route_shelters(old["nodes"]))
    nodes: dict[str, list[float]] = {}
    print("snapping nodes ...")
    for zname, (clat, clon) in ZONES.items():
        for key, (dlat, dlon) in NODE_OFFSETS.items():
            nodes[f"{zname} {key}"] = nearest(round(clat + dlat, 6), round(clon + dlon, 6))

    pairs = [(f"{z} {a}", f"{z} {b}") for z in ZONES for a, b in INTRA_EDGES]
    pairs += [(f"{a[0]} {a[1]}", f"{b[0]} {b[1]}") for a, b in INTER_EDGES]
    edges = {}
    print(f"routing {len(pairs)} edges ...")
    for a, b in pairs:
        geom, dist = route(nodes[a], nodes[b])
        straight = haversine_m(*nodes[a], *nodes[b])
        edges[f"{a}|{b}"] = {"distance_m": round(dist, 1), "straight_m": round(straight, 1),
                             "geometry": pinned(geom, nodes[a], nodes[b])}

    return write(nodes, edges, route_shelters(nodes))


def route_shelters(nodes: dict) -> dict:
    shelters = {}
    all_shelters = [(s[0], s[3], s[4]) for s in SHELTERS] + [(s[0], s[3], s[4]) for s in RESERVE_SHELTERS]
    print(f"routing {len(all_shelters)} shelters x 3 access paths ...")
    for name, lat, lon in all_shelters:
        # Access paths from the 3 nearest nodes; routing picks the one with the cheapest total walk at runtime,
        # so a route never overshoots the shelter to reach a single fixed entry node.
        options = []
        for node in sorted(nodes, key=lambda k: haversine_m(lat, lon, *nodes[k]))[:3]:
            geom, dist = route(nodes[node], [lat, lon])
            tail = haversine_m(*geom[-1], lat, lon)
            if tail > 5:  # entrance is off the street network (inside a park/stadium): walk the last bit
                geom = geom + [[lat, lon]]
                dist += tail
            options.append({"node": node, "distance_m": round(dist, 1), "geometry": pinned(geom, nodes[node], [lat, lon])})
        options.sort(key=lambda o: o["distance_m"])
        shelters[name] = {**options[0], "options": options}

    return shelters


def write(nodes, edges, shelters) -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": BASE, "profile": "foot",
        "attribution": "Map data (c) OpenStreetMap contributors (ODbL); routing by routing.openstreetmap.de",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "nodes": nodes, "edges": edges, "shelters": shelters,
    }, ensure_ascii=False, indent=1))
    ratio = sorted(((e["distance_m"] / max(e["straight_m"], 1), k) for k, e in edges.items()), reverse=True)
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB)")
    print("highest real/straight ratios:", [(k, round(r, 2)) for r, k in ratio[:6]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
