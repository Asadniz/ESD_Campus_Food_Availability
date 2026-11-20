#!/bin/sh
# Add (or remove) a fixed delay on ONE replica, for both HTTP and gRPC.
#   scripts/replica-delay.sh B 200     # replica B answers 200 ms slower
#   scripts/replica-delay.sh B 0       # back to normal
set -e
case "$1" in A|a) idx=1;; B|b) idx=2;; C|c) idx=3;; D|d) idx=4;; *) echo "usage: $0 A|B|C|D <ms>"; exit 2;; esac
docker compose exec -T --index "$idx" app python -m campus_api.faultctl "${2:?delay in ms}"
