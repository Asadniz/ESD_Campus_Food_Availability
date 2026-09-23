#!/usr/bin/env bash
# Experiment E1: slow menu requests during a simulated lunch rush.
# Runs baseline -> fault -> recovery, 2 minutes each (24 Prometheus scrapes at 5 s).
# Note the wall-clock start/end printed for each stage: you need them for Grafana and Kibana time ranges.
set -euo pipefail
BASE=${BASE:-http://localhost:8000}
KEY=${STAFF_KEY:-staff-demo-key}
DURATION=${DURATION:-120}
HERE="$(cd "$(dirname "$0")" && pwd)"

stage() {  # stage <tag>
  echo "=== $1 start: $(date -u +%H:%M:%S) UTC"
  python3 "$HERE/traffic.py" --base "$BASE" --tag "$1" --duration "$DURATION" --rps 5
  echo "=== $1 end:   $(date -u +%H:%M:%S) UTC"
}

echo "faults now:"; curl -s -X DELETE "$BASE/admin/faults" -H "X-Staff-Key: $KEY"; echo
stage e1-baseline

echo "switching fault ON: 500 ms extra on every 5th menu request"
curl -s -X POST "$BASE/admin/faults" -H "X-Staff-Key: $KEY" -H 'Content-Type: application/json' \
     -d '{"menu_delay_ms":500,"menu_delay_every_nth":5}'; echo
stage e1-fault

echo "switching fault OFF"
curl -s -X DELETE "$BASE/admin/faults" -H "X-Staff-Key: $KEY"; echo
stage e1-recovery
