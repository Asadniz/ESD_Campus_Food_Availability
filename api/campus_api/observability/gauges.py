"""Gauges are recomputed from the database, so they can never drift from reality."""
from .. import db
from .metrics import ACTIVE_HOLDS, ITEMS_AVAILABLE


def refresh_gauges() -> None:
    with db.session() as conn:
        available = conn.execute(
            "SELECT e.slug, COUNT(CASE WHEN i.available = 1 AND i.portions_left > 0 THEN 1 END) AS n "
            "FROM eateries e LEFT JOIN menu_items i ON i.eatery_id = e.id GROUP BY e.id"
        ).fetchall()
        holds = conn.execute(
            "SELECT e.slug, COUNT(CASE WHEN h.status = 'active' THEN 1 END) AS n "
            "FROM eateries e LEFT JOIN holds h ON h.eatery_id = e.id GROUP BY e.id"
        ).fetchall()
    for row in available:
        ITEMS_AVAILABLE.labels(row["slug"]).set(row["n"])
    for row in holds:
        ACTIVE_HOLDS.labels(row["slug"]).set(row["n"])
