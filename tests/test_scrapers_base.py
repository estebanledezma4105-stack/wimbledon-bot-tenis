import time
import pytest
from unittest.mock import patch
from scrapers import base

def test_jittered_sleep_within_bounds():
    with patch("time.sleep") as mock_sleep:
        base.jittered_sleep(min_seconds=1.5, max_seconds=4.2)
    args, _ = mock_sleep.call_args
    assert 1.5 <= args[0] <= 4.2

def test_log_scraper_run_writes_row(tmp_path):
    import db
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    base.log_scraper_run(db_path, source="rankings", status="success", rows_fetched=50)
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM scraper_runs WHERE source = ?", ("rankings",)).fetchone()
    assert row["status"] == "success"
    assert row["rows_fetched"] == 50

def test_fetch_with_retry_retries_on_failure():
    call_count = {"n": 0}

    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise ConnectionError("boom")
        return "ok"

    with patch("time.sleep"):
        result = base.fetch_with_retry(flaky, max_attempts=3)
    assert result == "ok"
    assert call_count["n"] == 2
