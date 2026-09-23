"""Repeatable traffic generator for the experiments (standard library only).

Example:
    python experiments/traffic.py --tag e1-baseline --duration 120 --rps 5

Same --seed gives the same sequence of actions, so before/during/after runs are comparable.
Every request carries X-Request-ID "<tag>-<n>", so the run can be found in Kibana with
    app.request_id : e1-baseline-*
"""
import argparse
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

STAFF_KEY = "staff-demo-key"


def call(base, method, path, body, request_id, staff=False):
    data = json.dumps(body).encode() if body is not None else None
    headers = {"X-Request-ID": request_id, "Content-Type": "application/json"}
    if staff:
        headers["X-Staff-Key"] = STAFF_KEY
    req = urllib.request.Request(base + path, data=data, method=method, headers=headers)
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload, status = resp.read(), resp.status
    except urllib.error.HTTPError as err:
        payload, status = err.read(), err.code
    except Exception:
        payload, status = b"", 0
    return status, time.perf_counter() - started, payload


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--tag", default="run", help="prefix for X-Request-ID")
    ap.add_argument("--duration", type=int, default=120, help="seconds")
    ap.add_argument("--rps", type=float, default=5.0, help="requests per second")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    rng = random.Random(args.seed)
    holds, lock = [], threading.Lock()
    results = []  # (action, status, seconds)

    def do(n, action, item_id, eatery_id):
        rid = f"{args.tag}-{n}"
        if action == "menu":
            status, secs, _ = call(args.base, "GET", f"/eateries/{eatery_id}/menu", None, rid)
        elif action == "item":
            status, secs, _ = call(args.base, "GET", f"/items/{item_id}", None, rid)
        elif action == "hold":
            status, secs, payload = call(args.base, "POST", "/holds", {"item_id": item_id, "pickup_in_minutes": 180}, rid)
            if status == 201:
                with lock:
                    holds.append(json.loads(payload)["id"])
        elif action in ("pickup", "cancel"):
            with lock:
                hold_id = holds.pop() if holds else None
            if hold_id is None:
                return
            status, secs, _ = call(args.base, "POST", f"/holds/{hold_id}/{action}", None, rid)
        else:  # staff toggle
            status, secs, _ = call(args.base, "PATCH", f"/items/{item_id}/availability",
                                   {"available": rng_toggle[0], "portions_left": 20}, rid, staff=True)
        results.append((action, status, secs))

    rng_toggle = [True]
    actions = ["menu"] * 60 + ["item"] * 15 + ["hold"] * 14 + ["pickup"] * 6 + ["cancel"] * 2 + ["staff"] * 3
    total = int(args.duration * args.rps)
    started = time.time()
    with ThreadPoolExecutor(max_workers=32) as pool:
        for n in range(total):
            action = rng.choice(actions)
            item_id, eatery_id = rng.randint(1, 10), rng.randint(1, 3)
            rng_toggle[0] = rng.random() < 0.7
            pool.submit(do, n, action, item_id, eatery_id)
            time.sleep(max(0.0, started + (n + 1) / args.rps - time.time()))

    print(f"tag={args.tag} requests={len(results)} duration={time.time() - started:.0f}s")
    print("status codes:", dict(Counter(s for _, s, _ in results)))
    for action in ("menu", "item", "hold", "pickup", "cancel", "staff"):
        times = sorted(t for a, _, t in results if a == action)
        if times:
            p95 = times[min(len(times) - 1, int(len(times) * 0.95))]
            print(f"  {action:7s} n={len(times):4d} mean={statistics.mean(times)*1000:7.1f} ms  p95={p95*1000:7.1f} ms")


if __name__ == "__main__":
    main()
