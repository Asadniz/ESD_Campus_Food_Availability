"""Build docs/A3_EVIDENCE.md from your real results, charts and screenshots.

    python experiments/a3/make_evidence.py              # numbers and images only (no stack needed)
    python experiments/a3/make_evidence.py --collect    # also run summarize / failure_timeline / shared_state_check /
                                                        # log_pair against the live stack and embed their output

Reads  experiments/a3/results/*.json (+ *-events.json), docs/img/a3/<tag>.png (charts), <tag>-grafana.png.
Optional hand-made screenshots, if present in docs/img/a3/, are embedded too:
    ps.png (docker compose ps), kibana-http.png, kibana-grpc.png, kibana-failure.png
Nothing is invented: every number comes from the result files or from the scripts' own output.
"""
import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
RESULTS = os.path.join(HERE, "results")
IMG = os.path.join(ROOT, "docs", "img", "a3")
OUT = os.path.join(ROOT, "docs", "A3_EVIDENCE.md")

STAGES = [
    ("b-baseline", "Part B: baseline, A only (B and C running, not destinations)"),
    ("c-rr", "Part C: equal-weight round robin over A, B, C"),
    ("d1-weighted", "D1: weighted round robin, A:B:C = 2:1:1"),
    ("d2-rr-delay", "D2: round robin, fixed delay on B"),
    ("d2-lr-delay", "D2: least request, same delay on B"),
    ("d3-fail", "D3: round robin with active health checks, B stopped then restarted"),
]


def stage_of(tag):
    for prefix, title in STAGES:
        if tag.startswith(prefix):
            return prefix, title
    return tag, tag


def load():
    runs = []
    for path in sorted(glob.glob(os.path.join(RESULTS, "*.json"))):
        if path.endswith("-events.json"):
            continue
        r = json.load(open(path))
        ev = path.replace(".json", "-events.json")
        r["events"] = json.load(open(ev)) if os.path.exists(ev) else None
        runs.append(r)
    order = {p: i for i, (p, _) in enumerate(STAGES)}
    runs.sort(key=lambda r: (order.get(stage_of(r["tag"])[0], 99), r["op"] != "http", r["tag"]))
    return runs


def shares(r):
    seen = {k: v for k, v in r["replicas_seen_by_client"].items() if k != "?"}
    total = sum(seen.values())
    return "/".join(f"{100 * seen.get(k, 0) / total:.1f}" for k in "ABC") if total else "-"


def image(name, alt, base="img/a3/"):
    return f"![{alt}]({base}{name})\n" if os.path.exists(os.path.join(IMG, name)) else f"*(missing: docs/img/a3/{name})*\n"


def run_script(script, *args, timeout=240):
    cmd = [sys.executable, os.path.join(HERE, script), *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=ROOT)
        out = (p.stdout + (("\n[stderr]\n" + p.stderr) if p.stderr.strip() else "")).strip()
        return out or "(no output)"
    except Exception as exc:                      # keep going: a missing piece should not stop the file
        return f"(not collected: {exc})"


def block(text):
    return "```text\n" + text + "\n```\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--collect", action="store_true", help="run the analysis scripts against the live stack")
    ap.add_argument("--trace-http", default="c-rr-http-17")
    ap.add_argument("--trace-grpc", default="c-rr-grpc-17")
    args = ap.parse_args()
    runs = load()
    if not runs:
        raise SystemExit("no result files in experiments/a3/results: run experiments/a3/run_all.py first")

    md = [f"# Assignment 3: evidence\n",
          f"Generated {date.today()} by `experiments/a3/make_evidence.py` from the result files in "
          "`experiments/a3/results/`. Workload for every run: fixed rate, open loop, one HTTP operation "
          "(`GET /eateries/1/menu`) and one unary gRPC operation (`CreateHold` replay of one idempotency key) through Envoy. "
          "Client p95 is over successful requests. Shares below are what the client saw (replica header); "
          "section 3 cross-checks them against Prometheus and Envoy's access log.\n",
          "## 1. All runs\n",
          "| Run | Interface | Target / actual send rps | Sent | OK | Failed | Error rate | Client p50 / p95 / p99 ms | A/B/C share % (client) | Max send lag ms |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in runs:
        md.append(f"| {r['tag']} | {r['op']} | {r['target_rps']:g} / {r['actual_send_rps']} | {r['sent']} | {r['successes']} | "
                  f"{r['failures']} | {100 * r['error_rate']:.2f}% | {r['client_p50_ms']} / {r['client_p95_ms']} / {r['client_p99_ms']} | "
                  f"{shares(r)} | {r['max_send_lag_ms']} |")
    md.append("")

    md.append("## 2. Per run: numbers, chart and Grafana view\n")
    seen_stage = None
    for r in runs:
        prefix, title = stage_of(r["tag"])
        if prefix != seen_stage:
            md.append(f"### {title}\n")
            seen_stage = prefix
        md.append(f"**{r['tag']}** ({r['op']}): target {r['target_rps']:g} rps for {r['duration_s']:g} s, sent {r['sent']}, "
                  f"ok {r['successes']}, failed {r['failures']} {r['statuses']}, client p95 {r['client_p95_ms']} ms, "
                  f"replicas seen by client {r['replicas_seen_by_client']}.")
        if r["events"] and r.get("first_failure_at_s") is not None:
            ev = r["events"]
            md.append(f"B stopped at +{ev['stop_epoch'] - r['start_epoch']:.1f} s and started again at "
                      f"+{ev['start_epoch'] - r['start_epoch']:.1f} s (run clock); first failed request at +{r['first_failure_at_s']} s, "
                      f"last at +{r['last_failure_at_s']} s.")
        md.append("")
        md.append(image(f"{r['tag']}.png", f"{r['tag']} chart"))
        md.append(image(f"{r['tag']}-grafana.png", f"{r['tag']} Grafana"))

    tags_d3 = sorted({r["tag"] for r in runs if r["tag"].startswith("d3-fail")})
    if args.collect:
        files = [os.path.join("experiments", "a3", "results", f"{r['tag']}.json") for r in runs]
        md += ["## 3. Share cross-check: client, Prometheus, Envoy access log, plus proxy-side latency\n",
               block(run_script("summarize.py", *files)),
               "## 4. Failure timeline (removal and recovery of replica B)\n",
               block(run_script("failure_timeline.py", *tags_d3)) if tags_d3 else "*(no d3-fail runs found)*\n",
               "## 5. Shared state: idempotency (shared) and rate limit (per replica)\n",
               block(run_script("shared_state_check.py", timeout=120)),
               "## 6. Proxy and backend log examples (same trace_id)\n",
               f"HTTP, `trace_id : \"{args.trace_http}\"`:\n", run_script("log_pair.py", args.trace_http, "--md"), "",
               f"gRPC, `trace_id : \"{args.trace_grpc}\"`:\n", run_script("log_pair.py", args.trace_grpc, "--md"), ""]
    else:
        md += ["## 3. to 6. Cross-checks and log examples\n",
               "*Not collected. Run `python experiments/a3/make_evidence.py --collect` with the stack up.*\n"]

    md += ["## 7. Screenshots taken by hand\n",
           "`docker compose ps` (three replicas and Envoy):\n", image("ps.png", "docker compose ps"),
           "Kibana, HTTP: one search returning the Envoy event and the replica event:\n", image("kibana-http.png", "Kibana HTTP"),
           "Kibana, gRPC: same for one unary call:\n", image("kibana-grpc.png", "Kibana gRPC")]
    if os.path.exists(os.path.join(IMG, "kibana-failure.png")):
        md += ["Kibana, failure run:\n", image("kibana-failure.png", "Kibana failure")]
    open(OUT, "w", encoding="utf-8").write("\n".join(md) + "\n")
    print("wrote", OUT, f"({len(runs)} runs)")


if __name__ == "__main__":
    main()
