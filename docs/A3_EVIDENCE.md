# Assignment 3: evidence

Generated 2026-11-22 by `experiments/a3/make_evidence.py` from the result files in `experiments/a3/results/`. Workload for every run: fixed rate, open loop, one HTTP operation (`GET /eateries/1/menu`) and one unary gRPC operation (`CreateHold` replay of one idempotency key) through Envoy. Client p95 is over successful requests. Shares below are what the client saw (replica header); section 3 cross-checks them against Prometheus and Envoy's access log.

## 1. All runs

| Run | Interface | Target / actual send rps | Sent | OK | Failed | Error rate | Client p50 / p95 / p99 ms | A/B/C share % (client) | Max send lag ms |
|---|---|---|---|---|---|---|---|---|---|
| b-baseline-http | http | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.2 / 6.8 / 10.2 | 100.0/0.0/0.0 | 12.6 |
| b-baseline-grpc | grpc | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.7 / 9.1 / 14.8 | 100.0/0.0/0.0 | 2.2 |
| c-rr-http | http | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.5 / 6.7 / 10.5 | 33.3/33.3/33.3 | 1.4 |
| c-rr-grpc | grpc | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.3 / 6.5 / 8.9 | 33.3/33.3/33.3 | 1.4 |
| d1-weighted-http | http | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.4 / 5.8 / 7.2 | 50.0/25.0/25.0 | 1.3 |
| d1-weighted-grpc | grpc | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.0 / 5.0 / 6.2 | 50.0/25.0/25.0 | 1.1 |
| d2-rr-delay-http | http | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.4 / 205.1 / 205.7 | 33.3/33.4/33.3 | 1.4 |
| d2-rr-delay-grpc | grpc | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.5 / 205.2 / 206.0 | 33.3/33.3/33.3 | 1.5 |
| d2-lr-delay-http | http | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.6 / 205.1 / 206.8 | 43.6/13.2/43.2 | 4.6 |
| d2-lr-delay-grpc | grpc | 50 / 50.0 | 3000 | 3000 | 0 | 0.00% | 4.3 / 204.9 / 205.8 | 43.1/14.2/42.7 | 1.4 |
| d3-fail-http | http | 50 / 50.0 | 4500 | 4419 | 81 | 1.80% | 4.3 / 6.1 / 7.9 | 39.1/21.7/39.1 | 1.8 |
| d3-fail-grpc | grpc | 50 / 50.0 | 4500 | 4426 | 74 | 1.64% | 4.6 / 9.8 / 28.9 | 39.9/20.1/39.9 | 3.6 |

## 2. Per run: numbers, chart and Grafana view

### Part B: baseline, A only (B and C running, not destinations)

**b-baseline-http** (http): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'200': 3000}, client p95 6.8 ms, replicas seen by client {'A': 3000}.

![b-baseline-http chart](img/a3/b-baseline-http.png)

![b-baseline-http Grafana](img/a3/b-baseline-http-grafana.png)

**b-baseline-grpc** (grpc): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'OK': 3000}, client p95 9.1 ms, replicas seen by client {'A': 3000}.

![b-baseline-grpc chart](img/a3/b-baseline-grpc.png)

![b-baseline-grpc Grafana](img/a3/b-baseline-grpc-grafana.png)

### Part C: equal-weight round robin over A, B, C

**c-rr-http** (http): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'200': 3000}, client p95 6.7 ms, replicas seen by client {'A': 1000, 'B': 1000, 'C': 1000}.

![c-rr-http chart](img/a3/c-rr-http.png)

![c-rr-http Grafana](img/a3/c-rr-http-grafana.png)

**c-rr-grpc** (grpc): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'OK': 3000}, client p95 6.5 ms, replicas seen by client {'A': 1000, 'C': 1000, 'B': 1000}.

![c-rr-grpc chart](img/a3/c-rr-grpc.png)

![c-rr-grpc Grafana](img/a3/c-rr-grpc-grafana.png)

### D1: weighted round robin, A:B:C = 2:1:1

**d1-weighted-http** (http): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'200': 3000}, client p95 5.8 ms, replicas seen by client {'B': 750, 'C': 750, 'A': 1500}.

![d1-weighted-http chart](img/a3/d1-weighted-http.png)

![d1-weighted-http Grafana](img/a3/d1-weighted-http-grafana.png)

**d1-weighted-grpc** (grpc): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'OK': 3000}, client p95 5.0 ms, replicas seen by client {'A': 1500, 'B': 750, 'C': 750}.

![d1-weighted-grpc chart](img/a3/d1-weighted-grpc.png)

![d1-weighted-grpc Grafana](img/a3/d1-weighted-grpc-grafana.png)

### D2: round robin, fixed delay on B

**d2-rr-delay-http** (http): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'200': 3000}, client p95 205.1 ms, replicas seen by client {'A': 1000, 'C': 999, 'B': 1001}.

![d2-rr-delay-http chart](img/a3/d2-rr-delay-http.png)

![d2-rr-delay-http Grafana](img/a3/d2-rr-delay-http-grafana.png)

**d2-rr-delay-grpc** (grpc): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'OK': 3000}, client p95 205.2 ms, replicas seen by client {'C': 1000, 'A': 1000, 'B': 1000}.

![d2-rr-delay-grpc chart](img/a3/d2-rr-delay-grpc.png)

![d2-rr-delay-grpc Grafana](img/a3/d2-rr-delay-grpc-grafana.png)

### D2: least request, same delay on B

**d2-lr-delay-http** (http): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'200': 3000}, client p95 205.1 ms, replicas seen by client {'C': 1296, 'A': 1308, 'B': 396}.

![d2-lr-delay-http chart](img/a3/d2-lr-delay-http.png)

![d2-lr-delay-http Grafana](img/a3/d2-lr-delay-http-grafana.png)

**d2-lr-delay-grpc** (grpc): target 50 rps for 60 s, sent 3000, ok 3000, failed 0 {'OK': 3000}, client p95 204.9 ms, replicas seen by client {'C': 1281, 'A': 1292, 'B': 427}.

![d2-lr-delay-grpc chart](img/a3/d2-lr-delay-grpc.png)

![d2-lr-delay-grpc Grafana](img/a3/d2-lr-delay-grpc-grafana.png)

### D3: round robin with active health checks, B stopped then restarted

**d3-fail-http** (http): target 50 rps for 90 s, sent 4500, ok 4419, failed 81 {'200': 4419, '503': 81}, client p95 6.1 ms, replicas seen by client {'A': 1729, 'B': 960, 'C': 1730, '?': 81}.
B stopped at +19.8 s and started again at +49.8 s (run clock); first failed request at +20.0 s, last at +24.8 s.

![d3-fail-http chart](img/a3/d3-fail-http.png)

![d3-fail-http Grafana](img/a3/d3-fail-http-grafana.png)

**d3-fail-grpc** (grpc): target 50 rps for 90 s, sent 4500, ok 4426, failed 74 {'OK': 4426, 'UNAVAILABLE': 74}, client p95 9.8 ms, replicas seen by client {'B': 890, 'A': 1768, 'C': 1768, '?': 74}.
B stopped at +19.0 s and started again at +49.0 s (run clock); first failed request at +19.1 s, last at +23.5 s.

![d3-fail-grpc chart](img/a3/d3-fail-grpc.png)

![d3-fail-grpc Grafana](img/a3/d3-fail-grpc-grafana.png)

## 3. Share cross-check: client, Prometheus, Envoy access log, plus proxy-side latency

```text
== b-baseline-http (http) ==
client  counts {'A': 3000} shares % {'A': 100.0}
prom    counts {'A': 3000.0} shares % {'A': 100.0}
envoy   counts {'A': 3000} shares % {'A': 100.0}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 3.0, 'p95': 4.0, 'p99': 6.8, 'mean': 2.4} mean by replica {'A': 2.4}

== b-baseline-grpc (grpc) ==
client  counts {'A': 3000} shares % {'A': 100.0}
prom    counts {'A': 3001.0} shares % {'A': 100.0}
envoy   counts {'A': 3001} shares % {'A': 100.0}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 4.0, 'p95': 5.1, 'p99': 9.6, 'mean': 2.7} mean by replica {'A': 2.7}

== c-rr-http (http) ==
client  counts {'A': 1000, 'B': 1000, 'C': 1000} shares % {'A': 33.3, 'B': 33.3, 'C': 33.3}
prom    counts {'A': 1000.0, 'C': 1000.0, 'B': 1000.0} shares % {'A': 33.3, 'B': 33.3, 'C': 33.3}
envoy   counts {'A': 1000, 'B': 1000, 'C': 1000} shares % {'A': 33.3, 'B': 33.3, 'C': 33.3}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 3.0, 'p95': 4.0, 'p99': 7.2, 'mean': 2.5} mean by replica {'A': 2.5, 'B': 2.5, 'C': 2.5}

== c-rr-grpc (grpc) ==
client  counts {'A': 1000, 'C': 1000, 'B': 1000} shares % {'A': 33.3, 'B': 33.3, 'C': 33.3}
prom    counts {'A': 1000.0, 'C': 1000.0, 'B': 1001.0} shares % {'A': 33.3, 'B': 33.4, 'C': 33.3}
envoy   counts {'B': 1001, 'A': 1000, 'C': 1000} shares % {'A': 33.3, 'B': 33.4, 'C': 33.3}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 3.0, 'p95': 3.2, 'p99': 5.3, 'mean': 2.3} mean by replica {'B': 2.3, 'A': 2.3, 'C': 2.3}

== d1-weighted-http (http) ==
client  counts {'B': 750, 'C': 750, 'A': 1500} shares % {'A': 50.0, 'B': 25.0, 'C': 25.0}
prom    counts {'B': 750.0, 'A': 1500.0, 'C': 750.0} shares % {'A': 50.0, 'B': 25.0, 'C': 25.0}
envoy   counts {'A': 1500, 'B': 750, 'C': 750} shares % {'A': 50.0, 'B': 25.0, 'C': 25.0}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 3.0, 'p95': 3.0, 'p99': 4.5, 'mean': 2.3} mean by replica {'A': 2.3, 'B': 2.4, 'C': 2.3}

== d1-weighted-grpc (grpc) ==
client  counts {'A': 1500, 'B': 750, 'C': 750} shares % {'A': 50.0, 'B': 25.0, 'C': 25.0}
prom    counts {'B': 750.0, 'A': 1500.0, 'C': 751.0} shares % {'A': 50.0, 'B': 25.0, 'C': 25.0}
envoy   counts {'A': 1500, 'C': 751, 'B': 750} shares % {'A': 50.0, 'B': 25.0, 'C': 25.0}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 2.0, 'p95': 2.0, 'p99': 3.0, 'mean': 2.1} mean by replica {'A': 2.0, 'C': 2.1, 'B': 2.0}

== d2-rr-delay-http (http) ==
client  counts {'A': 1000, 'C': 999, 'B': 1001} shares % {'A': 33.3, 'B': 33.4, 'C': 33.3}
prom    counts {'B': 1001.0, 'A': 1000.0, 'C': 999.0} shares % {'A': 33.3, 'B': 33.4, 'C': 33.3}
envoy   counts {'B': 1001, 'A': 1000, 'C': 999} shares % {'A': 33.3, 'B': 33.4, 'C': 33.3}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 203.0, 'p95': 203.0, 'p99': 204.0, 'mean': 69.1} mean by replica {'B': 202.7, 'A': 2.1, 'C': 2.1}

== d2-rr-delay-grpc (grpc) ==
client  counts {'C': 1000, 'A': 1000, 'B': 1000} shares % {'A': 33.3, 'B': 33.3, 'C': 33.3}
prom    counts {'B': 1001.0, 'A': 1000.0, 'C': 1000.0} shares % {'A': 33.3, 'B': 33.4, 'C': 33.3}
envoy   counts {'B': 1001, 'A': 1000, 'C': 1000} shares % {'A': 33.3, 'B': 33.4, 'C': 33.3}
envoy   latency ms (proxy side) {'p50': 2.1, 'p90': 202.7, 'p95': 203.0, 'p99': 204.0, 'mean': 68.9} mean by replica {'B': 202.4, 'A': 2.1, 'C': 2.2}

== d2-lr-delay-http (http) ==
client  counts {'C': 1296, 'A': 1308, 'B': 396} shares % {'A': 43.6, 'B': 13.2, 'C': 43.2}
prom    counts {'B': 396.0, 'A': 1308.0, 'C': 1296.0} shares % {'A': 43.6, 'B': 13.2, 'C': 43.2}
envoy   counts {'A': 1308, 'C': 1296, 'B': 396} shares % {'A': 43.6, 'B': 13.2, 'C': 43.2}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 203.0, 'p95': 203.0, 'p99': 204.4, 'mean': 29.0} mean by replica {'A': 2.5, 'C': 2.4, 'B': 203.3}

== d2-lr-delay-grpc (grpc) ==
client  counts {'C': 1281, 'A': 1292, 'B': 427} shares % {'A': 43.1, 'B': 14.2, 'C': 42.7}
prom    counts {'B': 427.0, 'A': 1293.0, 'C': 1281.0} shares % {'A': 43.1, 'B': 14.2, 'C': 42.7}
envoy   counts {'A': 1293, 'C': 1281, 'B': 427} shares % {'A': 43.1, 'B': 14.2, 'C': 42.7}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 201.9, 'p95': 203.0, 'p99': 203.7, 'mean': 30.7} mean by replica {'A': 2.2, 'C': 2.2, 'B': 202.5}

== d3-fail-http (http) ==
client  counts {'A': 1729, 'B': 960, 'C': 1730, '?': 81} shares % {'?': 1.8, 'A': 38.4, 'B': 21.3, 'C': 38.4}
prom    counts {'B': 627.0, 'A': 1729.0, 'C': 1730.0} shares % {'A': 42.3, 'B': 15.3, 'C': 42.3}
envoy   counts {'C': 1730, 'A': 1729, 'B': 960, '(none: no replica answered)': 81} shares % {'(none: no replica answered)': 1.8, 'A': 38.4, 'B': 21.3, 'C': 38.4}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 3.0, 'p95': 4.0, 'p99': 408.6, 'mean': 11.9} mean by replica {'C': 2.4, 'A': 2.4, 'B': 2.4, '(none)': 528.4}

== d3-fail-grpc (grpc) ==
client  counts {'B': 890, 'A': 1768, 'C': 1768, '?': 74} shares % {'?': 1.6, 'A': 39.3, 'B': 19.8, 'C': 39.3}
prom    counts {'B': 572.0, 'A': 1769.0, 'C': 1768.0} shares % {'A': 43.1, 'B': 13.9, 'C': 43.0}
envoy   counts {'A': 1769, 'C': 1768, 'B': 890, '(none: no replica answered)': 74} shares % {'(none: no replica answered)': 1.6, 'A': 39.3, 'B': 19.8, 'C': 39.3}
envoy   latency ms (proxy side) {'p50': 2.0, 'p90': 3.9, 'p95': 5.3, 'p99': 371.1, 'mean': 10.6} mean by replica {'A': 2.6, 'C': 2.6, 'B': 2.6, '(none)': 491.6}

| Run / interface | Target / actual rps | A/B/C shares % (Prometheus) | Client p95 ms | Envoy mean ms | Error rate |
|---|---|---|---|---|---|
| b-baseline-http / http | 50 / 50.0 ok | 100.0/0/0 | 6.8 | 2.4 | 0.0% |
| b-baseline-grpc / grpc | 50 / 50.0 ok | 100.0/0/0 | 9.1 | 2.7 | 0.0% |
| c-rr-http / http | 50 / 50.0 ok | 33.3/33.3/33.3 | 6.7 | 2.5 | 0.0% |
| c-rr-grpc / grpc | 50 / 50.0 ok | 33.3/33.4/33.3 | 6.5 | 2.3 | 0.0% |
| d1-weighted-http / http | 50 / 50.0 ok | 50.0/25.0/25.0 | 5.8 | 2.3 | 0.0% |
| d1-weighted-grpc / grpc | 50 / 50.0 ok | 50.0/25.0/25.0 | 5.0 | 2.1 | 0.0% |
| d2-rr-delay-http / http | 50 / 50.0 ok | 33.3/33.4/33.3 | 205.1 | 69.1 | 0.0% |
| d2-rr-delay-grpc / grpc | 50 / 50.0 ok | 33.3/33.4/33.3 | 205.2 | 68.9 | 0.0% |
| d2-lr-delay-http / http | 50 / 50.0 ok | 43.6/13.2/43.2 | 205.1 | 29.0 | 0.0% |
| d2-lr-delay-grpc / grpc | 50 / 50.0 ok | 43.1/14.2/42.7 | 204.9 | 30.7 | 0.0% |
| d3-fail-http / http | 50 / 49.1 ok | 42.3/15.3/42.3 | 6.1 | 11.9 | 1.8% |
| d3-fail-grpc / grpc | 50 / 49.2 ok | 43.1/13.9/43.0 | 9.8 | 10.6 | 1.6% |
```

## 4. Failure timeline (removal and recovery of replica B)

```text
== d3-fail-grpc ==
B stopped at +19.0s, started again at +49.0s (run clock)
failed requests in access log: 74
detection  (stop -> first failure):   0.1 s
removal    (stop -> last failure) :   4.5 s
recovery   (start -> first answer from B):   6.7 s
settings: interval 2s, timeout 1s, unhealthy 2, healthy 2
expected removal about 2 to 5 s after the stop (wait for next check + 1 more interval(s) + timeout)
expected recovery = app start-up time + about 1 to 2 intervals (2 to 4 s)
back-of-envelope failures: rate x 1/3 x removal = 50 x 1/3 x removal time

== d3-fail-http ==
B stopped at +19.8s, started again at +49.8s (run clock)
failed requests in access log: 81
detection  (stop -> first failure):   0.2 s
removal    (stop -> last failure) :   5.0 s
recovery   (start -> first answer from B):   2.6 s
settings: interval 2s, timeout 1s, unhealthy 2, healthy 2
expected removal about 2 to 5 s after the stop (wait for next check + 1 more interval(s) + timeout)
expected recovery = app start-up time + about 1 to 2 intervals (2 to 4 s)
back-of-envelope failures: rate x 1/3 x removal = 50 x 1/3 x removal time
```

## 5. Shared state: idempotency (shared) and rate limit (per replica)

```text
1. same Idempotency-Key x9
   answered by replicas ['C', 'B', 'B', 'A', 'A', 'C', 'B', 'A', 'A']
   distinct hold ids: {553}  replays: 9/9
   FAIL (or key reused from an earlier run: change the key)
   waiting 11 s so the rate-limit window of step 1 is empty ...
2. rate limit: 30 quick POST /holds with different keys
   statuses {201: 15, 429: 15}  (limit per replica per window is HOLD_RATE_LIMIT, default 5)
   accepted > 5 means the limit is per replica, not global
```

## 6. Proxy and backend log examples (same trace_id)

HTTP, `trace_id : "c-rr-http-17"`:

### ENVOY (proxy)
```json
{
  "@timestamp": "2026-11-21T06:07:20.070Z",
  "trace_id": "c-rr-http-17",
  "replica": "C",
  "listener": "http",
  "upstream_host": "172.19.0.6:8000",
  "response_code": 200,
  "request_id": "c-rr-http-17",
  "response_flags": "-",
  "service": "envoy",
  "path": "/eateries/1/menu",
  "time": "2026-11-21T06:07:20.070Z",
  "upstream_cluster": "app_http",
  "protocol": "HTTP/1.1",
  "method": "GET",
  "duration_ms": 3,
  "client": "172.19.0.1",
  "grpc_status": null
}
```

### REPLICA (backend)
```json
{
  "@timestamp": "2026-11-21T06:07:20.073Z",
  "trace_id": "c-rr-http-17",
  "replica": "C",
  "status": 200,
  "time": "2026-11-21T06:07:20.073Z",
  "service": "campus-food-app",
  "severity": "INFO",
  "request_id": "c-rr-http-17",
  "event": "request_completed",
  "route": "/eateries/{eatery_id}/menu",
  "method": "GET",
  "path": "/eateries/1/menu",
  "duration_ms": 1.7
}
```

### REPLICA (backend)
```json
{
  "@timestamp": "2026-11-21T06:07:20.073Z",
  "trace_id": "c-rr-http-17",
  "replica": "C",
  "time": "2026-11-21T06:07:20.073Z",
  "severity": "INFO",
  "route": "/eateries/{eatery_id}/menu",
  "status": 200,
  "path": "/eateries/1/menu",
  "duration_ms": 1.7,
  "service": "campus-food-app",
  "request_id": "c-rr-http-17",
  "event": "request_completed",
  "method": "GET"
}
```

OK: proxy and replica event found
Kibana Discover query: trace_id : "c-rr-http-17"   (http://localhost:5602, data view "Campus food logs")

gRPC, `trace_id : "c-rr-grpc-17"`:

### ENVOY (proxy)
```json
{
  "@timestamp": "2026-11-21T06:08:45.629Z",
  "trace_id": "c-rr-grpc-17",
  "replica": "B",
  "client": "172.19.0.1",
  "response_code": 200,
  "service": "envoy",
  "upstream_cluster": "app_grpc",
  "response_flags": "-",
  "duration_ms": 2,
  "time": "2026-11-21T06:08:45.629Z",
  "method": "POST",
  "protocol": "HTTP/2",
  "request_id": "c-rr-grpc-17",
  "upstream_host": "172.19.0.5:50051",
  "path": "/campus.holds.v1.HoldService/CreateHold",
  "listener": "grpc",
  "grpc_status": "OK"
}
```

### REPLICA (backend)
```json
{
  "@timestamp": "2026-11-21T06:08:45.631Z",
  "trace_id": "c-rr-grpc-17",
  "replica": "B",
  "service": "campus-food-app",
  "severity": "INFO",
  "request_id": "c-rr-grpc-17",
  "event": "hold_replayed",
  "hold_id": 548,
  "time": "2026-11-21T06:08:45.631Z"
}
```

### REPLICA (backend)
```json
{
  "@timestamp": "2026-11-21T06:08:45.631Z",
  "trace_id": "c-rr-grpc-17",
  "replica": "B",
  "duration_ms": 0.9,
  "severity": "INFO",
  "method": "/campus.holds.v1.HoldService/CreateHold",
  "grpc_status": "OK",
  "request_id": "c-rr-grpc-17",
  "event": "grpc_call_completed",
  "time": "2026-11-21T06:08:45.631Z",
  "service": "campus-food-app"
}
```

### REPLICA (backend)
```json
{
  "@timestamp": "2026-11-21T06:08:45.631Z",
  "trace_id": "c-rr-grpc-17",
  "replica": "B",
  "severity": "INFO",
  "request_id": "c-rr-grpc-17",
  "event": "hold_replayed",
  "hold_id": 548,
  "time": "2026-11-21T06:08:45.631Z",
  "service": "campus-food-app"
}
```

### REPLICA (backend)
```json
{
  "@timestamp": "2026-11-21T06:08:45.631Z",
  "trace_id": "c-rr-grpc-17",
  "replica": "B",
  "request_id": "c-rr-grpc-17",
  "method": "/campus.holds.v1.HoldService/CreateHold",
  "time": "2026-11-21T06:08:45.631Z",
  "service": "campus-food-app",
  "event": "grpc_call_completed",
  "grpc_status": "OK",
  "duration_ms": 0.9,
  "severity": "INFO"
}
```

OK: proxy and replica event found
Kibana Discover query: trace_id : "c-rr-grpc-17"   (http://localhost:5602, data view "Campus food logs")

## 7. Screenshots taken by hand

`docker compose ps` (three replicas and Envoy):

*(missing: docs/img/a3/ps.png)*

Kibana, HTTP: one search returning the Envoy event and the replica event:

*(missing: docs/img/a3/kibana-http.png)*

Kibana, gRPC: same for one unary call:

*(missing: docs/img/a3/kibana-grpc.png)*

