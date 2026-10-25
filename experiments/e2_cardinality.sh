#!/usr/bin/env bash
# Experiment E2: cardinality explosion, then recovery.
# Run 1 (WITH request_id label) -> stop -> Run 2 (WITHOUT the label) -> compare series counts.
set -euo pipefail
PROM=${PROM:-http://localhost:9091}

series_count() {
  curl -s "$PROM/api/v1/query" --data-urlencode 'query=count(demo_requests_total)' \
    | python3 -c "import sys,json; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else 0)"
}

echo "=== Run 1: WITH request_id label ==="
CARDINALITY_MODE=request_id docker compose --profile experiments up -d --build cardinality-demo
echo "generating 100 unique request IDs (20s)"; sleep 25
echo "series for demo_requests_total: $(series_count)"     # expect 100
echo "query used: count(demo_requests_total)"

docker compose stop cardinality-demo
docker compose rm -f cardinality-demo

echo
echo "=== Run 2: WITHOUT the label ==="
CARDINALITY_MODE=none docker compose --profile experiments up -d --build cardinality-demo
sleep 25
echo "series for demo_requests_total: $(series_count)"     # expect 1

echo
echo "cleaning up (stops the demo; does not delete Prometheus' stored history, by design)"
docker compose stop cardinality-demo
docker compose rm -f cardinality-demo
