"""One error shape for the whole API: {"error": {"code", "message", "request_id", "details"?}}."""
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .observability.logs import log_event, request_id_var
from .schemas import ErrorResponse

logger = logging.getLogger("campus.errors")


class ApiError(Exception):
    """Raise this from routes instead of HTTPException. `code` is a stable machine-readable name."""

    def __init__(self, status: int, code: str, message: str, headers: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers
        super().__init__(message)


# Fallback codes for plain HTTPExceptions (401/403 from auth, unknown routes, wrong method...).
_STATUS_CODES = {
    400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED", 409: "CONFLICT", 422: "VALIDATION_ERROR",
    429: "RATE_LIMITED", 500: "INTERNAL_ERROR", 503: "SERVICE_UNAVAILABLE",
}


def _envelope(status: int, code: str, message: str, headers=None, details=None) -> JSONResponse:
    error = {"code": code, "message": message, "request_id": request_id_var.get()}
    if details:
        error["details"] = details
    return JSONResponse(status_code=status, content={"error": error}, headers=headers)


async def _api_error(_: Request, exc: ApiError):
    return _envelope(exc.status, exc.code, exc.message, exc.headers)


async def _http_error(_: Request, exc: StarletteHTTPException):
    code = _STATUS_CODES.get(exc.status_code, "HTTP_ERROR")
    return _envelope(exc.status_code, code, str(exc.detail), getattr(exc, "headers", None))


async def _validation_error(_: Request, exc: RequestValidationError):
    details = [
        {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
        for e in exc.errors()
    ]
    return _envelope(422, "VALIDATION_ERROR", "request validation failed", details=details)


async def _unhandled(_: Request, exc: Exception):
    # Details stay in the logs; the client only gets a generic message.
    log_event(logger, logging.ERROR, "unhandled_exception", f"unhandled error: {type(exc).__name__}")
    return _envelope(500, "INTERNAL_ERROR", "internal server error")


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ApiError, _api_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)  # Starlette's class also catches 404/405
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled)


# Reusable for `responses=` on routes so the OpenAPI spec documents the error shape.
def error_responses(*statuses: int) -> dict:
    return {s: {"model": ErrorResponse, "description": _STATUS_CODES.get(s, "Error")} for s in statuses}