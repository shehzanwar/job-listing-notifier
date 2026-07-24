import logging

logger = logging.getLogger(__name__)


def check_consecutive_failures(db, company: str, max_failures: int) -> bool:
    """Return True if the last `max_failures` scraper runs for a company all failed."""
    cursor = db.conn.execute(
        """SELECT status FROM scraper_log
           WHERE company = ?
           ORDER BY ran_at DESC
           LIMIT ?""",
        (company, max_failures)
    )
    rows = [row["status"] for row in cursor.fetchall()]
    return len(rows) == max_failures and all(s == "ERROR" for s in rows)
