"""Turn loadgen results into the report's table and cross-check the traffic shares three ways:

  1. client   : which replica answered, from the X-Replica header / x-replica metadata the client saw
  2. prometheus: the replicas' own request counters, over the run window (taken directly from A, B, C)
  3. envoy    : Envoy's JSON access log in Elasticsearch, grouped by the replica field

    python experiments/a3/summarize.py experiments/a3/results/rr-http.json experiments/a3/results/rr-grpc.json

Run it a few seconds after the run ended (Prometheus scrapes every 5 s, Filebeat ships within seconds).
Between runs, leave about 20 s with no traffic so counters are stable. Stdlib only.
"""
import argparse
import glob
import json
import urllib.parse
import urllib.request

PROM = "http://localhost:9091"
ES = "http://localhost:9201"
METRIC = {"http": ('campus_http_requests_total{route="/eateries/{eatery_id}/menu"}', "http"),
          "grpc": ('campus_grpc_requests_total{method="CreateHold"}', "grpc")}


def expand(patterns):
    """PowerShell/cmd do not expand * themselves: do it here so the same command works everywhere."""
    out = []
    for pattern in patterns:
        out.extend(sorted(glob.glob(pattern)) or [pattern])
    return [p for p in out if not p.endswith("-events.json")]


def get(url, data=None):
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def prom_counts(selector, at):
    q = f"sum by (replica) ({selector})"
    res = get(f"{PROM}/api/v1/query?" + urllib.parse.urlencode({"query": q, "time": at}))["data"]["result"]
    return {r["metric"].get("replica", "?"): float(r["value"][1]) for r in res}


def prometheus_shares(res):
    sel, _ = METRIC[res["op"]]
    before = prom_counts(sel, res["start_epoch"] - 7)       # 7 s = more than one 5 s scrape interval
    after = prom_counts(sel, res["finished_epoch"] + 7)
    return {k: after.get(k, 0) - before.get(k, 0) for k in set(after) | set(before)}


def _envoy_filter(res):
    listener = METRIC[res["op"]][1]
    return {"bool": {"filter": [
        {"term": {"envoy.listener": listener}},
        {"prefix": {"envoy.request_id": res["tag"] + "-"}},
        {"range": {"@timestamp": {"gte": int((res["start_epoch"] - 5) * 1000), "lte": int((res["finished_epoch"] + 30) * 1000),
                                  "format": "epoch_millis"}}}]}}


def envoy_counts(res):
    body = {"size": 0, "query": _envoy_filter(res),
            "aggs": {"by_replica": {"terms": {"field": "envoy.replica", "size": 10, "missing": "(none: no replica answered)"}}}}
    out = get(f"{ES}/campus-food-logs-*/_search", json.dumps(body).encode())
    return {b["key"]: b["doc_count"] for b in out["aggregations"]["by_replica"]["buckets"]}


def envoy_latency(res):
    """Latency as the proxy saw it (request in to response out), from the access log: percentiles, mean, mean per replica."""
    body = {"size": 0, "query": _envoy_filter(res), "aggs": {
        "pct": {"percentiles": {"field": "envoy.duration_ms", "percents": [50, 90, 95, 99]}},
        "mean": {"avg": {"field": "envoy.duration_ms"}},
        "by_replica": {"terms": {"field": "envoy.replica", "size": 10, "missing": "(none)"},
                       "aggs": {"mean": {"avg": {"field": "envoy.duration_ms"}}}}}}
    out = get(f"{ES}/campus-food-logs-*/_search", json.dumps(body).encode())["aggregations"]
    r = lambda v: None if v is None else round(v, 1)
    return {"p50": r(out["pct"]["values"]["50.0"]), "p90": r(out["pct"]["values"]["90.0"]),
            "p95": r(out["pct"]["values"]["95.0"]), "p99": r(out["pct"]["values"]["99.0"]),
            "mean": r(out["mean"]["value"]),
            "mean_by_replica": {b["key"]: r(b["mean"]["value"]) for b in out["by_replica"]["buckets"]}}


def shares(counts):
    total = sum(counts.values())
    return {k: round(100 * v / total, 1) for k, v in sorted(counts.items())} if total else {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", nargs="+")
    args = ap.parse_args()
    rows = []
    for path in expand(args.results):
        r = json.load(open(path))
        print(f"\n== {r['tag']} ({r['op']}) ==")
        client = r["replicas_seen_by_client"]
        print("client  counts", client, "shares %", shares(client))
        try:
            pc = {k: v for k, v in prometheus_shares(r).items() if v}
            print("prom    counts", pc, "shares %", shares(pc))
        except Exception as exc:
            pc = {}
            print("prom    unavailable:", exc)
        try:
            ec = envoy_counts(r)
            print("envoy   counts", ec, "shares %", shares(ec))
        except Exception as exc:
            ec = {}
            print("envoy   unavailable:", exc)
        lat = {}
        try:
            lat = envoy_latency(r)
            print("envoy   latency ms (proxy side)", {k: v for k, v in lat.items() if k != "mean_by_replica"},
                  "mean by replica", lat["mean_by_replica"])
        except Exception as exc:
            print("envoy   latency unavailable:", exc)
        rows.append((r, shares(pc) or shares(client), lat.get("mean")))
    print("\n| Run / interface | Target / actual rps | A/B/C shares % (Prometheus) | Client p95 ms | Envoy mean ms | Error rate |")
    print("|---|---|---|---|---|---|")
    for r, sh, mean in rows:
        abc = "/".join(str(sh.get(k, 0)) for k in "ABC")
        print(f"| {r['tag']} / {r['op']} | {r['target_rps']:g} / {r['successes'] / r['duration_s']:.1f} ok | {abc} "
              f"| {r['client_p95_ms']} | {mean} | {100 * r['error_rate']:.1f}% |")


if __name__ == "__main__":
    main()
