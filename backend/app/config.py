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

# Red Alert (codes only; UI translates).
ALERT_SEVERITY = "red"
ALERT_ACTION_CODE = "dispatch_brigade_and_open_shelter"
TEMP_SHELTER_CAPACITY = 500  # temporary assembly point when no reserve shelter is left
OVERVIEW_RECENT_CONFIRMED = 20
# Demo SOS burst scatter radius. <= 250 m keeps every pair < SOS_CLUSTER_RADIUS_M, so a burst always clusters.
DEMO_BURST_RADIUS_M = 240

# SOS priority: lower number = more urgent. Labels are codes, translated by the UI.
SOS_PRIORITY_CRITICAL = 1
SOS_PRIORITY_NORMAL = 2
SOS_PRIORITY_LABELS = {SOS_PRIORITY_CRITICAL: "critical", SOS_PRIORITY_NORMAL: "normal"}

# Routing / external Map & Routing API (simulated). All values are read at call time
# (always `config.X`, never `from config import X`) so the demo toggles and tests can change them.
EXTERNAL_MODE = "up"              # runtime: up | down_503 | slow  (POST /api/routing/external/{up|down|slow})
EXTERNAL_TIMEOUT_S = 5.0          # hard timeout per external call
EXTERNAL_SLOW_LATENCY_S = 6.0     # simulated response time in "slow" mode
BREAKER_FAILURE_THRESHOLD = 2     # consecutive failures (503/timeout) that open the circuit
BREAKER_COOLDOWN_S = 30           # open -> half_open after this many seconds
STATIC_MATRIX_DETOUR_FACTOR = 1.3 # haversine x factor when no road distance is known
MAX_EDGE_DETOUR_RATIO = 2.5      # seed drops a road whose real walking length exceeds this x straight distance
WALKING_SPEED_KMH = 5
