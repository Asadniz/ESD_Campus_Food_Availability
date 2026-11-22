"""Print the proxy event and the replica event for one request (the "two log examples" in the report).

    python experiments/a3/log_pair.py c-rr-http-17          # one HTTP request
    python experiments/a3/log_pair.py c-rr-grpc-17          # one unary gRPC call
    python experiments/a3/log_pair.py c-rr-http-17 --md     # as Markdown, ready to paste into the report

Both events share the trace_id (= the X-Request-ID the client sent, forwarded by Envoy). Envoy's event names the
replica it picked (`envoy.replica`, `envoy.upstream_host`); the replica's own event has `app.replica`.
The id must be one that exists: ids are "<tag>-<n>" with n from 0 to sent-1. Wait ~10 s after the run for Filebeat.
Also prints the Kibana Discover query to use for the screenshot.
"""
import argparse
import json
import urllib.request

ES = "http://localhost:9201"
KIBANA = "http://localhost:5602"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trace_id")
    ap.add_argument("--md", action="store_true")
    args = ap.parse_args()
    body = {"size": 10, "sort": [{"@timestamp": "asc"}], "query": {"term": {"trace_id": args.trace_id}}}
    req = urllib.request.Request(f"{ES}/campus-food-logs-*/_search", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    hits = json.load(urllib.request.urlopen(req, timeout=15))["hits"]["hits"]
    if not hits:
        raise SystemExit(f'no events with trace_id "{args.trace_id}" (wrong id, not shipped yet, or old index mapping: see README)')
    for h in hits:
        src = h["_source"]
        kind = "ENVOY (proxy)" if "envoy" in src else "REPLICA (backend)"
        doc = src.get("envoy") or src.get("app") or src
        text = json.dumps({"@timestamp": src.get("@timestamp"), "trace_id": src.get("trace_id"),
                           "replica": src.get("replica"), **doc}, indent=2)
        print(f"### {kind}\n```json\n{text}\n```\n" if args.md else f"--- {kind}\n{text}\n")
    kinds = {"envoy" in h["_source"] for h in hits}
    print("OK: proxy and replica event found" if kinds == {True, False} else "WARNING: only one side found (check Filebeat / the id)")
    print(f'Kibana Discover query: trace_id : "{args.trace_id}"   ({KIBANA}, data view "Campus food logs")')


if __name__ == "__main__":
    main()
