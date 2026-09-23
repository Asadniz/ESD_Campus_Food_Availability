"""Holds: the feature that fixes the original problem (food kept aside for 2-3 hours)."""
import logging
import secrets
import time

from fastapi import APIRouter, HTTPException

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


def _reject(reason: str, status: int, detail: str, **fields):
    HOLDS_REJECTED.labels(reason).inc()
    log_event(logger, logging.WARNING, "hold_rejected", f"hold rejected: {reason}", reason=reason, **fields)
    raise HTTPException(status_code=status, detail=detail)


def _get_hold(conn, hold_id: int):
    row = conn.execute(
        "SELECT h.*, e.slug AS eatery FROM holds h JOIN eateries e ON e.id = h.eatery_id WHERE h.id = ?",
        (hold_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="hold not found")
    return row


def _public(row) -> dict:
    return {
        "id": row["id"], "item_id": row["item_id"], "eatery": row["eatery"],
        "pickup_code": row["pickup_code"], "status": row["status"],
        "planned_pickup_minutes": row["planned_pickup_minutes"],
    }


@router.post("", status_code=201)
def create_hold(body: HoldCreate):
    with HOLD_CREATION.time():  # Summary: records duration, exposes _sum and _count
        if faults.should_fail_hold():
            raise RuntimeError("injected fault: hold creation failed")

        with db.session() as conn:
            item = conn.execute(
                "SELECT i.id, i.eatery_id, e.slug AS eatery FROM menu_items i "
                "JOIN eateries e ON e.id = i.eatery_id WHERE i.id = ?", (body.item_id,),
            ).fetchone()
            if not item:
                _reject("item_not_found", 404, "item not found", item_id=body.item_id)

            # Take one portion only if the item is on and still has stock (atomic, no oversell).
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
            hold = _get_hold(conn, cur.lastrowid)

    HOLDS_PLACED.labels(item["eatery"]).inc()
    refresh_gauges()
    log_event(logger, logging.INFO, "hold_created", f"hold {hold['id']} created",
              hold_id=hold["id"], item_id=item["id"], eatery=item["eatery"],
              planned_pickup_minutes=body.pickup_in_minutes)
    return _public(hold)


@router.get("/{hold_id}")
def read_hold(hold_id: int):
    with db.session() as conn:
        return _public(_get_hold(conn, hold_id))


def _close(hold_id: int, new_status: str, return_portion: bool):
    with db.session() as conn:
        hold = _get_hold(conn, hold_id)
        if hold["status"] != "active":
            raise HTTPException(status_code=409, detail=f"hold is already {hold['status']}")
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


@router.post("/{hold_id}/pickup")
def pick_up(hold_id: int):
    updated, waited = _close(hold_id, "picked_up", return_portion=False)
    HOLD_PICKUP_DELAY.observe(waited)
    return _public(updated)


@router.post("/{hold_id}/cancel")
def cancel(hold_id: int):
    updated, _ = _close(hold_id, "cancelled", return_portion=True)
    return _public(updated)
