"""Repeatable calls to fill the Part C panels: the same operation (create a hold) over HTTP and gRPC.

Phase 1, steady (about 25 s): the same fixed sequence of 8 calls per round, sent to HTTP and to gRPC
in turn. Each round has 4 new holds, 1 repeat of an Idempotency-Key, 1 unknown item, 1 invalid
item_id and 1 sold-out item, so the counts are the same on every run (see the table it prints).
Holds it creates are cancelled straight away, which gives the portion back.

Phase 2, burst (gRPC only, default 20 s): several workers call at once, each call held for a
moment on the server, so the "calls in flight" gauge is high at every Prometheus scrape. The
delay uses the staff-key-protected `x-fault-delay-ms` switch of the gRPC service.

Before running, raise the HTTP rate limit, or the HTTP side will mostly return 429:
    HOLD_RATE_LIMIT=1000 docker compose up -d api        (PowerShell: $env:HOLD_RATE_LIMIT="1000")
and put it back afterwards with a plain `docker compose up -d api` after clearing the variable.

    python experiments/hold_load.py
    python experiments/hold_load.py --skip-burst --rounds 5

Needs: pip install grpcio protobuf requests
"""
import argparse
import collections
import os
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api"))

import grpc  # noqa: E402
import requests  # noqa: E402

from campus_api.rpc import holds_pb2, holds_pb2_grpc  # noqa: E402

# One round. "replay" repeats the key of the previous "ok" call.
ROUND = ["ok", "replay", "ok", "ok", "notfound", "invalid", "soldout", "ok"]
ITEM_OK, ITEM_SOLD_OUT, ITEM_MISSING, ITEM_INVALID = 1, 2, 9999, 0


class Load:
    def __init__(self, args):
        self.args = args
        self.run = args.run_id or uuid.uuid4().hex[:6]
        self.http = requests.Session()
        self.channel = grpc.insecure_channel(args.grpc_target)
        self.stub = holds_pb2_grpc.HoldServiceStub(self.channel)
        self.staff = {"X-Staff-Key": args.staff_key}
        self.counts = {"http": collections.Counter(), "grpc": collections.Counter()}
        self.lock = threading.Lock()

    # ----------------------------------------------------------------- one call, either transport
    def _cancel(self, hold_id: int) -> None:
        self.http.post(f"{self.args.http_url}/holds/{hold_id}/cancel", timeout=5)

    def call_http(self, item_id: int, key: str | None, request_id: str) -> str:
        headers = {"X-Request-ID": request_id}
        if key:
            headers["Idempotency-Key"] = key
        r = self.http.post(f"{self.args.http_url}/holds", json={"item_id": item_id}, headers=headers, timeout=5)
        if r.status_code == 201 and r.headers.get("Idempotent-Replayed") != "true":
            self._cancel(r.json()["id"])
        return str(r.status_code)

    def call_grpc(self, item_id: int, key: str | None, request_id: str, delay_ms: int = 0) -> str:
        metadata = [("x-request-id", request_id)]
        if delay_ms:
            metadata += [("x-staff-key", self.args.staff_key), ("x-fault-delay-ms", str(delay_ms))]
        try:
            resp = self.stub.CreateHold(
                holds_pb2.CreateHoldRequest(item_id=item_id, idempotency_key=key or ""),
                timeout=10, metadata=metadata)
        except grpc.RpcError as err:
            return err.code().name
        if not resp.replayed:
            self._cancel(resp.hold.id)
        return "OK"

    # ----------------------------------------------------------------- phases
    def set_item(self, item_id: int, available: bool) -> None:
        r = self.http.patch(f"{self.args.http_url}/items/{item_id}/availability", json={"available": available},
                            headers=self.staff, timeout=5)
        r.raise_for_status()

    def steady(self) -> None:
        print(f"phase 1: steady, {self.args.rounds} rounds x {len(ROUND)} calls per transport", flush=True)
        n = 0
        last_key = {"http": None, "grpc": None}
        for _ in range(self.args.rounds):
            for kind in ROUND:
                for transport in ("grpc", "http"):
                    n += 1
                    item = {"ok": ITEM_OK, "replay": ITEM_OK, "notfound": ITEM_MISSING,
                            "invalid": ITEM_INVALID, "soldout": ITEM_SOLD_OUT}[kind]
                    key = None
                    if kind == "ok":
                        key = last_key[transport] = f"{self.run}-{transport[0]}-{n}"
                    elif kind == "replay":
                        key = last_key[transport]
                    request_id = f"load-{self.run}-{transport[0]}{n}"
                    if transport == "grpc":
                        outcome = self.call_grpc(item, key, request_id)
                    else:
                        outcome = self.call_http(item, key, request_id)
                    self.counts[transport][outcome] += 1
                    time.sleep(self.args.pause)

    def burst(self) -> None:
        a = self.args
        print(f"phase 2: burst, gRPC only, {a.workers} workers for {a.burst_seconds:.0f} s, "
              f"{a.burst_delay_ms} ms held per call", flush=True)
        key = f"{self.run}-burst"
        self.call_grpc(ITEM_OK, key, f"load-{self.run}-burst-first")      # creates the one hold that is replayed
        end = time.time() + a.burst_seconds
        kinds = ["replay", "notfound", "invalid"]

        def worker(w: int) -> None:
            i = w                                    # workers start at different points of the cycle
            while time.time() < end:
                kind = kinds[i % len(kinds)]
                i += 1
                item = {"replay": ITEM_OK, "notfound": ITEM_MISSING, "invalid": ITEM_INVALID}[kind]
                outcome = self.call_grpc(item, key if kind == "replay" else None,
                                         f"load-{self.run}-b{w}-{i}", delay_ms=a.burst_delay_ms)
                with self.lock:
                    self.counts["grpc_burst"][outcome] += 1

        self.counts["grpc_burst"] = collections.Counter()
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            list(pool.map(worker, range(a.workers)))

    def close(self) -> None:
        self.channel.close()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--http-url", default="http://localhost:8000")
    p.add_argument("--grpc-target", default="localhost:50051")
    p.add_argument("--staff-key", default="staff-demo-key")
    p.add_argument("--rounds", type=int, default=10, help="rounds of 8 calls per transport in phase 1")
    p.add_argument("--pause", type=float, default=0.15, help="seconds between calls in phase 1")
    p.add_argument("--skip-burst", action="store_true")
    p.add_argument("--burst-seconds", type=float, default=20.0)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--burst-delay-ms", type=int, default=300)
    p.add_argument("--run-id", default=None, help="prefix of idempotency keys and request IDs (random if omitted)")
    args = p.parse_args()

    load = Load(args)
    started = time.time()
    print(f"run id {load.run}  (request IDs look like load-{load.run}-g12 for gRPC, -h12 for HTTP)")
    try:
        load.set_item(ITEM_SOLD_OUT, False)          # item 2 is the sold-out item for this run
        load.steady()
        if not args.skip_burst:
            load.burst()
    finally:
        load.set_item(ITEM_SOLD_OUT, True)           # always switch item 2 back on
        load.close()

    print(f"\nfinished in {time.time() - started:.0f} s. Results by outcome (HTTP status or gRPC status):")
    for name, counter in load.counts.items():
        print(f"  {name:11s} {dict(sorted(counter.items()))}")
    http = load.counts["http"]
    if http.get("429"):
        print("\nwarning: some HTTP calls were rate limited (429). Raise HOLD_RATE_LIMIT for this run, see the top of this file.")
    print("\nOpen Grafana: http://localhost:3001 -> dashboard 'Create hold: HTTP vs gRPC' (last 15 minutes).")


if __name__ == "__main__":
    main()
