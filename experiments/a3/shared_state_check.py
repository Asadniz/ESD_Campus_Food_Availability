"""Shows, through Envoy, what is shared between replicas and what is not (Assignment 3, Part A).

  1. IDEMPOTENCY (shared, in the database): the same Idempotency-Key sent 9 times is spread over A, B, C by
     round robin, yet exactly ONE hold is created; the other 8 answers are replays of it.
  2. RATE LIMIT (NOT shared, in each replica's memory): 30 quick POST /holds with different keys. One replica
     would accept HOLD_RATE_LIMIT (default 5) per window; N replicas accept about N x that.

Run it with the round-robin stage (python envoy/render.py rr) and an idle system. Wait 10 s between runs.
    python experiments/a3/shared_state_check.py
"""
import argparse
import collections
import json
import time
import urllib.error
import urllib.request


def call(base, method, path, body=None, headers=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), json.load(e)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    base = ap.parse_args().base

    print("1. same Idempotency-Key x9")
    ids, who, replays = set(), [], 0
    for i in range(9):
        st, h, b = call(base, "POST", "/holds", {"item_id": 1}, {"Idempotency-Key": "a3-demo-key", "X-Request-ID": f"a3-idem-{i}"})
        ids.add(b.get("id"))
        who.append(h.get("X-Replica"))
        replays += h.get("Idempotent-Replayed") == "true"
    print(f"   answered by replicas {who}\n   distinct hold ids: {ids}  replays: {replays}/9")
    print("   PASS: one hold, shared idempotency records" if len(ids) == 1 and replays == 8 else "   FAIL (or key reused from an earlier run: change the key)")
    for hid in ids:
        call(base, "POST", f"/holds/{hid}/cancel")

    print("   waiting 11 s so the rate-limit window of step 1 is empty ...")
    time.sleep(11)
    print("2. rate limit: 30 quick POST /holds with different keys")
    codes, created = collections.Counter(), []
    for i in range(30):
        st, h, b = call(base, "POST", "/holds", {"item_id": 1}, {"Idempotency-Key": f"a3-rl-{i}-{int(time.time())}", "X-Request-ID": f"a3-rl-{i}"})
        codes[st] += 1
        if st == 201:
            created.append(b["id"])
    print(f"   statuses {dict(codes)}  (limit per replica per window is HOLD_RATE_LIMIT, default 5)")
    print("   accepted > 5 means the limit is per replica, not global")
    for hid in created:
        call(base, "POST", f"/holds/{hid}/cancel")


if __name__ == "__main__":
    main()
