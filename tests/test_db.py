import os
import sqlite3
import pytest
import db


@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / "test_wimbledon.db")


def test_init_db_creates_all_tables(test_db_path):
    db.init_db(test_db_path)
    conn = sqlite3.connect(test_db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    expected = {
        "players", "player_aliases", "unresolved_names", "h2h",
        "grass_stats", "form", "draw_matches", "live_scores",
        "scraper_runs", "match_stats",
    }
    assert expected.issubset(tables)
    conn.close()
