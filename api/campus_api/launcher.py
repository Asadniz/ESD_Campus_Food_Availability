"""Container entrypoint for Assignment 3: one container = one replica = HTTP server + gRPC server.

Compose scaling (`docker compose up -d --scale app=3`) names the containers campus-food-app-1, -2, -3.
This launcher turns that index into the replica ID used in logs, metrics labels and response headers:
1 -> A, 2 -> B, 3 -> C. The index is found by asking Docker's DNS which of the names campus-food-app-1, -2, ...
resolves to this container's own IP (the same names Envoy and Prometheus use to reach the replicas). Reverse
DNS is only a second attempt: some Docker setups answer it with the container id. Set REPLICA_ID yourself to
skip all this; REPLICA_NAME_PREFIX changes the container name prefix if your Compose project is named differently.

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


def replica_by_forward_dns(own_ip: str, prefix: str, resolve=socket.gethostbyname, limit: int = 26) -> str | None:
    """Which of prefix1, prefix2, ... resolves to our own IP? 'campus-food-app-' + 2 -> 'B'."""
    for n in range(1, limit + 1):
        try:
            if resolve(f"{prefix}{n}") == own_ip:
                return chr(ord("A") + n - 1)
        except OSError:          # name does not exist (yet): try the next index
            continue
    return None


def resolve_replica_id() -> str:
    if os.getenv("REPLICA_ID"):
        return os.environ["REPLICA_ID"]
    prefix = os.getenv("REPLICA_NAME_PREFIX", "campus-food-app-")
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        return socket.gethostname()
    found = replica_by_forward_dns(ip, prefix)
    if found:
        return found
    try:                          # second attempt: reverse DNS (answers differ between Docker setups)
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
