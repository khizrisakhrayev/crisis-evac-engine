"""Crisis domain logic (rerouting decisions, Red Alert detection). Thresholds come from config.py.

Stubs only for T0; implemented in later tasks.
"""


def needs_reroute(db, shelter, path_edge_ids) -> tuple[bool, str | None]:
    raise NotImplementedError


def evaluate_alerts(db) -> list:
    raise NotImplementedError
