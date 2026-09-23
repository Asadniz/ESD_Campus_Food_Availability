"""Background job: expire forgotten holds and reset the menu once per morning."""
import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import config, db
from .observability.gauges import refresh_gauges
from .observability.logs import log_event, request_id_var
from .observability.metrics import HOLDS_CLOSED, JOB_LAST_RUN

logger = logging.getLogger("campus.jobs")


def expire_stale_holds() -> None:
    cutoff = time.time() - config.HOLD_EXPIRY_SECONDS
    with db.session() as conn:
        stale = conn.execute(
            "SELECT h.id, e.slug AS eatery FROM holds h JOIN eateries e ON e.id = h.eatery_id "
            "WHERE h.status = 'active' AND h.created_at < ?", (cutoff,),
        ).fetchall()
        for row in stale:
            conn.execute("UPDATE holds SET status = 'expired', closed_at = ? WHERE id = ?", (time.time(), row["id"]))
    for row in stale:
        HOLDS_CLOSED.labels(row["eatery"], "expired").inc()
    if stale:
        log_event(logger, logging.WARNING, "holds_expired", f"{len(stale)} holds expired", count=len(stale))
    JOB_LAST_RUN.labels("expire_holds").set(time.time())


def daily_menu_reset() -> None:
    local_now = datetime.now(timezone.utc) + timedelta(hours=config.LOCAL_UTC_OFFSET_HOURS)
    today = local_now.date().isoformat()
    with db.session() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = 'last_reset_date'").fetchone()
        if (row and row["value"] == today) or local_now.hour < config.DAILY_RESET_HOUR:
            JOB_LAST_RUN.labels("daily_reset").set(time.time())
            return
        conn.execute("UPDATE menu_items SET portions_left = default_portions, available = 1")
        conn.execute("INSERT INTO meta (key, value) VALUES ('last_reset_date', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (today,))
    log_event(logger, logging.INFO, "daily_reset", "menu portions reset for the new day", date=today)
    JOB_LAST_RUN.labels("daily_reset").set(time.time())


def run_once() -> None:
    token = request_id_var.set(f"job-{uuid.uuid4().hex[:8]}")  # lets you group one run's logs
    try:
        expire_stale_holds()
        daily_menu_reset()
        refresh_gauges()
    finally:
        request_id_var.reset(token)


async def run_forever() -> None:
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            logger.error("background job failed", exc_info=True, extra={"fields": {"event": "job_failed"}})
        await asyncio.sleep(config.JOB_INTERVAL_SECONDS)
