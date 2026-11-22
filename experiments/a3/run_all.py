"""Run the whole Assignment 3 workload in order, with timing, so the results line up with the report.

    python experiments/a3/run_all.py                    # everything: B baseline, C round robin, D1, D2, D3
    python experiments/a3/run_all.py --only baseline rr # just some stages
    python experiments/a3/run_all.py --rate 50 --duration 60 --settle 25

Stages (in this order):  baseline  rr  weighted  delay  failure
Each stage switches Envoy's config (envoy/render.py), recreates Envoy, then runs HTTP and gRPC one after the
other with the same fixed-rate workload and waits `--settle` seconds so Prometheus counters and the 1 m rate
windows are quiet before the next run. It always restores the normal round-robin state at the end, even on error.

Result files go to experiments/a3/results/<tag>.json. The failure stage also writes <tag>-events.json with the
exact times it stopped and started replica B (charts.py draws them; use them to compute removal/recovery time).
Portable on purpose (no shell script): needs only Python and the docker CLI.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RESULTS = os.path.join(HERE, "results")
PY = sys.executable
B_CONTAINER = "campus-food-app-2"          # replica B


def sh(cmd, check=True):
    print("  $", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, check=check)


def envoy_ready(timeout=40):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if urllib.request.urlopen("http://localhost:9901/ready", timeout=2).status == 200:
                return True
        except Exception:
            time.sleep(1)
    return False


def stage(name, *flags, wait=8):
    print(f"\n=== Envoy stage: {name} {' '.join(flags)}", flush=True)
    sh([PY, "envoy/render.py", name, *flags])
    sh(["docker", "compose", "up", "-d", "--no-deps", "--force-recreate", "envoy"])
    if not envoy_ready():
        raise SystemExit("Envoy did not become ready (docker compose logs envoy)")
    time.sleep(wait)                         # DNS, first health checks, first Prometheus scrape


def delay(replica_index, ms):
    sh(["docker", "compose", "exec", "-T", "--index", str(replica_index), "app",
        "python", "-m", "campus_api.faultctl", str(ms)])


def loadgen_cmd(op, tag, args):
    return [PY, "experiments/a3/loadgen.py", "--op", op, "--rate", str(args.rate),
            "--duration", str(args.duration), "--tag", tag]


def run(op, tag, args):
    print(f"\n--- {tag}", flush=True)
    sh(loadgen_cmd(op, tag, args))
    time.sleep(args.settle)


def both(prefix, args):
    for op in ("http", "grpc"):
        run(op, f"{prefix}-{op}", args)


def failure(args):
    stage("rr", "--health-checks", wait=10)
    duration = max(args.duration, 90)
    for op in ("http", "grpc"):
        tag = f"d3-fail-{op}"
        print(f"\n--- {tag}: stop B at +{args.stop_at}s, start it at +{args.start_at}s", flush=True)
        cmd = loadgen_cmd(op, tag, args)
        cmd[cmd.index("--duration") + 1] = str(duration)
        proc = subprocess.Popen(cmd, cwd=ROOT)
        t0 = time.time()
        events = {"tag": tag, "stop_cmd": f"docker stop {B_CONTAINER}", "start_cmd": f"docker start {B_CONTAINER}"}
        time.sleep(max(0, args.stop_at - (time.time() - t0)))
        events["stop_epoch"] = time.time()
        sh(["docker", "stop", B_CONTAINER])
        events["stop_returned_epoch"] = time.time()
        time.sleep(max(0, args.start_at - (time.time() - t0)))
        events["start_epoch"] = time.time()
        sh(["docker", "start", B_CONTAINER])
        proc.wait()
        json.dump(events, open(os.path.join(RESULTS, f"{tag}-events.json"), "w"), indent=1)
        time.sleep(args.settle)


def restore():
    print("\n=== restoring the normal round-robin state", flush=True)
    sh(["docker", "compose", "start", "app"], check=False)           # starts any stopped replica
    time.sleep(6)                                                     # let a restarted replica come up
    try:
        delay(2, 0)
    except subprocess.CalledProcessError:
        print("  could not clear B's delay: run  docker compose exec -T --index 2 app python -m campus_api.faultctl 0")
    stage("rr", wait=4)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", choices=["baseline", "rr", "weighted", "delay", "failure"])
    ap.add_argument("--rate", type=float, default=50)
    ap.add_argument("--duration", type=float, default=60)
    ap.add_argument("--settle", type=float, default=25, help="quiet seconds after each run")
    ap.add_argument("--delay-ms", type=int, default=200, help="delay added to replica B in D2")
    ap.add_argument("--stop-at", type=float, default=20, help="D3: seconds into the run when B is stopped")
    ap.add_argument("--start-at", type=float, default=50, help="D3: seconds into the run when B is started again")
    args = ap.parse_args()
    todo = args.only or ["baseline", "rr", "weighted", "delay", "failure"]
    os.makedirs(RESULTS, exist_ok=True)

    n = subprocess.run(["docker", "compose", "ps", "--status", "running", "-q", "app"], cwd=ROOT,
                       capture_output=True, text=True).stdout.split()
    if len(n) != 3:
        raise SystemExit(f"expected 3 running app replicas, found {len(n)}: docker compose up -d --scale app=3")
    if args.start_at <= args.stop_at or args.start_at + 20 > max(args.duration, 90):
        raise SystemExit("D3 timing: need stop-at < start-at and 20 s of recovery before the run ends")

    try:
        if "baseline" in todo:
            stage("a-only")
            both("b-baseline", args)
        if "rr" in todo:
            stage("rr")
            both("c-rr", args)
        if "weighted" in todo:
            stage("weighted")
            both("d1-weighted", args)
        if "delay" in todo:
            stage("rr")
            delay(2, args.delay_ms)
            both("d2-rr-delay", args)
            stage("least-request")
            both("d2-lr-delay", args)
            delay(2, 0)
        if "failure" in todo:
            failure(args)
    finally:
        restore()
    print("\nDone. Next: python experiments/a3/summarize.py experiments/a3/results/*-http.json experiments/a3/results/*-grpc.json")


if __name__ == "__main__":
    main()
