"""Central configuration. All domain thresholds live here, never hard-coded elsewhere."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./crisis.db")

# Rerouting: citizen is rerouted when target shelter occupancy >= this percent.
REROUTE_OCCUPANCY_PCT = 90
# Red Alert: raised when a shelter occupancy is > this percent.
ALERT_OCCUPANCY_PCT = 95
# Red Alert: >= SOS_CLUSTER_COUNT distinct SOS within SOS_CLUSTER_RADIUS_M in SOS_CLUSTER_WINDOW_MIN.
SOS_CLUSTER_COUNT = 4
SOS_CLUSTER_RADIUS_M = 500
SOS_CLUSTER_WINDOW_MIN = 5
