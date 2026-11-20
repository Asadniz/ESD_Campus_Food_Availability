"""Fixed-rate (open-loop) test client for Assignment 3.

Requests are SENT on a schedule (request i at t0 + i/rate) whether or not earlier responses have come back, so a
slow replica cannot slow the sender down. Latency is measured from the scheduled send time, so time spent waiting
inside the client counts too (no hidden queueing). If the client itself falls behind, `max_send_lag_ms` shows it.

    python experiments/a3/loadgen.py --op http --rate 50 --duration 60 --tag baseline-http
    python experiments/a3/loadgen.py --op grpc --rate 50 --duration 60 --tag baseline-grpc

--op http : GET /eateries/1/menu          (read-only, through Envoy :8000)
--op grpc : CreateHold with ONE fixed idempotency key. The first call (not counted) creates a hold, every timed call
            is a replay of it: no new rows, and it proves idempotency records are shared by all replicas.
            All calls use ONE gRPC channel (one TCP connection), like a real client.
Every request carries x-request-id "<tag>-<n>", searchable in Kibana as  trace_id : "<tag>-17".
Writes experiments/a3/results/<tag>.json. Needs: pip install grpcio protobuf  (gRPC only)
"""
import argparse
import collections
import http.client
import json
import math
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "api"))


def pct(values, q):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, math.ceil(q * len(s)) - 1))]


class Recorder:
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = []          # (ok, status, latency_s, replica, scheduled_offset_s)

    def add(self, ok, status, latency, replica, at):
        with self.lock:
            self.rows.append((ok, status, latency, replica, at))


def run_http(args, rec, total, t0):
    local = threading.local()

    def conn():
        if not hasattr(local, "c"):
            local.c = http.client.HTTPConnection(args.http_host, args.http_port, timeout=args.timeout)
        return local.c

    def fire(i, started):
        try:
            c = conn()
            c.request("GET", "/eateries/1/menu", headers={"X-Request-ID": f"{args.tag}-{i}"})
            r = c.getresponse()
            r.read()
            rec.add(200 <= r.status < 300, str(r.status), time.perf_counter() - started, r.getheader("X-Replica"), started - t0)
        except Exception as exc:
            local.__dict__.pop("c", None)         # drop a broken connection, next request opens a new one
            rec.add(False, f"ERR:{type(exc).__name__}", time.perf_counter() - started, None, started - t0)

    lag = 0.0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i in range(total):
            due = t0 + i / args.rate
            delay = due - time.perf_counter()
            if delay > 0:
                time.sleep(delay)
            lag = max(lag, time.perf_counter() - due)
            pool.submit(fire, i, due)
    return lag


def run_grpc(args, rec, total, t0):
    import grpc
    import requests
    from campus_api.rpc import holds_pb2, holds_pb2_grpc

    channel = grpc.insecure_channel(args.grpc_target)
    stub = holds_pb2_grpc.HoldServiceStub(channel)
    key = f"{args.tag}-fixed-key"
    first = stub.CreateHold(holds_pb2.CreateHoldRequest(item_id=1, idempotency_key=key), timeout=args.timeout,
                            metadata=[("x-request-id", f"{args.tag}-setup")])
    done = threading.Semaphore(0)

    def make_cb(fut, started):  # t0 comes from the enclosing run_grpc argument
        def cb(_):
            code = fut.code()
            meta = dict(fut.initial_metadata() or ())
            rec.add(code == grpc.StatusCode.OK, code.name, time.perf_counter() - started, meta.get("x-replica"), started - t0)
            done.release()
        return cb

    lag = 0.0
    for i in range(total):
        due = t0 + i / args.rate
        delay = due - time.perf_counter()
        if delay > 0:
            time.sleep(delay)
        lag = max(lag, time.perf_counter() - due)
        fut = stub.CreateHold.future(holds_pb2.CreateHoldRequest(item_id=1, idempotency_key=key),
                                     timeout=args.timeout, metadata=[("x-request-id", f"{args.tag}-{i}")])
        fut.add_done_callback(make_cb(fut, due))
    for _ in range(total):                       # every call finishes at the latest at its deadline
        done.acquire(timeout=args.timeout + 5)
    channel.close()
    try:                                         # give the portion back
        requests.post(f"http://{args.http_host}:{args.http_port}/holds/{first.hold.id}/cancel", timeout=5)
    except Exception:
        print("warning: could not cancel the setup hold", first.hold.id)
    return lag


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--op", choices=["http", "grpc"], required=True)
    p.add_argument("--rate", type=float, default=50, help="requests per second (target)")
    p.add_argument("--duration", type=float, default=60, help="seconds")
    p.add_argument("--tag", required=True, help="run name; prefix of every x-request-id")
    p.add_argument("--timeout", type=float, default=5.0, help="per request, seconds")
    p.add_argument("--workers", type=int, default=128, help="http sender threads (must exceed rate x latency)")
    p.add_argument("--http-host", default="localhost")
    p.add_argument("--http-port", type=int, default=8000)
    p.add_argument("--grpc-target", default="localhost:50051")
    p.add_argument("--out", default=None)
    args = p.parse_args()

    total = int(args.rate * args.duration)
    rec = Recorder()
    print(f"{args.tag}: {args.op} target {args.rate:g} rps for {args.duration:g}s = {total} requests", flush=True)
    t0 = time.perf_counter()
    wall0 = time.time()
    lag = (run_http if args.op == "http" else run_grpc)(args, rec, total, t0)
    wall1 = time.time()
    elapsed = time.perf_counter() - t0

    ok = [r for r in rec.rows if r[0]]
    bad = [r for r in rec.rows if not r[0]]
    result = {
        "tag": args.tag, "op": args.op, "target_rps": args.rate, "duration_s": args.duration,
        "start_epoch": wall0, "end_epoch": wall0 + args.duration,           # the sending window
        "finished_epoch": wall1,
        "sent": total, "completed": len(rec.rows), "successes": len(ok), "failures": len(bad),
        "error_rate": round(len(bad) / total, 4) if total else None,
        "actual_send_rps": round(total / args.duration, 2),
        "max_send_lag_ms": round(lag * 1000, 1),
        "statuses": dict(collections.Counter(r[1] for r in rec.rows)),
        "client_p50_ms": round(pct([r[2] for r in ok], 0.50) * 1000, 1) if ok else None,
        "client_p95_ms": round(pct([r[2] for r in ok], 0.95) * 1000, 1) if ok else None,
        "client_p99_ms": round(pct([r[2] for r in ok], 0.99) * 1000, 1) if ok else None,
        "client_p95_all_ms": round(pct([r[2] for r in rec.rows], 0.95) * 1000, 1) if rec.rows else None,
        "first_failure_at_s": round(min(r[4] for r in bad), 1) if bad else None,   # seconds after the start
        "last_failure_at_s": round(max(r[4] for r in bad), 1) if bad else None,
        "replicas_seen_by_client": dict(collections.Counter(r[3] or "?" for r in rec.rows)),
    }
    out = args.out or os.path.join(HERE, "results", f"{args.tag}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    json.dump(result, open(out, "w"), indent=1)
    for k, v in result.items():
        if k not in ("start_epoch", "end_epoch", "finished_epoch"):
            print(f"  {k:24s} {v}")
    if lag > 0.05:
        print("  WARNING: the client fell behind its schedule; lower --rate or raise --workers.")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
