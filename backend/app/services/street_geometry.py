"""Live street geometry for the walking legs (citizen -> road network, or a direct walk to a nearby shelter).

Calls the public OSM foot router (routing.openstreetmap.de, (c) OpenStreetMap contributors) with a 3 s timeout.
Never raises: any error/timeout -> None and the caller keeps its fallback (dotted straight leg / graph route).
Skipped when config.LIVE_STREET_GEOMETRY is False (tests) or when the simulated external routing mode is not
"up" (Drop 2 outage drill). After a failure the service is not retried for FAILURE_BACKOFF_S.
"""
import json
import logging
import threading
import time
import urllib.request
from collections import OrderedDict

from .. import config

log = logging.getLogger(__name__)
URL = "https://routing.openstreetmap.de/routed-foot/route/v1/foot/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson"
USER_AGENT = "crisis-evacuation-prototype/1.0"
TIMEOUT_S = 3.0
CACHE_MAX = 500
FAILURE_BACKOFF_S = 60

_cache: "OrderedDict[tuple, tuple[list, float]]" = OrderedDict()
_lock = threading.Lock()
_down_until = 0.0


def _key(*coords: float) -> tuple:
    return tuple(round(c, 4) for c in coords)


def walk_geometry(lat1: float, lon1: float, lat2: float, lon2: float) -> tuple[list[list[float]], float] | None:
    """Street walking path [[lat, lon], ...] and its length in metres, or None."""
    global _down_until
    if not config.LIVE_STREET_GEOMETRY or config.EXTERNAL_MODE != "up":
        return None
    key = _key(lat1, lon1, lat2, lon2)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
        if time.monotonic() < _down_until:
            return None
    try:
        req = urllib.request.Request(URL.format(lat1=lat1, lon1=lon1, lat2=lat2, lon2=lon2),
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            data = json.load(resp)
        route = data["routes"][0]
        path = [[lat, lon] for lon, lat in route["geometry"]["coordinates"]]
        if len(path) < 2:
            return None
        result = (path, float(route["distance"]))
    except Exception as e:  # network, timeout, bad JSON, no route: keep the fallback
        log.info("street geometry unavailable: %s", e)
        with _lock:
            _down_until = time.monotonic() + FAILURE_BACKOFF_S
        return None
    with _lock:
        _cache[key] = result
        while len(_cache) > CACHE_MAX:
            _cache.popitem(last=False)
    return result
