"""Every Prometheus metric the app exposes, defined in one place.

Reading guide (the same list appears as a table in docs/REPORT.md):
  Counter   only goes up            -> things that happened
  Gauge     goes up and down        -> the current state of something
  Histogram counts into buckets     -> latency distributions, percentiles via histogram_quantile()
  Summary   keeps sum and count     -> averages (the Python client has no percentiles)
"""
from prometheus_client import Counter, Gauge, Histogram, Summary, disable_created_metrics

# Skips the extra *_created series the client adds by default, so /metrics stays small and readable.
disable_created_metrics()

# ---------------------------------------------------------------- application metrics
HTTP_REQUESTS = Counter(
    "campus_http_requests_total",
    "HTTP requests handled, by method, route template and status code.",
    ["method", "route", "status"],
)
HTTP_DURATION = Histogram(
    "campus_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)
HTTP_IN_PROGRESS = Gauge(
    "campus_http_requests_in_progress",
    "Requests currently being processed.",
)
STAFF_AUTH_FAILURES = Counter(
    "campus_staff_auth_failures_total",
    "Staff endpoint calls rejected because of a missing or wrong key.",
)
JOB_LAST_RUN = Gauge(
    "campus_background_job_last_run_timestamp_seconds",
    "Unix time of the last completed background job run.",
    ["job"],
)

# ---------------------------------------------------------------- business metrics
MENU_VIEWS = Counter(
    "campus_menu_views_total",
    "Times a student opened an eatery menu.",
    ["eatery"],
)
HOLDS_PLACED = Counter(
    "campus_holds_placed_total",
    "Holds (food kept aside for later pickup) created.",
    ["eatery"],
)
HOLDS_REJECTED = Counter(
    "campus_holds_rejected_total",
    "Hold requests refused, by reason (sold_out, item_not_found).",
    ["reason"],
)
HOLDS_CLOSED = Counter(
    "campus_holds_closed_total",
    "Holds that ended, by outcome (picked_up, cancelled, expired).",
    ["eatery", "outcome"],
)
AVAILABILITY_UPDATES = Counter(
    "campus_availability_updates_total",
    "Staff changes to item availability.",
    ["eatery", "new_status"],
)
ITEMS_AVAILABLE = Gauge(
    "campus_items_available",
    "Menu items that can be ordered right now.",
    ["eatery"],
)
ACTIVE_HOLDS = Gauge(
    "campus_active_holds",
    "Holds waiting to be picked up.",
    ["eatery"],
)
HOLD_CREATION = Summary(
    "campus_hold_creation_seconds",
    "Time spent creating a hold (sum and count only, so use it for averages).",
)
# Metric I explored myself: how long food actually waits before the student comes back.
# Buckets: 10 min, 30 min, 1 h, 2 h, 3 h, 4 h, 6 h, 12 h.
HOLD_PICKUP_DELAY = Histogram(
    "campus_hold_pickup_delay_seconds",
    "Seconds between placing a hold and picking it up.",
    buckets=(600, 1800, 3600, 7200, 10800, 14400, 21600, 43200),
)
