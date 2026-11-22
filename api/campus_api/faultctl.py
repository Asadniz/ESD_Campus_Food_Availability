"""Set or clear a fixed delay on THIS replica (Assignment 3, experiment "least request").

Run it inside the replica you want to slow down, e.g. replica B (index 2):
    docker compose exec --index 2 app python -m campus_api.faultctl 200     # +200 ms
    docker compose exec --index 2 app python -m campus_api.faultctl 0       # back to normal
(scripts/replica-delay.sh B 200 wraps this.)

HTTP: uses the existing staff-key protected /admin/faults (every GET /eateries/{id}/menu sleeps).
gRPC: writes the delay file that the gRPC process checks on every CreateHold.
"""
import json
import os
import sys
import urllib.request

from . import config
from .launcher import resolve_replica_id


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1].isdigit():
        print(__doc__)
        return 2
    ms = int(sys.argv[1])
    http = "http://127.0.0.1:8000/admin/faults"
    headers = {"X-Staff-Key": config.STAFF_KEY, "Content-Type": "application/json"}
    if ms:
        req = urllib.request.Request(http, method="POST", headers=headers,
                                     data=json.dumps({"menu_delay_ms": ms, "menu_delay_every_nth": 1}).encode())
        with open(config.GRPC_DELAY_FILE, "w") as f:
            f.write(str(ms))
    else:
        req = urllib.request.Request(http, method="DELETE", headers=headers)
        try:
            os.remove(config.GRPC_DELAY_FILE)
        except FileNotFoundError:
            pass
    with urllib.request.urlopen(req, timeout=5) as resp:
        print(f"replica {resolve_replica_id()}: delay={ms} ms, http answered {resp.status}: {resp.read().decode()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
