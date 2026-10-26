# Campus Food Availability

Shows the day's menu and live item availability for campus eateries, and lets a student
place a hold on an item so it is kept aside instead of eaten cold two hours later.

Built for Enterprise Software Development, Fall 2026.

- Assignment 1 (observability): write-up in `docs/REPORT.md`, metric table in `docs/METRICS.md`.
- Assignment 2 (HTTP API, gRPC, metrics): Part A evidence in `evidence_part_02.md`. Run and test
  commands are in the "Assignment 2" section below.

## Layout

```
api/                    FastAPI app (the only thing you would deploy for real)
  campus_api/
    main.py             wiring: routers, /metrics, background job, lifespan
    config.py           every setting, all from environment variables
    db.py, seed.py      SQLite access and demo data
    schemas.py          request and response bodies
    errors.py           one error format for every failure, plus OpenAPI error schemas
    hold_service.py    hold creation rules, shared by the HTTP route and the gRPC service
    grpc_server.py     gRPC service (CreateHold) and its logging interceptor
    rpc/               holds.proto and the generated holds_pb2*.py
    ratelimit.py        rate limiter for POST /holds
    auth.py             staff key check
    faults.py           fault-injection switches used by Experiment E1
    jobs.py             background job: hold expiry + daily menu reset
    observability/
      metrics.py        every Prometheus metric, one place, with comments
      logs.py           JSON log formatter + request-scoped request_id
      middleware.py     records metrics and one log line per request
      gauges.py         recomputes the two gauges from the database
    routers/
      eateries.py, items.py, holds.py, admin.py
    tests/              pytest suite (33 tests, 10 of them for gRPC)
caller/
  client.py             Python caller: timeout, limited retry with backoff, circuit breaker
  grpc_client.py        command-line client: CreateHold over gRPC (or HTTP, for comparison)
monitoring/
  prometheus/prometheus.yml
  grafana/              datasource + dashboard, provisioned automatically
  filebeat/filebeat.yml
  elasticsearch/setup.sh   retention policy + index template (runs once)
  kibana/setup.sh          data view + saved searches (runs once)
experiments/
  traffic.py            repeatable load generator used by both experiments
  e1_slow_menu.sh       Experiment E1: slow menu requests
  e2_cardinality.sh     Experiment E2: cardinality explosion
  hold_load.py          repeatable HTTP and gRPC calls that fill the Part C panels
  cardinality/          tiny standalone app used only by E2
openapi.json            OpenAPI description of the HTTP API
evidence_part_02.md     Assignment 2 Part A evidence
docker-compose.yml
```

## Start

Requires Docker and Docker Compose.

```bash
docker compose up -d --build
```

First start takes a minute or two (Elasticsearch has to come up before `es-setup` and
`filebeat` will proceed; `kibana-setup` waits for Kibana the same way). Check everything
is healthy:

```bash
docker compose ps
```

Open:
- API: http://localhost:8000/docs (interactive Swagger UI)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin / admin) — the dashboard is already provisioned
- Kibana: http://localhost:5601 (data view `Campus food logs` and saved searches are already there)

## Use it

```bash
curl localhost:8000/eateries
curl localhost:8000/eateries/1/menu
curl -X POST localhost:8000/holds -H 'Content-Type: application/json' \
     -d '{"item_id": 1, "pickup_in_minutes": 180}'
curl -X POST localhost:8000/holds/1/pickup

# staff-only (default demo key is staff-demo-key, set STAFF_KEY to change it)
curl -X PATCH localhost:8000/items/2/availability -H 'X-Staff-Key: staff-demo-key' \
     -H 'Content-Type: application/json' -d '{"available": false}'
```

To see realistic traffic and data on the dashboards without doing this by hand:

```bash
python3 experiments/traffic.py --tag manual --duration 60 --rps 5
```

## Test

```bash
cd api
pip install -r requirements-dev.txt
DB_PATH=/tmp/campus_test.db python -m pytest -v
```

On Windows PowerShell:

```powershell
cd api
pip install -r requirements-dev.txt
$env:DB_PATH="$env:TEMP\campus_test.db"
python -m pytest -v
```

The suite (33 tests) covers menu reads, the hold lifecycle (create, sold-out rejection,
pickup, cancel), the staff-key check, the common error format, rate limiting and
idempotency, and the gRPC service (`test_grpc.py`).

## Assignment 2

### Error format

Every error, including unknown routes, has the same body. The `request_id` is also in the
`x-request-id` response header and in the JSON log line for that request.

```bash
curl -i localhost:8000/holds/9999
curl -i -X POST localhost:8000/holds -H 'Content-Type: application/json' -d '{"item_id": 0}'
curl -i localhost:8000/nope
```

```json
{"error": {"code": "HOLD_NOT_FOUND", "message": "hold not found", "request_id": "72542927ffbd49aa"}}
```

### Idempotent hold creation

Send the same request twice with the same `Idempotency-Key`. The second response is the
stored one (same hold id) and carries `Idempotent-Replayed: true`. Reusing the key with a
different body returns `422 IDEMPOTENCY_KEY_REUSED`.

```bash
for i in 1 2; do
  curl -i -X POST localhost:8000/holds -H 'Content-Type: application/json' \
       -H 'Idempotency-Key: demo-1' -d '{"item_id": 1, "pickup_in_minutes": 180}'
done
```

### Rate limiting

`POST /holds` allows 5 requests per 10 seconds per client IP (sliding window, in memory,
single instance). The sixth request gets `429` with a `Retry-After` header. Other endpoints
are not limited. Change the limit with `HOLD_RATE_LIMIT` and `HOLD_RATE_WINDOW_SECONDS`
(set them in the environment before `docker compose up`).

```bash
for i in $(seq 1 7); do
  curl -s -o /dev/null -w "request $i -> %{http_code}\n" -X POST localhost:8000/holds \
       -H 'Content-Type: application/json' -d '{"item_id": 4, "pickup_in_minutes": 120}'
done
sleep 10    # allowed again after Retry-After seconds
```

### Python caller

`caller/client.py` acts like another service calling the API. It sets a timeout (1 s connect,
2 s read), retries safe calls up to 3 attempts with exponential backoff (0.5 s, then 1 s,
plus jitter), and uses a circuit breaker that opens after 3 consecutive failed attempts and
tries again after 10 s. `POST /holds` is retried only because every retry reuses one
`Idempotency-Key`.

The demo has three phases: a healthy server, an injected 3000 ms menu delay (longer than the
read timeout, so calls time out, retry and trip the breaker), and recovery after the fault is
removed. It needs the staff key to switch the fault on and off.

```bash
pip install requests
python caller/client.py --base-url http://localhost:8000 --staff-key staff-demo-key
```

The run takes about 25 seconds. The fault is always cleared at the end of phase 3.
Rate limiting is demonstrated separately (see above).

### OpenAPI

`openapi.json` is exported from the running app and validated:

```bash
curl -s localhost:8000/openapi.json -o openapi.json
pip install openapi-spec-validator
python -m openapi_spec_validator openapi.json      # prints: openapi.json: OK
```

Use Swagger UI (http://localhost:8000/docs) to try an endpoint against the spec, for
example `POST /holds` with `{"item_id": 0}`, which returns a documented `422`.

### gRPC service (Part B)

`CreateHold` in `api/campus_api/rpc/holds.proto` is the gRPC version of `POST /holds`. It runs in
its own container (`campus-grpc`, port 50051), calls the same `hold_service.create_hold` as the
HTTP route and uses the same SQLite file (shared `api-data` volume). `docker compose up -d --build`
starts it together with everything else.

Regenerate the Python code after changing the `.proto` (run from `api/`; the generated files are
committed, so this is only needed after an edit):

```bash
cd api
pip install -r requirements-dev.txt
python -m grpc_tools.protoc -I. --python_out=. --grpc_python_out=. campus_api/rpc/holds.proto
```

Call it from the repo root (`pip install grpcio protobuf requests` first). The client sets a
2 s deadline by default, sends an `x-request-id`, and prints the status, the error code and the
duration. Exit code is 0 on success, 1 on an error response, 2 when the server is unreachable or
the deadline passes.

```bash
python caller/grpc_client.py --item-id 1                                  # success
python caller/grpc_client.py --item-id 9999                               # NOT_FOUND
python caller/grpc_client.py --item-id 0                                  # INVALID_ARGUMENT
python caller/grpc_client.py --item-id 2 --idempotency-key demo-1         # run twice: same hold, replayed
python caller/grpc_client.py --item-id 1 --via http                       # same operation over HTTP
python caller/grpc_client.py --item-id 9999 --via http                    # 404
```

Find the call in Kibana with the request ID the client printed: `app.request_id : "<id>"`
shows `hold_created` (or `hold_rejected`) and `grpc_call_completed`, which has `app.grpc_status`.

Run it without Docker (for development):

```bash
cd api
DB_PATH=/tmp/campus.db python -m campus_api.main &          # HTTP API, creates and seeds the database
DB_PATH=/tmp/campus.db python -m campus_api.grpc_server     # gRPC service on :50051
```

Tests: `cd api && DB_PATH=/tmp/campus_test.db python -m pytest -v campus_api/tests/test_grpc.py`.

### Metrics for both versions (Part C)

The gRPC service serves its metrics on port 9102 (inside Docker, scraped by the Prometheus job
`campus-food-grpc`). Prometheus does not reload its config by itself, so restart it once after
pulling this change, then check that the target is UP at http://localhost:9091/targets:

```bash
docker compose up -d --build
docker compose restart prometheus
```

Fill the panels with repeatable calls. The HTTP rate limit (5 per 10 s) would reject most of the HTTP
calls, so raise it for the run and put it back afterwards:

```powershell
$env:HOLD_RATE_LIMIT="1000"; docker compose up -d api
pip install grpcio protobuf requests
python experiments/hold_load.py
Remove-Item Env:HOLD_RATE_LIMIT; docker compose up -d api
```

On Git Bash use `HOLD_RATE_LIMIT=1000 docker compose up -d api`. The script prints the outcome
counts of each transport (50 successes, 10 not found, 10 invalid, 10 sold out for each). Then open
Grafana at http://localhost:3001 and the dashboard "Create hold: HTTP vs gRPC" (last 15 minutes). Use
`--skip-burst` to leave out the gRPC-only burst that fills the "calls in flight" panel. The metric
list and queries are in `docs/METRICS.md` and `docs/A2_REPORT.md`.

### Evidence

`evidence_part_02.md` holds the outputs for Parts A, B and C. For Part A: tests, error format, idempotency, rate
limiting, caller output, and OpenAPI validation.

## Run the experiments (Assignment 1)

Both scripts print the UTC start/end of each stage. You need those for the Grafana time
range and the Kibana search when writing up Part E. Run them in Git Bash on Windows.

```bash
./experiments/e1_slow_menu.sh
./experiments/e2_cardinality.sh
```

## Clean up

```bash
docker compose down        # stop, keep data
docker compose down -v     # stop and delete all stored data (volumes)
```
