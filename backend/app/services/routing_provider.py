"""Routing abstraction. External providers (e.g. OSRM) plug in here; the local road graph is the fallback."""
from typing import Protocol


class RoutingProvider(Protocol):
    def route(self, from_lat: float, from_lon: float, to_lat: float, to_lon: float) -> list[list[float]]:
        """Return a path as [[lat, lon], ...]."""
        ...


class LocalGraphProvider:
    """Shortest path over seeded RoadNode/RoadEdge graph, skipping closed edges. TODO (T-routing)."""

    def __init__(self, db):
        self.db = db

    def route(self, from_lat, from_lon, to_lat, to_lon):
        raise NotImplementedError


def get_provider(db) -> RoutingProvider:
    return LocalGraphProvider(db)
