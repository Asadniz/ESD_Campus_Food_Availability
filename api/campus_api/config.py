"""All settings in one place. Everything can be overridden with environment variables."""
import os

SERVICE_NAME = os.getenv("SERVICE_NAME", "campus-food-api")
# Which replica this is (A, B, C...). The launcher sets it for every container; "single" when the app
# is run on its own (tests, python -m campus_api.main).
REPLICA_ID = os.getenv("REPLICA_ID", "single")
# Per-replica gRPC delay switch (Assignment 3 experiments): if this file exists and holds a number,
# every CreateHold on this replica sleeps that many ms. Written by campus_api.faultctl.
GRPC_DELAY_FILE = os.getenv("GRPC_DELAY_FILE", "/tmp/grpc_delay_ms")
DB_PATH = os.getenv("DB_PATH", "/data/campus.db")

# Staff endpoints (availability updates, fault injection) need this header value.
# Demo default only. It must never appear in logs.
STAFF_KEY = os.getenv("STAFF_KEY", "staff-demo-key")

# A hold that nobody picks up for this long is marked expired by the background job.
HOLD_EXPIRY_SECONDS = int(os.getenv("HOLD_EXPIRY_SECONDS", str(6 * 3600)))

# How often the background job runs, and when the daily menu reset happens.
JOB_INTERVAL_SECONDS = int(os.getenv("JOB_INTERVAL_SECONDS", "30"))
DAILY_RESET_HOUR = int(os.getenv("DAILY_RESET_HOUR", "6"))
LOCAL_UTC_OFFSET_HOURS = int(os.getenv("LOCAL_UTC_OFFSET_HOURS", "5"))  # Karachi

# Port of the gRPC service (grpc_server.py), which runs as its own process.
GRPC_PORT = int(os.getenv("GRPC_PORT", "50051"))
# Where the gRPC process serves /metrics for Prometheus (the gRPC port itself is not HTTP).
GRPC_METRICS_PORT = int(os.getenv("GRPC_METRICS_PORT", "9102"))
