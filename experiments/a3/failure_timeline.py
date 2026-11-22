"""Removal and recovery time of replica B in the failure experiment, measured from Envoy's access log.

    python experiments/a3/failure_timeline.py d3-fail-http d3-fail-grpc

Needs results/<tag>.json and results/<tag>-events.json (written by run_all.py) and the logs in Elasticsearch.
  removal   = last request Envoy could not deliver (response flag set, e.g. UF/UH) minus the moment B was stopped
  detection = first such failure minus the stop
  recovery  = first request answered by B after `docker start` minus the moment B was started
Compare with the health-check settings in envoy/render.py (interval, timeout, thresholds).
"""
import json
import os
import sys
import urllib.request

ES = "http://localhost:9201"
HERE = os.path.dirname(os.path.abspath(__file__))
INTERVAL, TIMEOUT, UNHEALTHY, HEALTHY = 2.0, 1.0, 2, 2      # keep equal to envoy/render.py


def es(body):
    req = urllib.request.Request(f"{ES}/campus-food-logs-*/_search", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=20))["aggregations"]


def base_filter(res, listener, lo, hi):
    return [{"term": {"envoy.listener": listener}}, {"prefix": {"envoy.request_id": res["tag"] + "-"}},
            {"range": {"@timestamp": {"gte": int(lo * 1000), "lte": int(hi * 1000), "format": "epoch_millis"}}}]


def edge(filters, extra=None, must_not=None):
    q = {"bool": {"filter": filters + (extra or []), "must_not": must_not or []}}
    a = es({"size": 0, "query": q, "aggs": {"first": {"min": {"field": "@timestamp"}}, "last": {"max": {"field": "@timestamp"}},
                                            "n": {"value_count": {"field": "@timestamp"}}}})
    f, l = a["first"]["value"], a["last"]["value"]
    return (f / 1000 if f else None, l / 1000 if l else None, a["n"]["value"])


def main():
    for tag in sys.argv[1:]:
        res = json.load(open(os.path.join(HERE, "results", f"{tag}.json")))
        ev = json.load(open(os.path.join(HERE, "results", f"{tag}-events.json")))
        listener = "http" if res["op"] == "http" else "grpc"
        stop, start, end = ev["stop_epoch"], ev["start_epoch"], res["finished_epoch"] + 30
        window = base_filter(res, listener, stop - 5, end)
        # undeliverable requests: Envoy set a response flag (UF = upstream connect failure, UH = no healthy upstream ...)
        f_first, f_last, n = edge(window, must_not=[{"term": {"envoy.response_flags": "-"}}])
        b_first, _, nb = edge(base_filter(res, listener, start, end), [{"term": {"envoy.replica": "B"}}])
        print(f"\n== {tag} ==")
        print(f"B stopped at +{stop - res['start_epoch']:.1f}s, started again at +{start - res['start_epoch']:.1f}s (run clock)")
        if f_first is None:
            print("no failed requests in the access log (is Filebeat caught up?)")
        else:
            print(f"failed requests in access log: {n}")
            print(f"detection  (stop -> first failure): {f_first - stop:5.1f} s")
            print(f"removal    (stop -> last failure) : {f_last - stop:5.1f} s")
        if b_first is None:
            print("B never answered after the restart")
        else:
            print(f"recovery   (start -> first answer from B): {b_first - start:5.1f} s")
        lo = (UNHEALTHY - 1) * INTERVAL
        hi = INTERVAL + (UNHEALTHY - 1) * INTERVAL + TIMEOUT
        print(f"settings: interval {INTERVAL:g}s, timeout {TIMEOUT:g}s, unhealthy {UNHEALTHY}, healthy {HEALTHY}")
        print(f"expected removal about {lo:g} to {hi:g} s after the stop (wait for next check + {UNHEALTHY - 1} more interval(s) + timeout)")
        print(f"expected recovery = app start-up time + about {HEALTHY - 1} to {HEALTHY} intervals ({(HEALTHY - 1) * INTERVAL:g} to {HEALTHY * INTERVAL:g} s)")
        print(f"back-of-envelope failures: rate x 1/3 x removal = {res['target_rps']:g} x 1/3 x removal time")


if __name__ == "__main__":
    main()
