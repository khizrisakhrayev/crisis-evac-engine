"""Live evacuation simulation: virtual citizens walk their recommended street routes to shelters.

Everything goes through the normal services: routes from evacuation.recommend (so full shelters / closed
roads reroute), arrivals raise shelter occupancy through shelters.set_occupancy + crisis.on_shelter_updated
(so 90 % rerouting and 95 % Red Alerts fire by themselves). One tick = move everyone, one batched DB write
per shelter, reroute citizens whose target became full or closed, broadcast "sim_tick".
tick() is synchronous and deterministic given the seed, so tests drive it directly; the API runs it from
an asyncio task once per SIM_TICK_S.
"""
import math
import random
import threading
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..models import Shelter
from ..schemas import AlertOut, ShelterOut, occupancy_pct
from . import crisis, evacuation, geo
from . import shelters as shelter_svc
from .ws import publish, publish_alert

M_PER_DEG_LAT = 111_320
MOVING, ARRIVED, STUCK = 0, 1, 2


@dataclass
class Walker:
    id: int
    lat: float
    lon: float
    priority: bool
    path: list = field(default_factory=list)  # remaining [[lat, lon], ...]
    shelter_id: int | None = None
    status: int = MOVING


def _scatter(rng: random.Random, lat: float, lon: float, radius_m: float) -> tuple[float, float]:
    r, a = radius_m * math.sqrt(rng.random()), rng.random() * 2 * math.pi
    return (lat + r * math.cos(a) / M_PER_DEG_LAT,
            lon + r * math.sin(a) / (M_PER_DEG_LAT * math.cos(math.radians(lat))))


class Simulation:
    def __init__(self):
        self.lock = threading.Lock()
        self.running = False
        self.walkers: list[Walker] = []
        self.speed = 1.0
        self.counters = Counter()
        self.generation = 0  # bumps on every start/stop so an old runner task exits

    # --- lifecycle ------------------------------------------------------------------------------------
    def start(self, db: Session, citizens: int, zone_id: int | None, speed: float, seed: int | None = None) -> dict:
        rng = random.Random(seed)
        zones = [z for z in geo.zones() if zone_id is None or z.id == zone_id]
        if not zones:
            raise ValueError("unknown zone")
        with self.lock:
            self.generation += 1
            self.walkers, self.counters, self.speed = [], Counter(), speed
            for i in range(citizens):
                z = zones[i % len(zones)] if zone_id is None else zones[0]
                lat, lon = _scatter(rng, z.lat, z.lon, config.SIM_SPAWN_RADIUS_M)
                w = Walker(id=i + 1, lat=lat, lon=lon, priority=rng.random() < config.SIM_PRIORITY_SHARE)
                self._route(db, w)
                self.walkers.append(w)
            self.counters["spawned"] = citizens
            self.running = True
            return self.status()

    def stop(self) -> dict:
        with self.lock:
            self.generation += 1
            self.running = False
            return self.status()

    # --- routing / movement ---------------------------------------------------------------------------
    def _route(self, db: Session, w: Walker) -> None:
        try:
            r = evacuation.recommend(db, w.lat, w.lon, None, accessible_only=w.priority)
        except evacuation.NoShelterAvailable:
            r = {"shelter": None}
        if not r.get("shelter"):
            w.status, w.path, w.shelter_id = STUCK, [], None
            return
        w.shelter_id = r["shelter"].id
        w.path = [list(p) for p in (r.get("approach") or [])] + [list(p) for p in (r.get("path") or [])]
        if not w.path:
            w.path = [[r["shelter"].lat, r["shelter"].lon]]
        w.status = MOVING

    @staticmethod
    def _advance(w: Walker, meters: float) -> bool:
        """Move along the remaining path; True when the end (shelter) is reached."""
        while w.path and meters > 0:
            tlat, tlon = w.path[0]
            d = geo.haversine_m(w.lat, w.lon, tlat, tlon)
            if d <= meters:
                w.lat, w.lon = tlat, tlon
                meters -= d
                w.path.pop(0)
            else:
                f = meters / d
                w.lat += (tlat - w.lat) * f
                w.lon += (tlon - w.lon) * f
                meters = 0
        return not w.path

    def tick(self, db: Session, dt: float | None = None) -> dict:
        """One simulation step. Returns the sim_tick payload (also broadcast)."""
        dt = config.SIM_TICK_S if dt is None else dt
        with self.lock:
            if not self.running:
                return self.status()
            step_m = config.WALKING_SPEED_KMH * 1000 / 3600 * self.speed * dt
            arrivals: Counter = Counter()
            for w in self.walkers:
                if w.status == MOVING and self._advance(w, step_m):
                    w.status = ARRIVED
                    arrivals[w.shelter_id] += 1
            # batched occupancy write: one update per shelter, alerts through the normal crisis rule
            for sid, n in arrivals.items():
                s = db.get(Shelter, sid)
                if s is None:
                    continue
                shelter, previous = shelter_svc.set_occupancy(db, sid, s.current + n)
                self.counters["arrived"] += n
                publish("shelter_updated", ShelterOut.model_validate(shelter))
                publish_alert(crisis.on_shelter_updated(db, shelter, previous))
            # reroute everyone heading to a shelter that is now >= 90 % full or closed
            state = {s.id: s for s in db.scalars(select(Shelter))}
            for w in self.walkers:
                if w.status != MOVING:
                    continue
                s = state.get(w.shelter_id)
                if s is None or not s.is_open or occupancy_pct(s.current, s.capacity) >= config.REROUTE_OCCUPANCY_PCT:
                    old = w.shelter_id
                    self._route(db, w)
                    if w.shelter_id != old:
                        self.counters["rerouted"] += 1
            if all(w.status != MOVING for w in self.walkers):
                self.running = False
                self.generation += 1
            payload = self.status(positions=True)
        publish("sim_tick", payload)
        return payload

    def status(self, positions: bool = False) -> dict:
        moving = sum(1 for w in self.walkers if w.status == MOVING)
        out = dict(running=self.running, speed=self.speed, spawned=self.counters["spawned"], moving=moving,
                   arrived=self.counters["arrived"], rerouted=self.counters["rerouted"],
                   stuck=sum(1 for w in self.walkers if w.status == STUCK))
        if positions:
            out["positions"] = [[w.id, round(w.lat, 5), round(w.lon, 5), int(w.priority), w.status]
                                for w in self.walkers]
        return out


simulation = Simulation()
