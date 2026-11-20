"""Container entrypoint for Assignment 3: one container = one replica = HTTP server + gRPC server.

Compose scaling (`docker compose up -d --scale app=3`) names the containers campus-food-app-1, -2, -3.
This launcher turns that index into the replica ID used in logs, metrics labels and response headers:
1 -> A, 2 -> B, 3 -> C. The index is found by reverse DNS on the container's own IP (Docker's embedded
DNS answers with "campus-food-app-2.campus-food_default"). Set REPLICA_ID yourself to skip all this.

If either server process exits, the other is stopped and the container exits, so Docker restarts the whole
replica and Envoy never sees a half-alive replica (HTTP up, gRPC dead).
"""
import os
import re
import signal
import socket
import subprocess
import sys
import time

_INDEX = re.compile(r"-(\d+)(?:\.|$)")


def replica_from_name(name: str) -> str | None:
    """'campus-food-app-2.campus-food_default' -> 'B'. None if the name has no index."""
    match = _INDEX.search(name.split(".")[0] + ".")
    if not match:
        return None
    n = int(match.group(1))
    return chr(ord("A") + n - 1) if 1 <= n <= 26 else str(n)


def resolve_replica_id() -> str:
    if os.getenv("REPLICA_ID"):
        return os.environ["REPLICA_ID"]
    try:
        ip = socket.gethostbyname(socket.gethostname())
        found = replica_from_name(socket.gethostbyaddr(ip)[0])
        if found:
            return found
    except OSError:
        pass
    return socket.gethostname()  # last resort: still unique, just not a letter


def main() -> int:
    replica = resolve_replica_id()
    env = {**os.environ, "REPLICA_ID": replica,
           "SERVICE_NAME": os.getenv("SERVICE_NAME", "campus-food-app")}
    print(f'{{"event":"launcher","replica":"{replica}","message":"starting http and grpc"}}', flush=True)
    procs = [
        subprocess.Popen([sys.executable, "-m", "campus_api.main"], env=env),
        subprocess.Popen([sys.executable, "-m", "campus_api.grpc_server"], env=env),
    ]

    def stop(*_):
        for p in procs:
            if p.poll() is None:
                p.terminate()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while all(p.poll() is None for p in procs):
        time.sleep(0.5)
    stop()
    for p in procs:
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            p.kill()
    return next((p.returncode for p in procs if p.returncode), 0)


if __name__ == "__main__":
    sys.exit(main())
