"""Holds: the feature that fixes the original problem (food kept aside for 2-3 hours)."""
import logging
import secrets
import time
import hashlib
import json
from fastapi import APIRouter, Depends, Header, Response

from ..ratelimit import hold_limiter
from ..errors import ApiError, error_responses
from ..schemas import HoldCreate, HoldOut
from .. import db
from ..faults import faults
from ..observability.gauges import refresh_gauges
from ..observability.logs import log_event
from ..observability.metrics import (
    HOLD_CREATION, HOLD_PICKUP_DELAY, HOLDS_CLOSED, HOLDS_PLACED, HOLDS_REJECTED,
)
from ..schemas import HoldCreate

router = APIRouter(prefix="/holds", tags=["holds"])
logger = logging.getLogger("campus.holds")

_CODES = {"item_not_found": "ITEM_NOT_FOUND", "sold_out": "ITEM_SOLD_OUT"}

def _fingerprint(body: HoldCreate) -> str:
    """Same body -> same hash, so we can tell a true retry from a reused key."""
    return hashlib.sha256(json.dumps(body.model_dump(), sort_keys=True).encode()).hexdigest()

def _stored_response(conn, key: str, fingerprint: str):
    """Saved response for this key, or None if the key is new."""
    row = conn.execute(
        "SELECT request_hash, response_body FROM idempotency_keys WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return None
    if row["request_hash"] != fingerprint:
        raise ApiError(422, "IDEMPOTENCY_KEY_REUSED",
                       "Idempotency-Key was already used with a different request body")
    return json.loads(row["response_body"])

def _reject(reason: str, status: int, detail: str, **fields):
    HOLDS_REJECTED.labels(reason).inc()
    log_event(logger, logging.WARNING, "hold_rejected", f"hold rejected: {reason}", reason=reason, **fields)
    raise ApiError(status, _CODES[reason], detail)

def _insert_hold(body: HoldCreate, key: str | None):
    """Returns (public_hold, item_row, replayed)."""
    fingerprint = _fingerprint(body)
    with db.session() as conn:
        if key:
            # Take the write lock BEFORE looking the key up. Two simultaneous retries then queue up:
            # the second one waits, sees the committed key, and replays instead of creating a duplicate.
            conn.execute("BEGIN IMMEDIATE")
            stored = _stored_response(conn, key, fingerprint)
            if stored is not None:
                return stored, None, True

        item = conn.execute(
            "SELECT i.id, i.eatery_id, e.slug AS eatery FROM menu_items i "
            "JOIN eateries e ON e.id = i.eatery_id WHERE i.id = ?", (body.item_id,),
        ).fetchone()
        if not item:
            _reject("item_not_found", 404, "item not found", item_id=body.item_id)

        taken = conn.execute(
            "UPDATE menu_items SET portions_left = portions_left - 1 "
            "WHERE id = ? AND available = 1 AND portions_left > 0", (body.item_id,),
        )
        if taken.rowcount == 0:
            _reject("sold_out", 409, "item is sold out", item_id=body.item_id, eatery=item["eatery"])

        code = f"{secrets.randbelow(10000):04d}"
        cur = conn.execute(
            "INSERT INTO holds (item_id, eatery_id, pickup_code, created_at, planned_pickup_minutes, status) "
            "VALUES (?,?,?,?,?, 'active')",
            (item["id"], item["eatery_id"], code, time.time(), body.pickup_in_minutes),
        )
        public = _public(_get_hold(conn, cur.lastrowid))

        if key:  # same transaction as the hold: both are saved, or neither is
            conn.execute(
                "INSERT INTO idempotency_keys (key, request_hash, status_code, response_body, created_at) "
                "VALUES (?,?,?,?,?)", (key, fingerprint, 201, json.dumps(public), time.time()),
            )
    return public, item, False

def _get_hold(conn, hold_id: int):
    row = conn.execute(
        "SELECT h.*, e.slug AS eatery FROM holds h JOIN eateries e ON e.id = h.eatery_id WHERE h.id = ?",
        (hold_id,),
    ).fetchone()
    if not row:
        raise ApiError(404, "HOLD_NOT_FOUND", "hold not found")
    return row


def _public(row) -> dict:
    return {
        "id": row["id"], "item_id": row["item_id"], "eatery": row["eatery"],
        "pickup_code": row["pickup_code"], "status": row["status"],
        "planned_pickup_minutes": row["planned_pickup_minutes"],
    }


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
    with HOLD_CREATION.time():  # Summary: records duration, exposes _sum and _count
        if faults.should_fail_hold():
            raise RuntimeError("injected fault: hold creation failed")
        public, item, replayed = _insert_hold(body, idempotency_key)

    if replayed:
        response.headers["Idempotent-Replayed"] = "true"
        log_event(logger, logging.INFO, "hold_replayed", f"hold {public['id']} returned for repeated key",
                  hold_id=public["id"])
        return public

    HOLDS_PLACED.labels(item["eatery"]).inc()
    refresh_gauges()
    log_event(logger, logging.INFO, "hold_created", f"hold {public['id']} created",
              hold_id=public["id"], item_id=item["id"], eatery=item["eatery"],
              planned_pickup_minutes=body.pickup_in_minutes)
    return public


@router.get("/{hold_id}", response_model=HoldOut, responses=error_responses(404, 422))
def read_hold(hold_id: int):
    with db.session() as conn:
        return _public(_get_hold(conn, hold_id))


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
    return _public(updated)


@router.post("/{hold_id}/cancel", response_model=HoldOut, responses=error_responses(404, 409, 422))
def cancel(hold_id: int):
    updated, _ = _close(hold_id, "cancelled", return_portion=True)
    return _public(updated)
