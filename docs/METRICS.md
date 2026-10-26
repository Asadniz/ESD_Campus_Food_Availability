# Metric list

All metrics are defined in one place: `api/campus_api/observability/metrics.py`.
They are recorded in the middleware (HTTP ones) or in the route/job that causes them
(business ones). "Where recorded" below gives the file and function.

## Application metrics

| Metric | Type | Unit | Labels | Purpose | Where recorded |
|---|---|---|---|---|---|
| `campus_http_requests_total` | Counter | requests | `method`, `route`, `status` | Traffic and error volume per endpoint | `observability/middleware.py: dispatch()` |
| `campus_http_request_duration_seconds` | Histogram | seconds | `method`, `route` | Latency distribution, source of p95/p99 | `observability/middleware.py: dispatch()` |
| `campus_http_requests_in_progress` | Gauge | requests | none | Requests being handled right now (concurrency) | `observability/middleware.py: dispatch()` |
| `campus_staff_auth_failures_total` | Counter | events | none | Wrong/missing staff key attempts | `auth.py: require_staff()` |
| `campus_background_job_last_run_timestamp_seconds` | Gauge | unix seconds | `job` | Freshness of the background job (age = time() - this) | `jobs.py: run_once()` |

## Business metrics

| Metric | Type | Unit | Labels | Purpose | Where recorded |
|---|---|---|---|---|---|
| `campus_menu_views_total` | Counter | views | `eatery` | How often each eatery's menu is checked | `routers/eateries.py: get_menu()` |
| `campus_holds_placed_total` | Counter | holds | `eatery` | Demand for the hold feature (the actual business feature) | `routers/holds.py: create_hold()` |
| `campus_holds_rejected_total` | Counter | holds | `reason` (`sold_out`, `item_not_found`) | Lost demand and why | `routers/holds.py: _reject()` |
| `campus_holds_closed_total` | Counter | holds | `eatery`, `outcome` (`picked_up`, `cancelled`, `expired`) | What happens to holds in the end | `routers/holds.py: _close()`, `jobs.py: expire_stale_holds()` |
| `campus_availability_updates_total` | Counter | updates | `eatery`, `new_status` | How often staff change availability | `routers/items.py: set_availability()` |
| `campus_items_available` | Gauge | items | `eatery` | What a student could order right now | `observability/gauges.py: refresh_gauges()` |
| `campus_active_holds` | Gauge | holds | `eatery` | Holds currently waiting for pickup | `observability/gauges.py: refresh_gauges()` |
| `campus_hold_creation_seconds` | Summary | seconds | none | Average time to create a hold (Python summaries give no percentiles, so average only) | `routers/holds.py: create_hold()` |
| `campus_hold_replays_total` | Counter | replays | none | Hold requests answered from a stored `Idempotency-Key` instead of creating a hold (added in Assignment 2) | `hold_service.py: create_hold()` (HTTP and gRPC) |
| `campus_hold_pickup_delay_seconds` | Histogram | seconds | none | **Explored myself.** How long food actually waits before pickup, with p50/p95 via `histogram_quantile` | `routers/holds.py: pick_up()` |

## gRPC metrics (Assignment 2, Part C)

Recorded in the gRPC process (`campus-grpc`), which serves them on port 9102 for the Prometheus job
`campus-food-grpc`. The duration is measured on the server, around the handler.

| Metric | Type | Unit | Labels | Purpose | Where recorded |
|---|---|---|---|---|---|
| `campus_grpc_requests_total` | Counter | calls | `method` (`CreateHold`), `status` (gRPC status name) | Traffic and error volume per RPC method and status | `grpc_server.py: ObservabilityInterceptor` |
| `campus_grpc_request_duration_seconds` | Histogram | seconds | `method` | Server-side latency, source of p50/p95. Buckets 1 ms to 5 s | `grpc_server.py: ObservabilityInterceptor` |
| `campus_grpc_requests_in_progress` | Gauge | calls | `method` | Calls being handled right now (saturation) | `grpc_server.py: ObservabilityInterceptor` |

Full descriptions, queries and the audit that led to them are in `docs/A2_REPORT.md` (Part C).

## Host metrics (Node Exporter, scraped directly, no app code)

CPU, memory, disk and network for the machine `asad-laptop` (set as the `host` label in
`monitoring/prometheus/prometheus.yml` and as the Node Exporter container's hostname in
`docker-compose.yml`).

## Percentiles

`campus_http_request_duration_seconds` and `campus_hold_pickup_delay_seconds` are
Histograms, so p95/p99 come from `histogram_quantile()`, e.g.

```promql
histogram_quantile(0.95, sum by (route, le) (rate(campus_http_request_duration_seconds_bucket[5m])))
```

`campus_hold_creation_seconds` is a Summary. The Python client's Summary has no
percentile support, so it only reports `_sum` and `_count`; the average is

```promql
rate(campus_hold_creation_seconds_sum[5m]) / rate(campus_hold_creation_seconds_count[5m])
```

## Notes added in Assignment 2

- `campus_http_request_duration_seconds` now has buckets at 1 ms and 2.5 ms as well (12 buckets: 1 ms,
  2.5 ms, 5 ms, ... 5 s). Almost every request is faster than 5 ms, so with the old lowest bucket the
  percentiles were bucket artifacts. Numbers in the Assignment 1 report were measured with the old buckets.
- `campus_items_available` and `campus_active_holds` are recomputed from the database on every
  `/metrics` scrape, because a hold can be created by the gRPC process as well.
- The gRPC process exposes only the metrics it records. The HTTP-only metrics are unregistered at start-up
  (`grpc_server.py: expose_metrics()`).
