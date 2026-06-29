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


def test_init_db_is_idempotent(test_db_path):
    db.init_db(test_db_path)
    db.init_db(test_db_path)
    conn = sqlite3.connect(test_db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    assert "players" in tables
    conn.close()


def test_upsert_player_creates_new_player(test_db_path):
    db.init_db(test_db_path)
    player_id = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2100, ranking=2)
    with db.get_connection(test_db_path) as conn:
        row = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    assert row["name"] == "Carlos Alcaraz"
    assert row["elo"] == 2100
    assert row["ranking"] == 2


def test_upsert_player_updates_existing_player(test_db_path):
    db.init_db(test_db_path)
    first_id = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2100, ranking=2)
    second_id = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2150, ranking=1)
    assert first_id == second_id
    with db.get_connection(test_db_path) as conn:
        row = conn.execute("SELECT * FROM players WHERE id = ?", (second_id,)).fetchone()
    assert row["elo"] == 2150
    assert row["ranking"] == 1


def test_get_player_by_name_returns_none_if_missing(test_db_path):
    db.init_db(test_db_path)
    assert db.get_player_by_name(test_db_path, "Nobody") is None


def test_upsert_player_preserves_elo_and_ranking_when_omitted(test_db_path):
    """Regression test: a scraper that only knows player identity (e.g. the
    draw scraper resolving names) must not wipe out elo/ranking set earlier
    by the rankings scraper."""
    db.init_db(test_db_path)
    db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2100, ranking=2)
    db.upsert_player(test_db_path, name="Carlos Alcaraz")
    row = db.get_player_by_name(test_db_path, "Carlos Alcaraz")
    assert row["elo"] == 2100
    assert row["ranking"] == 2


def test_upsert_player_defaults_elo_to_1500_for_brand_new_player(test_db_path):
    db.init_db(test_db_path)
    db.upsert_player(test_db_path, name="New Qualifier")
    row = db.get_player_by_name(test_db_path, "New Qualifier")
    assert row["elo"] == 1500
    assert row["ranking"] is None


def test_set_and_get_form_points(test_db_path):
    db.init_db(test_db_path)
    player_id = db.upsert_player(test_db_path, name="Carlos Alcaraz")
    db.set_form_points(test_db_path, player_id, points=4.5)
    points = db.get_form_points(test_db_path, player_id)
    assert points == 4.5


def test_get_form_points_defaults_to_zero_when_missing(test_db_path):
    db.init_db(test_db_path)
    player_id = db.upsert_player(test_db_path, name="Novak Djokovic")
    assert db.get_form_points(test_db_path, player_id) == 0
