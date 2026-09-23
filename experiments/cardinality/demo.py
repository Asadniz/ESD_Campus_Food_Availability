"""Experiment E2: cardinality explosion, safely capped at 100 unique IDs.

MODE=request_id  -> counter has a request_id label   (100 IDs -> 100 time series)
MODE=none        -> same traffic, no request_id label (1 time series)
"""
import os
import time
import uuid

from prometheus_client import Counter, disable_created_metrics, start_http_server

disable_created_metrics()
MODE = os.getenv("MODE", "request_id")
MAX_IDS = 100  # hard stop, on purpose

if MODE == "request_id":
    requests = Counter("demo_requests_total", "Demo counter WITH a request_id label.", ["route", "request_id"])
else:
    requests = Counter("demo_requests_total", "Demo counter without a request_id label.", ["route"])

start_http_server(8001)
print(f"demo running, MODE={MODE}, will generate {MAX_IDS} requests then idle", flush=True)
for i in range(MAX_IDS):
    request_id = uuid.uuid4().hex[:12]
    if MODE == "request_id":
        requests.labels("/menu", request_id).inc()
    else:
        requests.labels("/menu").inc()
    time.sleep(0.2)  # 20 s total, several scrapes see the series count grow
print("done generating, idling (metrics stay available)", flush=True)
while True:
    time.sleep(3600)
