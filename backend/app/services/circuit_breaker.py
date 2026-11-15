"""Generic, thread-safe circuit breaker (closed -> open -> half_open -> closed/open).

Clock is injectable for tests. Threshold/cooldown default to callables so config changes apply at runtime.
"""
import threading
import time
from typing import Callable

CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"


class CircuitBreaker:
    def __init__(self, failure_threshold: int | Callable[[], int], cooldown_s: float | Callable[[], float],
                 clock: Callable[[], float] = time.monotonic,
                 on_state_change: Callable[[str, str], None] | None = None):
        self._threshold = failure_threshold
        self._cooldown = cooldown_s
        self.clock = clock
        self.on_state_change = on_state_change
        self._lock = threading.Lock()
        self._state = CLOSED
        self.consecutive_failures = 0
        self.opened_at: float | None = None
        self.last_error: str | None = None
        self._trial_in_flight = False

    # config may be given as a value or as a callable (read at call time)
    @property
    def failure_threshold(self) -> int:
        return self._threshold() if callable(self._threshold) else self._threshold

    @property
    def cooldown_s(self) -> float:
        return self._cooldown() if callable(self._cooldown) else self._cooldown

    def _cooldown_elapsed(self) -> bool:
        return self.opened_at is not None and self.clock() - self.opened_at >= self.cooldown_s

    def _set(self, new: str) -> tuple[str, str] | None:
        old, self._state = self._state, new
        return (old, new) if old != new else None

    def _notify(self, change):
        if change and self.on_state_change:
            try:
                self.on_state_change(*change)
            except Exception:  # a listener must never break routing
                pass

    @property
    def state(self) -> str:
        with self._lock:
            if self._state == OPEN and self._cooldown_elapsed():
                return HALF_OPEN  # next request will be the trial
            return self._state

    def allow_request(self) -> bool:
        """True if a call may go through. In half_open only one trial call at a time."""
        change = None
        with self._lock:
            if self._state == CLOSED:
                allowed = True
            elif self._state == OPEN:
                allowed = self._cooldown_elapsed()
                if allowed:
                    change = self._set(HALF_OPEN)
                    self._trial_in_flight = True
            else:  # HALF_OPEN
                allowed = not self._trial_in_flight
                self._trial_in_flight = True
        self._notify(change)
        return allowed

    def record_success(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.opened_at = None
            self._trial_in_flight = False
            change = self._set(CLOSED)
        self._notify(change)

    def record_failure(self, error: object = None) -> None:
        change = None
        with self._lock:
            self.consecutive_failures += 1
            self.last_error = str(error) if error is not None else "error"
            self._trial_in_flight = False
            if self._state == HALF_OPEN or self.consecutive_failures >= self.failure_threshold:
                self.opened_at = self.clock()
                change = self._set(OPEN)
        self._notify(change)

    def reset(self) -> None:
        with self._lock:
            self.consecutive_failures = 0
            self.opened_at = None
            self.last_error = None
            self._trial_in_flight = False
            change = self._set(CLOSED)
        self._notify(change)

    def seconds_until_retry(self) -> float:
        with self._lock:
            if self._state != OPEN or self.opened_at is None:
                return 0.0
            return max(0.0, self.cooldown_s - (self.clock() - self.opened_at))

    def snapshot(self) -> dict:
        state = self.state
        return dict(state=state, consecutive_failures=self.consecutive_failures, opened_at=self.opened_at,
                    last_error=self.last_error, seconds_until_retry=round(self.seconds_until_retry(), 1))
