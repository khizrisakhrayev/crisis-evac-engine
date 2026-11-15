"""SOS flood / spam filtering: duplicate payloads, idempotency keys, many citizen ids from one IP.

All state is in memory (single-process prototype) and guarded by one lock; counters feed the
dispatcher's "Flood protection" KPI. reset() is called by the demo reset.
"""
import threading
import time
from collections import defaultdict

from .. import config


class SpamFilter:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self._lock = threading.Lock()
        self._recent: dict[tuple, tuple[float, object]] = {}   # (ip, payload) -> (ts, SOSOut)
        self._idem: dict[str, tuple[float, object]] = {}       # idempotency key -> (ts, SOSOut)
        self._citizens: dict[str, dict[str, float]] = defaultdict(dict)  # ip -> citizen_id -> last ts
        self.counters = {"rate_limited": 0, "duplicates": 0, "suspected": 0}

    @staticmethod
    def payload_key(ip: str, body, role: str = "") -> tuple:
        return (ip, role, body.citizen_id, round(body.lat, 6), round(body.lon, 6), body.hazard_type)

    def _prune(self, now: float) -> None:
        if len(self._recent) > 5000:
            self._recent = {k: v for k, v in self._recent.items() if now - v[0] < config.SOS_DUPLICATE_WINDOW_S}
        if len(self._idem) > 5000:
            self._idem = {k: v for k, v in self._idem.items() if now - v[0] < config.IDEMPOTENCY_TTL_S}

    def existing(self, ip: str, body, idem_key: str | None, role: str = ""):
        """The SOS (as returned before) to replay instead of creating a record: idempotency key or duplicate payload."""
        now = self.clock()
        with self._lock:
            if idem_key:
                hit = self._idem.get(idem_key)
                if hit and now - hit[0] < config.IDEMPOTENCY_TTL_S:
                    self.counters["duplicates"] += 1
                    return hit[1]
            hit = self._recent.get(self.payload_key(ip, body, role))
            if hit and now - hit[0] < config.SOS_DUPLICATE_WINDOW_S:
                self.counters["duplicates"] += 1
                return hit[1]
        return None

    def is_suspected(self, ip: str, citizen_id: str) -> bool:
        """Track citizen ids per IP; True once more than SPAM_DISTINCT_CITIZENS_PER_IP were seen in the window."""
        now = self.clock()
        with self._lock:
            seen = self._citizens[ip]
            for cid in [c for c, ts in seen.items() if now - ts >= config.SPAM_WINDOW_S]:
                del seen[cid]
            seen[citizen_id] = now
            suspected = len(seen) > config.SPAM_DISTINCT_CITIZENS_PER_IP
            if suspected:
                self.counters["suspected"] += 1
            return suspected

    def remember(self, ip: str, body, idem_key: str | None, sos_out, role: str = "") -> None:
        now = self.clock()
        with self._lock:
            self._prune(now)
            self._recent[self.payload_key(ip, body, role)] = (now, sos_out)
            if idem_key:
                self._idem[idem_key] = (now, sos_out)

    def forget(self, sos_id: int) -> None:
        """Drop cached replays of an SOS that changed (e.g. marked safe): the next SOS opens a fresh record."""
        with self._lock:
            self._recent = {k: v for k, v in self._recent.items() if v[1].id != sos_id}
            self._idem = {k: v for k, v in self._idem.items() if v[1].id != sos_id}

    def count(self, name: str) -> None:
        with self._lock:
            self.counters[name] += 1

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self.counters)

    def reset(self) -> None:
        with self._lock:
            self._recent.clear()
            self._idem.clear()
            self._citizens.clear()
            self.counters = {k: 0 for k in self.counters}


spam_filter = SpamFilter()
