"""In-memory sliding-window rate limiter (single instance only: state is lost on restart and not shared)."""
import logging
import math
import os
import threading
import time
from collections import defaultdict, deque

from fastapi import Request

from .errors import ApiError
from .observability.logs import log_event

logger = logging.getLogger("campus.ratelimit")


class SlidingWindowLimiter:
    def __init__(self, max_calls: int, window_seconds: float):
        self.configure(max_calls, window_seconds)
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def configure(self, max_calls: int, window_seconds: float) -> None:
        self.max_calls = max_calls
        self.window = window_seconds

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def __call__(self, request: Request) -> None:  # used as a FastAPI dependency
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] >= self.window:   # forget calls older than the window
                hits.popleft()
            if len(hits) < self.max_calls:
                hits.append(now)                            # rejected calls are NOT recorded
                return
            retry_after = max(1, math.ceil(self.window - (now - hits[0])))
        log_event(logger, logging.WARNING, "rate_limited", f"rate limit hit, retry in {retry_after}s",
                  client=client, retry_after=retry_after)
        raise ApiError(429, "RATE_LIMITED", f"too many requests, retry in {retry_after}s",
                       headers={"Retry-After": str(retry_after)})


hold_limiter = SlidingWindowLimiter(
    max_calls=int(os.getenv("HOLD_RATE_LIMIT", "5")),
    window_seconds=float(os.getenv("HOLD_RATE_WINDOW_SECONDS", "10")),
)