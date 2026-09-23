"""Read endpoints: which eateries exist and what is on today's menu."""
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from .. import db
from ..faults import faults
from ..observability.logs import log_event
from ..observability.metrics import MENU_VIEWS

router = APIRouter(prefix="/eateries", tags=["eateries"])
logger = logging.getLogger("campus.eateries")


@router.get("")
def list_eateries():
    with db.session() as conn:
        rows = conn.execute("SELECT id, name, slug, location FROM eateries ORDER BY id").fetchall()
    return [dict(r) for r in rows]


@router.get("/{eatery_id}/menu")
def get_menu(eatery_id: int):
    delay = faults.menu_delay_seconds()
    if delay:
        log_event(logger, logging.WARNING, "fault_injected", "artificial delay added to menu request",
                  delay_ms=int(delay * 1000))
        time.sleep(delay)

    with db.session() as conn:
        eatery = conn.execute("SELECT id, name, slug, location FROM eateries WHERE id = ?", (eatery_id,)).fetchone()
        if not eatery:
            raise HTTPException(status_code=404, detail="eatery not found")
        items = conn.execute(
            "SELECT id, name, category, price_pkr, portions_left, available FROM menu_items "
            "WHERE eatery_id = ? ORDER BY id", (eatery_id,),
        ).fetchall()

    MENU_VIEWS.labels(eatery["slug"]).inc()
    return {
        "eatery": dict(eatery),
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "items": [
            {**dict(i), "available": bool(i["available"] and i["portions_left"] > 0)} for i in items
        ],
    }
