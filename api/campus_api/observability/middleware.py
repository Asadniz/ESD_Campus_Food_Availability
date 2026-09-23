"""One middleware does three jobs for every request:
1. assigns a request ID (or reuses X-Request-ID) and returns it in the response,
2. records the HTTP metrics,
3. writes one `request_completed` log line.
"""
import logging
import time
import uuid

from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from .logs import log_event, request_id_var
from .metrics import HTTP_DURATION, HTTP_IN_PROGRESS, HTTP_REQUESTS

logger = logging.getLogger("campus.http")
SKIP_PATHS = {"/metrics"}  # Prometheus scrapes would drown the real traffic


class ObservabilityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        if request.url.path in SKIP_PATHS:
            return await call_next(request)

        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        HTTP_IN_PROGRESS.inc()
        try:
            try:
                response = await call_next(request)
            except Exception:
                # Unhandled error in a route: log the stack once, answer with a clean 500.
                logger.error("unhandled exception", exc_info=True, extra={"fields": {"event": "unhandled_exception"}})
                response = JSONResponse({"detail": "internal error"}, status_code=500)
            response.headers["X-Request-ID"] = request_id

            # Use the route template (/eateries/{eatery_id}/menu), never the raw path.
            # Raw paths contain IDs and would create one time series per ID.
            route = request.scope.get("route")
            route_path = route.path if route else "unmatched"
            elapsed = time.perf_counter() - started

            HTTP_REQUESTS.labels(request.method, route_path, str(response.status_code)).inc()
            HTTP_DURATION.labels(request.method, route_path).observe(elapsed)

            level = logging.INFO if response.status_code < 400 else logging.WARNING if response.status_code < 500 else logging.ERROR
            log_event(
                logger, level, "request_completed",
                f"{request.method} {route_path} -> {response.status_code}",
                method=request.method, path=request.url.path, route=route_path,
                status=response.status_code, duration_ms=round(elapsed * 1000, 1),
            )
            return response
        finally:
            HTTP_IN_PROGRESS.dec()
            request_id_var.reset(token)
