"""Screenshot the A3 Grafana dashboard for the exact time range of each run (headless browser).

    pip install playwright && python -m playwright install chromium
    python experiments/a3/grafana_shots.py --password YOURPASSWORD experiments/a3/results/c-rr-http.json
    python experiments/a3/grafana_shots.py --now          # one screenshot of the last 15 minutes

Output: docs/img/a3/<tag>-grafana.png. The time range is [start - 30 s, end + 60 s] of the run, so the chart shows
the quiet period before and after. The dashboard shows both interfaces, so HTTP and gRPC runs of the same stage
give the same view over different windows; use the one whose run you are discussing.

Grafana only draws panels that are inside the browser window, so the window is made taller than the whole dashboard
(--height) and the script waits until the number of drawn panels stops changing. The script logs in with
--user/--password (default admin/admin; or env GRAFANA_PASSWORD). To reset the password to admin:
    docker exec campus-grafana grafana cli admin reset-admin-password admin
"""
import argparse
import glob
import json
import os
import time

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(os.path.join(HERE, "..", "..", "docs", "img", "a3"))
UID = "campus-food-a3-lb"


def expand(patterns):
    """PowerShell/cmd do not expand * themselves: do it here so the same command works everywhere."""
    out = []
    for pattern in patterns:
        out.extend(sorted(glob.glob(pattern)) or [pattern])
    return [p for p in out if not p.endswith("-events.json")]


def drawn_panels(page):
    # time-series panels are drawn on <canvas>; panels without data say "No data"
    return page.locator("canvas").count() + page.get_by_text("No data").count()


def wait_for_panels(page, timeout=45):
    """Wait until the number of drawn panels has stayed the same for 4 seconds in a row."""
    deadline, last, stable = time.time() + timeout, -1, 0
    while time.time() < deadline:
        n = drawn_panels(page)
        stable = stable + 1 if (n == last and n >= 6) else 0
        last = n
        if stable >= 4:
            break
        page.wait_for_timeout(1000)
    return last


def shoot(page, url, out, wait):
    page.goto(url, wait_until="domcontentloaded")
    if "/login" in page.url:
        raise SystemExit("Grafana is showing its login page: the session was not accepted (wrong --password?)")
    n = wait_for_panels(page)
    page.wait_for_timeout(int(wait * 1000))
    page.screenshot(path=out, full_page=True)
    print(f"wrote {out}  ({n} panels drawn{'  WARNING: few panels, retry with --wait 10' if n < 12 else ''})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", nargs="*")
    ap.add_argument("--now", action="store_true")
    ap.add_argument("--grafana", default="http://localhost:3001")
    ap.add_argument("--user", default=os.environ.get("GRAFANA_USER", "admin"))
    ap.add_argument("--password", default=os.environ.get("GRAFANA_PASSWORD", "admin"),
                    help="the password you log in to Grafana with (also: env GRAFANA_PASSWORD)")
    ap.add_argument("--wait", type=float, default=3, help="extra seconds after the panels have drawn")
    ap.add_argument("--height", type=int, default=2600, help="browser window height; must exceed the dashboard height")
    args = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1700, "height": args.height})
        login = ctx.request.post(f"{args.grafana}/login", data={"user": args.user, "password": args.password})
        if not login.ok:
            raise SystemExit(f"Grafana rejected the login for user '{args.user}' (HTTP {login.status}). "
                             "Pass your real password: --password <it>  (or reset it, see below)\n"
                             "  reset to admin:  docker exec campus-grafana grafana cli admin reset-admin-password admin")
        page = ctx.new_page()
        # refresh=1d: no 5 s auto-refresh while the picture is taken (the time range is fixed anyway)
        base = f"{args.grafana}/d/{UID}/a3-load-balancing?orgId=1&kiosk&refresh=1d"
        if args.now:
            shoot(page, base + "&from=now-15m&to=now", os.path.join(OUT, "dashboard-now.png"), args.wait)
        for path in expand(args.results):
            res = json.load(open(path))
            frm = int((res["start_epoch"] - 30) * 1000)
            to = int((res["finished_epoch"] + 60) * 1000)
            shoot(page, f"{base}&from={frm}&to={to}", os.path.join(OUT, f"{res['tag']}-grafana.png"), args.wait)
        browser.close()


if __name__ == "__main__":
    main()
