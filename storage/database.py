import sqlite3
import json
from datetime import datetime, timedelta


class JobDatabase:
    def __init__(self, db_path: str = "jobs.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS raw_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_id TEXT NOT NULL,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                location TEXT,
                url TEXT,
                posted_date TEXT,
                description TEXT,
                department TEXT,
                raw_json TEXT,
                scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                filtered INTEGER DEFAULT 0,
                UNIQUE(company, req_id)
            );

            CREATE TABLE IF NOT EXISTS filtered_listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_id INTEGER REFERENCES raw_listings(id),
                req_id TEXT NOT NULL,
                company TEXT NOT NULL,
                title TEXT NOT NULL,
                location TEXT,
                url TEXT,
                verdict TEXT,          -- PASS / FLAG / REJECT
                fit_score INTEGER,
                effective_level TEXT,
                clearance_needed TEXT,
                clearance_sponsorable TEXT,
                is_data_role INTEGER,
                red_flags TEXT,        -- JSON array
                one_line_reason TEXT,
                llm_thinking_used INTEGER DEFAULT 0,
                notified INTEGER DEFAULT 0,
                filtered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(company, req_id)
            );

            CREATE TABLE IF NOT EXISTS scraper_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT,
                query TEXT,
                jobs_found INTEGER,
                status TEXT,           -- SUCCESS / ERROR
                error_message TEXT,
                duration_seconds REAL,
                ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS llm_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                req_id TEXT,
                company TEXT,
                verdict TEXT,
                fit_score INTEGER,
                thinking_used INTEGER,
                inference_seconds REAL,
                ran_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_raw_filtered
                ON raw_listings(filtered);
            CREATE INDEX IF NOT EXISTS idx_raw_company_req
                ON raw_listings(company, req_id);
            CREATE INDEX IF NOT EXISTS idx_filtered_verdict
                ON filtered_listings(verdict);
        """)
        self.conn.commit()

    def insert_raw_listing(self, job) -> bool:
        """Insert a raw listing. Returns False if already exists (dedup)."""
        try:
            self.conn.execute(
                """INSERT INTO raw_listings
                   (req_id, company, title, location, url, posted_date,
                    description, department, raw_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (job.req_id, job.company, job.title, job.location,
                 job.url, job.posted_date, job.description,
                 getattr(job, 'department', ''),
                 json.dumps(job.raw_json) if job.raw_json else None)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # Already seen

    def get_unfiltered_listings(self) -> list:
        """Get all listings that haven't been through the filter pipeline."""
        cursor = self.conn.execute(
            "SELECT * FROM raw_listings WHERE filtered = 0 ORDER BY scraped_at"
        )
        return [dict(row) for row in cursor.fetchall()]

    def mark_filtered(self, raw_id: int, result: dict):
        """Mark a listing as filtered and store the LLM result."""
        self.conn.execute(
            "UPDATE raw_listings SET filtered = 1 WHERE id = ?", (raw_id,)
        )
        self.conn.execute(
            """INSERT OR REPLACE INTO filtered_listings
               (raw_id, req_id, company, title, location, url,
                verdict, fit_score, effective_level, clearance_needed,
                clearance_sponsorable, is_data_role, red_flags,
                one_line_reason, llm_thinking_used)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (raw_id, result.get("req_id"), result.get("company"),
             result.get("title"), result.get("location"), result.get("url"),
             result.get("verdict"), result.get("fit_score"),
             result.get("effective_level"), result.get("clearance_needed"),
             str(result.get("clearance_sponsorable")),
             result.get("is_data_role"),
             json.dumps(result.get("red_flags", [])),
             result.get("one_line_reason"),
             result.get("thinking_used", 0))
        )
        self.conn.commit()

    def get_weekly_pass_flag(self, days: int = 7) -> list:
        """Get all PASS/FLAG listings from the past N days for digest."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = self.conn.execute(
            """SELECT * FROM filtered_listings
               WHERE verdict IN ('PASS', 'FLAG')
               AND filtered_at > ?
               ORDER BY fit_score DESC""",
            (cutoff,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def log_scraper_run(self, company: str, query: str,
                         jobs_found: int, status: str,
                         error: str = None, duration: float = 0):
        self.conn.execute(
            """INSERT INTO scraper_log
               (company, query, jobs_found, status, error_message, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (company, query, jobs_found, status, error, duration)
        )
        self.conn.commit()
