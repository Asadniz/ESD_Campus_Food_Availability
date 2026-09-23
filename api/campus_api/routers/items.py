"""Item availability: anyone can read it, staff can change it."""
import logging

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..auth import require_staff
from ..observability.gauges import refresh_gauges
from ..observability.logs import log_event
from ..observability.metrics import AVAILABILITY_UPDATES
from ..schemas import AvailabilityUpdate

router = APIRouter(prefix="/items", tags=["items"])
logger = logging.getLogger("campus.items")

_ITEM_SQL = (
    "SELECT i.id, i.name, i.portions_left, i.available, e.slug AS eatery "
    "FROM menu_items i JOIN eateries e ON e.id = i.eatery_id WHERE i.id = ?"
)


def _public(row) -> dict:
    return {
        "id": row["id"], "name": row["name"], "eatery": row["eatery"],
        "portions_left": row["portions_left"],
        "available": bool(row["available"] and row["portions_left"] > 0),
    }


@router.get("/{item_id}")
def get_item(item_id: int):
    with db.session() as conn:
        row = conn.execute(_ITEM_SQL, (item_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="item not found")
    return _public(row)


@router.patch("/{item_id}/availability", dependencies=[Depends(require_staff)])
def set_availability(item_id: int, body: AvailabilityUpdate):
    with db.session() as conn:
        row = conn.execute(_ITEM_SQL, (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="item not found")
        portions = body.portions_left if body.portions_left is not None else row["portions_left"]
        conn.execute("UPDATE menu_items SET available = ?, portions_left = ? WHERE id = ?",
                     (int(body.available), portions, item_id))
        updated = conn.execute(_ITEM_SQL, (item_id,)).fetchone()

    status = "available" if body.available else "sold_out"
    AVAILABILITY_UPDATES.labels(row["eatery"], status).inc()
    refresh_gauges()
    log_event(logger, logging.INFO, "availability_changed", f"item {item_id} marked {status}",
              item_id=item_id, eatery=row["eatery"], new_status=status, portions_left=portions)
    return _public(updated)
