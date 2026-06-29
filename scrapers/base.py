"""Shared scraping utilities: HTTP session, retry/backoff, jitter, run logging."""
import random
import time
from datetime import datetime, timezone

import requests

import db

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
]


def _now():
    return datetime.now(timezone.utc).isoformat()


def get_session():
    session = requests.Session()
    session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
    return session


def jittered_sleep(min_seconds=1.5, max_seconds=4.2):
    time.sleep(random.uniform(min_seconds, max_seconds))


def fetch_with_retry(fn, max_attempts=3, base_delay=1.0):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_error


def log_scraper_run(db_path, source, status, rows_fetched=0, error_message=None, started_at=None):
    started = started_at or _now()
    with db.get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO scraper_runs
               (source, status, rows_fetched, error_message, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source, status, rows_fetched, error_message, started, _now()),
        )
