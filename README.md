# Campus Food Availability

Shows the day's menu and live item availability for campus eateries, and lets a student
place a hold on an item so it is kept aside instead of eaten cold two hours later.

Built for the Enterprise Software Development Assignment 1 (observability). See
`docs/REPORT.md` for the write-up (Parts A-E) and `docs/METRICS.md` for the full metric table.

## Layout

```
api/                    FastAPI app (the only thing you would deploy for real)
  campus_api/
    main.py             wiring: routers, /metrics, background job, lifespan
    config.py           every setting, all from environment variables
    db.py, seed.py       SQLite access and demo data
    schemas.py           request bodies
    auth.py               staff key check
    faults.py             fault-injection switches used by Experiment E1
    jobs.py               background job: hold expiry + daily menu reset
    observability/
      metrics.py          every Prometheus metric, one place, with comments
      logs.py              JSON log formatter + request-scoped request_id
      middleware.py        records metrics and one log line per request
      gauges.py            recomputes the two gauges from the database
    routers/
      eateries.py, items.py, holds.py, admin.py
monitoring/
  prometheus/prometheus.yml
  grafana/                 datasource + dashboard, provisioned automatically
  filebeat/filebeat.yml
  elasticsearch/setup.sh   retention policy + index template (runs once)
  kibana/setup.sh          data view + saved searches (runs once)
experiments/
  traffic.py               repeatable load generator used by both experiments
  e1_slow_menu.sh          Experiment E1: slow menu requests
  e2_cardinality.sh        Experiment E2: cardinality explosion
  cardinality/             tiny standalone app used only by E2
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
- Prometheus: http://localhost:9091
- Grafana: http://localhost:3001 (admin / admin) — the dashboard is already provisioned
- Kibana: http://localhost:5602 (data view `Campus food logs` and saved searches are already there)
- Elasticsearch: http://localhost:9201 

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
cd api && pip install -r requirements.txt pytest httpx --break-system-packages
DB_PATH=/tmp/campus_test.db pytest
```

`api/campus_api/tests/` covers menu reads, the hold lifecycle (create, sold-out rejection,
pickup, cancel), and the staff-key check.

## Run the experiments

Both scripts print the UTC start/end of each stage. You need those for the Grafana time
range and the Kibana search when writing up Part E.

```bash
./experiments/e1_slow_menu.sh
./experiments/e2_cardinality.sh
```

## Clean up

```bash
docker compose down
docker compose down -v
```
