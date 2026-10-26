"""Hold creation: the business rules, shared by the HTTP route and the gRPC service.

Nothing in this file knows about HTTP or gRPC. It reads and writes the one SQLite database and
raises HoldError with a stable `code`. Each transport translates that code into its own status
(see STATUS MAP in docs/A2_REPORT.md):

    code                        HTTP    gRPC
    ITEM_NOT_FOUND              404     NOT_FOUND
    ITEM_SOLD_OUT               409     FAILED_PRECONDITION
    IDEMPOTENCY_KEY_REUSED      422     INVALID_ARGUMENT
"""
import hashlib
import json
import logging
import secrets
import time

from . import db
from .faults import faults
from .observability.logs import log_event
from .observability.metrics import HOLD_CREATION, HOLD_REPLAYS, HOLDS_PLACED, HOLDS_REJECTED
from .schemas import HoldCreate

logger = logging.getLogger("campus.holds")

_CODES = {"item_not_found": "ITEM_NOT_FOUND", "sold_out": "ITEM_SOLD_OUT"}


class HoldError(Exception):
    """A business-rule failure. `code` is the same stable name the HTTP error envelope uses."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def public_hold(row) -> dict:
    return {
        "id": row["id"], "item_id": row["item_id"], "eatery": row["eatery"],
        "pickup_code": row["pickup_code"], "status": row["status"],
        "planned_pickup_minutes": row["planned_pickup_minutes"],
    }


def fetch_hold(conn, hold_id: int):
    """The hold row joined with its eatery slug, or None."""
    return conn.execute(
        "SELECT h.*, e.slug AS eatery FROM holds h JOIN eateries e ON e.id = h.eatery_id WHERE h.id = ?",
        (hold_id,),
    ).fetchone()


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
        raise HoldError("IDEMPOTENCY_KEY_REUSED",
                        "Idempotency-Key was already used with a different request body")
    return json.loads(row["response_body"])


def _reject(reason: str, message: str, **fields):
    HOLDS_REJECTED.labels(reason).inc()
    log_event(logger, logging.WARNING, "hold_rejected", f"hold rejected: {reason}", reason=reason, **fields)
    raise HoldError(_CODES[reason], message)


def _insert_hold(body: HoldCreate, key: str | None):
    """Returns (public_hold, item_row, replayed)."""
    fingerprint = _fingerprint(body)
    with db.session() as conn:
        if key:
            # Take the write lock BEFORE looking the key up. Two simultaneous retries then queue up:
            # the second one waits, sees the committed key, and replays instead of creating a duplicate.
            # The lock is on the database file, so it also covers the HTTP and gRPC processes together.
            conn.execute("BEGIN IMMEDIATE")
            stored = _stored_response(conn, key, fingerprint)
            if stored is not None:
                return stored, None, True

        item = conn.execute(
            "SELECT i.id, i.eatery_id, e.slug AS eatery FROM menu_items i "
            "JOIN eateries e ON e.id = i.eatery_id WHERE i.id = ?", (body.item_id,),
        ).fetchone()
        if not item:
            _reject("item_not_found", "item not found", item_id=body.item_id)

        # Take one portion only if the item is on and still has stock (atomic, no oversell).
        taken = conn.execute(
            "UPDATE menu_items SET portions_left = portions_left - 1 "
            "WHERE id = ? AND available = 1 AND portions_left > 0", (body.item_id,),
        )
        if taken.rowcount == 0:
            _reject("sold_out", "item is sold out", item_id=body.item_id, eatery=item["eatery"])

        code = f"{secrets.randbelow(10000):04d}"
        cur = conn.execute(
            "INSERT INTO holds (item_id, eatery_id, pickup_code, created_at, planned_pickup_minutes, status) "
            "VALUES (?,?,?,?,?, 'active')",
            (item["id"], item["eatery_id"], code, time.time(), body.pickup_in_minutes),
        )
        public = public_hold(fetch_hold(conn, cur.lastrowid))

        if key:  # same transaction as the hold: both are saved, or neither is
            conn.execute(
                "INSERT INTO idempotency_keys (key, request_hash, status_code, response_body, created_at) "
                "VALUES (?,?,?,?,?)", (key, fingerprint, 201, json.dumps(public), time.time()),
            )
    return public, item, False


def create_hold(body: HoldCreate, idempotency_key: str | None = None) -> tuple[dict, bool]:
    """Create a hold. Returns (hold, replayed); replayed is True when an Idempotency-Key matched.

    Raises HoldError for business-rule failures. Callers validate `body` first (HoldCreate).
    """
    with HOLD_CREATION.time():  # Summary: records duration, exposes _sum and _count
        if faults.should_fail_hold():
            raise RuntimeError("injected fault: hold creation failed")
        public, item, replayed = _insert_hold(body, idempotency_key)

    if replayed:
        HOLD_REPLAYS.inc()
        log_event(logger, logging.INFO, "hold_replayed", f"hold {public['id']} returned for repeated key",
                  hold_id=public["id"])
        return public, True

    HOLDS_PLACED.labels(item["eatery"]).inc()
    log_event(logger, logging.INFO, "hold_created", f"hold {public['id']} created",
              hold_id=public["id"], item_id=item["id"], eatery=item["eatery"],
              planned_pickup_minutes=body.pickup_in_minutes)
    return public, False
