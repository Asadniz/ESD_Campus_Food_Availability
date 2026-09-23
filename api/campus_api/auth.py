"""Staff key check, shared by the staff and admin routes."""
import logging
import secrets

from fastapi import Header, HTTPException

from . import config
from .observability.logs import log_event
from .observability.metrics import STAFF_AUTH_FAILURES

logger = logging.getLogger("campus.auth")


def require_staff(x_staff_key: str | None = Header(default=None)) -> None:
    if x_staff_key and secrets.compare_digest(x_staff_key, config.STAFF_KEY):
        return
    STAFF_AUTH_FAILURES.inc()
    # Log that it failed, never the key that was sent.
    log_event(logger, logging.WARNING, "staff_auth_failed", "staff key missing or wrong",
              key_supplied=bool(x_staff_key))
    raise HTTPException(status_code=401, detail="staff key required")
