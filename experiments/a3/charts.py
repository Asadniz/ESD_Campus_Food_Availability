"""Draw one evidence chart per run from Prometheus, for the exact time window of that run.

    pip install matplotlib
    python experiments/a3/charts.py experiments/a3/results/c-rr-http.json experiments/a3/results/c-rr-grpc.json
    python experiments/a3/charts.py experiments/a3/results/*-http.json experiments/a3/results/*-grpc.json

Output: docs/img/a3/<tag>.png  (six panels: request rate, share of traffic, active requests, p95, errors by
status, Envoy healthy members). Same queries and the same 1 minute rate window as the Grafana dashboard; the
shaded band is the period the client was sending. If <tag>-events.json exists (failure runs) the stop / start of
replica B is drawn as vertical lines. Dashed horizontal lines show the expected share (100/0/0, 33.3 or 50/25/25).
Run it within Prometheus' retention (default 15 days) and after the 5 s scrape has caught up (wait ~10 s).
"""
import argparse
import glob
import json
import os
import urllib.parse
import urllib.request

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "docs", "img", "a3"))
PROM = "http://localhost:9091"
COLORS = {"A": "#1f77b4", "B": "#ff7f0e", "C": "#2ca02c", "D": "#9467bd"}
M = {"http": ("campus_http_requests_total", "campus_http_requests_in_progress",
              "campus_http_request_duration_seconds", 'status!~"2.."', "app_http"),
     "grpc": ("campus_grpc_requests_total", "campus_grpc_requests_in_progress",
              "campus_grpc_request_duration_seconds", 'status!="OK"', "app_grpc")}


def expand(patterns):
    """PowerShell/cmd do not expand * themselves: do it here so the same command works everywhere."""
    out = []
    for pattern in patterns:
        out.extend(sorted(glob.glob(pattern)) or [pattern])
    return [p for p in out if not p.endswith("-events.json")]


def qr(query, start, end, step=5):
    url = f"{PROM}/api/v1/query_range?" + urllib.parse.urlencode({"query": query, "start": start, "end": end, "step": step})
    with urllib.request.urlopen(url, timeout=30) as r:
        data = json.load(r)["data"]["result"]
    out = []
    for series in data:
        pts = [(float(t), float(v)) for t, v in series["values"] if v not in ("NaN", "+Inf", "-Inf")]
        out.append((series["metric"], pts))
    return out


def expected(tag):
    if "baseline" in tag:
        return {"A": 100, "B": 0, "C": 0}
    if "weighted" in tag:
        return {"A": 50, "B": 25, "C": 25}
    return {"A": 100 / 3, "B": 100 / 3, "C": 100 / 3}


def plot_series(ax, series, t0, label_keys=("replica",), ylabel="", ylim0=True):
    for metric, pts in sorted(series, key=lambda s: s[0].get("replica", "")):
        rep = metric.get("replica", "")
        label = " ".join(metric.get(k, "") for k in label_keys).strip() or "total"
        ax.plot([t - t0 for t, _ in pts], [v for _, v in pts], label=label, color=COLORS.get(rep), linewidth=1.8)
    ax.set_ylabel(ylabel)
    if ylim0:
        ax.set_ylim(bottom=0)
    ax.grid(alpha=0.3)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=7, loc="best")


def draw(path):
    res = json.load(open(path))
    tag, op = res["tag"], res["op"]
    cnt, inprog, dur, err, cluster = M[op]
    t0, t1 = res["start_epoch"], res["finished_epoch"]
    start, end = t0 - 20, t1 + 40
    events = None
    ev_path = path.replace(".json", "-events.json")
    if os.path.exists(ev_path):
        events = json.load(open(ev_path))

    fig, axes = plt.subplots(2, 3, figsize=(17, 8.5))
    ax = axes.flat
    rate = f"sum by (replica) (rate({cnt}[1m]))"
    plot_series(ax[0], qr(rate, start, end), t0, ylabel="requests / s")
    ax[0].set_title("Request rate per replica (1m window)")

    plot_series(ax[1], qr(f"100 * {rate} / scalar(sum(rate({cnt}[1m])))", start, end), t0, ylabel="% of total traffic")
    for rep, val in expected(tag).items():
        ax[1].axhline(val, color=COLORS[rep], linestyle="--", linewidth=0.9, alpha=0.6)
    ax[1].set_ylim(0, 105)
    ax[1].set_title("Share of traffic (dashed = expected)")

    plot_series(ax[2], qr(f"sum by (replica) ({inprog})", start, end), t0, ylabel="active requests")
    ax[2].set_title("Active requests per replica (5 s samples)")

    plot_series(ax[3], qr(f"histogram_quantile(0.95, sum by (le, replica) (rate({dur}_bucket[1m])))", start, end), t0,
                ylabel="seconds")
    ax[3].set_title("p95 server-side latency (1m window)")

    plot_series(ax[4], qr(f"sum by (replica, status) (rate({cnt}{{{err}}}[1m]))", start, end), t0,
                label_keys=("replica", "status"), ylabel="errors / s")
    ax[4].set_title("Errors reaching a replica, by status")

    plot_series(ax[5], qr(f'envoy_cluster_membership_healthy{{envoy_cluster_name="{cluster}"}}', start, end), t0,
                label_keys=("envoy_cluster_name",), ylabel="healthy replicas")
    ax[5].set_ylim(0, 3.5)
    ax[5].set_title(f"Envoy: healthy members of {cluster}")

    for a in ax:
        a.axvspan(0, res["duration_s"], color="grey", alpha=0.07)
        a.set_xlabel("seconds since the client started sending")
        if events:
            a.axvline(events["stop_epoch"] - t0, color="red", linestyle=":", linewidth=1.5)
            a.axvline(events["start_epoch"] - t0, color="green", linestyle=":", linewidth=1.5)
    sub = (f"target {res['target_rps']:g} rps x {res['duration_s']:g}s, sent {res['sent']}, ok {res['successes']}, "
           f"failed {res['failures']}, client p95 {res['client_p95_ms']} ms")
    if events:
        sub += "   |  red = docker stop B, green = docker start B"
    fig.suptitle(f"{tag}  ({op})\n{sub}", fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    os.makedirs(OUT, exist_ok=True)
    out = os.path.join(OUT, f"{tag}.png")
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print("wrote", out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", nargs="+")
    paths = expand(ap.parse_args().results)
    if not paths or not all(os.path.exists(p) for p in paths):
        raise SystemExit("no result files found: run experiments/a3/run_all.py (or loadgen.py) first")
    for p in paths:
        draw(p)


if __name__ == "__main__":
    main()
