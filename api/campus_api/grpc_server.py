"""gRPC service for one operation: CreateHold (the same operation as POST /holds).

Runs as its own process/container (`python -m campus_api.grpc_server`). It does not call the HTTP
API. The handler validates with the same HoldCreate model and calls hold_service.create_hold, the
same function the HTTP route calls, against the same SQLite database (shared volume).

Call path:  client -> generated stub -> HTTP/2 -> interceptor -> HoldServicer.CreateHold
            -> hold_service.create_hold -> SQLite
"""
import logging
import signal
import time
import uuid
from concurrent import futures

import grpc
from pydantic import ValidationError

from prometheus_client import REGISTRY, start_http_server

from . import config, db, hold_service
from .hold_service import HoldError
from .observability import metrics
from .observability.logs import log_event, request_id_var, setup_logging
from .rpc import holds_pb2, holds_pb2_grpc
from .schemas import HoldCreate

logger = logging.getLogger("campus.grpc")

MAX_KEY_LENGTH = 128  # same limit as the HTTP Idempotency-Key header
MAX_FAULT_DELAY_MS = 2000

# HoldError.code -> gRPC status. The HTTP route has its own table (routers/holds.py) for the same codes.
_GRPC_STATUS = {
    "ITEM_NOT_FOUND": grpc.StatusCode.NOT_FOUND,                    # HTTP 404
    "ITEM_SOLD_OUT": grpc.StatusCode.FAILED_PRECONDITION,           # HTTP 409
    "IDEMPOTENCY_KEY_REUSED": grpc.StatusCode.INVALID_ARGUMENT,     # HTTP 422
}


class RpcAbort(Exception):
    """Raised by the handler to end the call with a gRPC status. The interceptor turns it into one."""

    def __init__(self, status: grpc.StatusCode, error_code: str, message: str):
        self.status = status
        self.error_code = error_code  # same stable names as the HTTP error envelope's `code`
        self.message = message
        super().__init__(message)


def _inject_delay(context) -> None:
    """Test switch for the in-flight gauge (like A1's /admin/faults): a call that carries the staff key
    in `x-staff-key` and a delay in `x-fault-delay-ms` metadata sleeps that long (capped). Without the
    right key the metadata is ignored, so normal clients cannot slow the service down."""
    metadata = dict(context.invocation_metadata())
    raw = metadata.get("x-fault-delay-ms")
    if not raw or metadata.get("x-staff-key") != config.STAFF_KEY:
        return
    try:
        delay_ms = min(max(int(raw), 0), MAX_FAULT_DELAY_MS)
    except ValueError:
        return
    if delay_ms:
        log_event(logger, logging.WARNING, "fault_injected", f"gRPC delay of {delay_ms} ms injected",
                  delay_ms=delay_ms)
        time.sleep(delay_ms / 1000)


class HoldServicer(holds_pb2_grpc.HoldServiceServicer):
    def CreateHold(self, request, context):
        _inject_delay(context)
        fields = {"item_id": request.item_id}
        if request.HasField("pickup_in_minutes"):  # unset -> the model's default (180), as in HTTP
            fields["pickup_in_minutes"] = request.pickup_in_minutes
        try:
            body = HoldCreate(**fields)
        except ValidationError as exc:
            detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
            raise RpcAbort(grpc.StatusCode.INVALID_ARGUMENT, "VALIDATION_ERROR", detail)

        key = request.idempotency_key or None
        if key and len(key) > MAX_KEY_LENGTH:
            raise RpcAbort(grpc.StatusCode.INVALID_ARGUMENT, "VALIDATION_ERROR",
                           f"idempotency_key: must be at most {MAX_KEY_LENGTH} characters")

        try:
            hold, replayed = hold_service.create_hold(body, key)
        except HoldError as exc:
            raise RpcAbort(_GRPC_STATUS[exc.code], exc.code, exc.message)
        return holds_pb2.CreateHoldResponse(hold=holds_pb2.Hold(**hold), replayed=replayed)


class ObservabilityInterceptor(grpc.ServerInterceptor):
    """The gRPC counterpart of the HTTP middleware. For every call it:

    1. takes the request ID from the `x-request-id` metadata (or makes one) and sets request_id_var,
       so every log line written during the call carries it, and returns it in the initial metadata;
    2. turns RpcAbort into a gRPC status (with the error code in `x-error-code` trailing metadata)
       and any other exception into INTERNAL, logging the stack once;
    3. writes one `grpc_call_completed` log line, the counterpart of `request_completed`;
    4. records the gRPC metrics (calls by method and status, duration, calls in flight). The duration
       is measured here on the server, around the handler, so it leaves out network time and the
       protobuf encoding and decoding that happen outside the interceptor.
    """

    def intercept_service(self, continuation, handler_call_details):
        handler = continuation(handler_call_details)
        if handler is None or handler.unary_unary is None:
            return handler
        method = handler_call_details.method
        short = method.rsplit("/", 1)[-1]  # "CreateHold": a bounded label (one value per RPC in the .proto)
        inner = handler.unary_unary

        def wrapped(request, context):
            metadata = dict(context.invocation_metadata())
            request_id = metadata.get("x-request-id") or uuid.uuid4().hex[:16]
            token = request_id_var.set(request_id)
            started = time.perf_counter()
            status = grpc.StatusCode.OK
            metrics.GRPC_IN_PROGRESS.labels(short).inc()
            try:
                context.send_initial_metadata((("x-request-id", request_id),))
                return inner(request, context)
            except RpcAbort as exc:
                status = exc.status
                context.set_trailing_metadata((("x-error-code", exc.error_code),))
                context.abort(exc.status, exc.message)
            except Exception:
                status = grpc.StatusCode.INTERNAL
                logger.error("unhandled exception", exc_info=True, extra={"fields": {"event": "unhandled_exception"}})
                context.set_trailing_metadata((("x-error-code", "INTERNAL_ERROR"),))
                context.abort(grpc.StatusCode.INTERNAL, "internal server error")
            finally:
                elapsed = time.perf_counter() - started
                metrics.GRPC_IN_PROGRESS.labels(short).dec()
                metrics.GRPC_REQUESTS.labels(short, status.name).inc()
                metrics.GRPC_DURATION.labels(short).observe(elapsed)
                level = (logging.INFO if status == grpc.StatusCode.OK
                         else logging.ERROR if status == grpc.StatusCode.INTERNAL else logging.WARNING)
                log_event(logger, level, "grpc_call_completed", f"{method} -> {status.name}",
                          method=method, grpc_status=status.name,  # not "status": ES maps that field as integer
                          duration_ms=round(elapsed * 1000, 1))
                request_id_var.reset(token)

        return grpc.unary_unary_rpc_method_handler(
            wrapped,
            request_deserializer=handler.request_deserializer,
            response_serializer=handler.response_serializer,
        )


def create_server(address: str = f"[::]:{config.GRPC_PORT}", max_workers: int = 10):
    """Build (not start) the server. Returns (server, bound_port); address ':0' picks a free port."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=max_workers),
                         interceptors=[ObservabilityInterceptor()])
    holds_pb2_grpc.add_HoldServiceServicer_to_server(HoldServicer(), server)
    port = server.add_insecure_port(address)
    return server, port


# Metrics that only the HTTP process records. They would show up here as empty series (or as zero
# gauges) and duplicate the HTTP process's series in Grafana, so this process does not expose them.
_HTTP_PROCESS_ONLY = (
    metrics.HTTP_REQUESTS, metrics.HTTP_DURATION, metrics.HTTP_IN_PROGRESS, metrics.STAFF_AUTH_FAILURES,
    metrics.JOB_LAST_RUN, metrics.MENU_VIEWS, metrics.HOLDS_CLOSED, metrics.AVAILABILITY_UPDATES,
    metrics.ITEMS_AVAILABLE, metrics.ACTIVE_HOLDS, metrics.HOLD_PICKUP_DELAY,
)


def expose_metrics(port: int) -> None:
    """Serve /metrics on its own port: the gRPC port speaks gRPC, not HTTP, so Prometheus cannot scrape it."""
    for collector in _HTTP_PROCESS_ONLY:
        REGISTRY.unregister(collector)
    start_http_server(port)


def main() -> None:
    setup_logging()
    db.init_db()  # creates tables if missing; seeding stays the HTTP API's job
    expose_metrics(config.GRPC_METRICS_PORT)
    server, port = create_server()
    server.start()
    log_event(logger, logging.INFO, "grpc_started", f"campus food gRPC service listening on {port}",
              service=config.SERVICE_NAME, port=port)
    signal.signal(signal.SIGTERM, lambda *_: server.stop(grace=5))
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        server.stop(grace=2)
    log_event(logger, logging.INFO, "grpc_stopped", "campus food gRPC service stopped")


if __name__ == "__main__":
    main()
