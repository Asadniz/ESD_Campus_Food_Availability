"""Holds: the feature that fixes the original problem (food kept aside for 2-3 hours).

POST /holds is a thin HTTP layer: rate limit, header parsing, status mapping. The rules live in
hold_service.py, which the gRPC service (grpc_server.py) calls too.
"""
import logging
import time

from fastapi import APIRouter, Depends, Header, Response

from .. import db
from ..errors import ApiError, error_responses
from ..hold_service import HoldError, create_hold as create_hold_record, fetch_hold, public_hold
from ..observability.gauges import refresh_gauges
from ..observability.logs import log_event
from ..observability.metrics import HOLD_PICKUP_DELAY, HOLDS_CLOSED
from ..ratelimit import hold_limiter
from ..schemas import HoldCreate, HoldOut

router = APIRouter(prefix="/holds", tags=["holds"])
logger = logging.getLogger("campus.holds")

# HoldError.code -> HTTP status. The gRPC service has its own table for the same codes.
_HTTP_STATUS = {"ITEM_NOT_FOUND": 404, "ITEM_SOLD_OUT": 409, "IDEMPOTENCY_KEY_REUSED": 422}


def _get_hold(conn, hold_id: int):
    row = fetch_hold(conn, hold_id)
    if not row:
        raise ApiError(404, "HOLD_NOT_FOUND", "hold not found")
    return row


@router.post("", status_code=201, response_model=HoldOut,
             dependencies=[Depends(hold_limiter)],
             responses=error_responses(404, 409, 422, 429))
def create_hold(
    body: HoldCreate,
    response: Response,
    idempotency_key: str | None = Header(default=None, min_length=1, max_length=128,
                                         description="Client-generated unique key. Repeating the same key "
                                                     "with the same body returns the original hold."),
):
    try:
        public, replayed = create_hold_record(body, idempotency_key)
    except HoldError as exc:
        raise ApiError(_HTTP_STATUS[exc.code], exc.code, exc.message)

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
    else:
        refresh_gauges()
    return public


@router.get("/{hold_id}", response_model=HoldOut, responses=error_responses(404, 422))
def read_hold(hold_id: int):
    with db.session() as conn:
        return public_hold(_get_hold(conn, hold_id))


def _close(hold_id: int, new_status: str, return_portion: bool):
    with db.session() as conn:
        hold = _get_hold(conn, hold_id)
        if hold["status"] != "active":
            raise ApiError(409, "HOLD_NOT_ACTIVE", f"hold is already {hold['status']}")
        now = time.time()
        conn.execute("UPDATE holds SET status = ?, closed_at = ? WHERE id = ?", (new_status, now, hold_id))
        if return_portion:
            conn.execute("UPDATE menu_items SET portions_left = portions_left + 1 WHERE id = ?", (hold["item_id"],))
        updated = _get_hold(conn, hold_id)

    HOLDS_CLOSED.labels(hold["eatery"], new_status).inc()
    refresh_gauges()
    waited = now - hold["created_at"]
    log_event(logger, logging.INFO, f"hold_{new_status}", f"hold {hold_id} {new_status}",
              hold_id=hold_id, eatery=hold["eatery"], waited_seconds=round(waited))
    return updated, waited


@router.post("/{hold_id}/pickup", response_model=HoldOut, responses=error_responses(404, 409, 422))
def pick_up(hold_id: int):
    updated, waited = _close(hold_id, "picked_up", return_portion=False)
    HOLD_PICKUP_DELAY.observe(waited)
    return public_hold(updated)


@router.post("/{hold_id}/cancel", response_model=HoldOut, responses=error_responses(404, 409, 422))
def cancel(hold_id: int):
    updated, _ = _close(hold_id, "cancelled", return_portion=True)
    return public_hold(updated)
