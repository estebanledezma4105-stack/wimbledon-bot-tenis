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


def test_load_all_data_returns_expected_shape(test_db_path):
    db.init_db(test_db_path)
    p1 = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2100)
    p2 = db.upsert_player(test_db_path, name="Novak Djokovic", elo=2050)
    db.set_form_points(test_db_path, p1, points=3.0)

    data = db.load_all_data(test_db_path)

    assert data["elo"]["Carlos Alcaraz"] == 2100
    assert data["elo"]["Novak Djokovic"] == 2050
    assert data["form"]["Carlos Alcaraz"] == 3.0
    assert "Novak Djokovic" not in data["form"] or data["form"]["Novak Djokovic"] == 0
    assert isinstance(data["grass_stats"], dict)
    assert isinstance(data["h2h"], dict)


def test_load_all_data_includes_scheduled_date_per_match(test_db_path):
    db.init_db(test_db_path)
    p1 = db.upsert_player(test_db_path, name="Carlos Alcaraz")
    p2 = db.upsert_player(test_db_path, name="Novak Djokovic")
    with db.get_connection(test_db_path) as conn:
        conn.execute(
            """INSERT INTO draw_matches (tournament_id, year, round, player1_id, player2_id, scheduled_date)
               VALUES ('wimbledon', 2026, '1R', ?, ?, '2026-06-29')""",
            (p1, p2),
        )

    data = db.load_all_data(test_db_path)
    match = data["draw"]["matches"][0]
    assert match["scheduled_date"] == "2026-06-29"


def test_total_games_played_sums_across_sets_with_tiebreaks():
    assert db._total_games_played("6-3, 7-6(7), 4-6") == 6 + 3 + 7 + 6 + 4 + 6


def test_total_games_played_handles_empty_string():
    assert db._total_games_played("") == 0


def test_get_games_played_in_last_match_returns_zero_without_finished_match(test_db_path):
    db.init_db(test_db_path)
    player_id = db.upsert_player(test_db_path, name="Carlos Alcaraz")
    assert db.get_games_played_in_last_match(test_db_path, player_id) == 0


def test_get_games_played_in_last_match_reads_finished_match(test_db_path):
    db.init_db(test_db_path)
    p1 = db.upsert_player(test_db_path, name="Carlos Alcaraz")
    p2 = db.upsert_player(test_db_path, name="Mark Newcomer")
    with db.get_connection(test_db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO draw_matches (tournament_id, year, round, player1_id, player2_id)
               VALUES ('wimbledon', 2026, '1R', ?, ?)""",
            (p1, p2),
        )
        match_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO live_scores (match_id, sets, status, updated_at) VALUES (?, ?, 'finished', '')",
            (match_id, "7-6(7), 6(5)-7, 7-6(2), 7-6(5)"),
        )
    games = db.get_games_played_in_last_match(test_db_path, p1)
    assert games == db._total_games_played("7-6(7), 6(5)-7, 7-6(2), 7-6(5)")
    assert db.get_games_played_in_last_match(test_db_path, p2) == games


def test_load_all_data_includes_fatigue_per_player(test_db_path):
    db.init_db(test_db_path)
    player_id = db.upsert_player(test_db_path, name="Carlos Alcaraz")
    data = db.load_all_data(test_db_path)
    assert data["fatigue"]["Carlos Alcaraz"] == 0


def test_init_db_creates_atp_rankings_table(test_db_path):
    db.init_db(test_db_path)
    conn = sqlite3.connect(test_db_path)
    cursor = conn.cursor()

    # Verify atp_rankings table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='atp_rankings'")
    assert cursor.fetchone() is not None, "atp_rankings table not found"

    # Verify column structure for atp_rankings
    cursor.execute("PRAGMA table_info(atp_rankings)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    assert "player_id" in columns, "player_id column not found"
    assert "ranking_position" in columns, "ranking_position column not found"
    assert "ranking_points" in columns, "ranking_points column not found"
    assert "scraped_at" in columns, "scraped_at column not found"

    # Verify recent_form table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='recent_form'")
    assert cursor.fetchone() is not None, "recent_form table not found"

    # Verify column structure for recent_form
    cursor.execute("PRAGMA table_info(recent_form)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    assert "player_id" in columns, "player_id column not found"
    assert "tournaments_played" in columns, "tournaments_played column not found"
    assert "wins" in columns, "wins column not found"
    assert "losses" in columns, "losses column not found"
    assert "titles" in columns, "titles column not found"
    assert "finals_reached" in columns, "finals_reached column not found"
    assert "last_tournament_date" in columns, "last_tournament_date column not found"
    assert "updated_at" in columns, "updated_at column not found"

    conn.close()


def test_upsert_ranking_inserts_and_updates(test_db_path):
    """Test that upsert_ranking inserts new rankings and updates existing ones."""
    db.init_db(test_db_path)
    # Create player
    player_id = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2100)

    # Insert ranking data
    db.upsert_ranking(test_db_path, player_id, ranking_position=1, ranking_points=10000)

    # Verify inserted data
    with db.get_connection(test_db_path) as conn:
        row = conn.execute("SELECT * FROM atp_rankings WHERE player_id = ?", (player_id,)).fetchone()
    assert row is not None
    assert row["ranking_position"] == 1
    assert row["ranking_points"] == 10000
    assert row["scraped_at"] is not None

    # Update with new values
    db.upsert_ranking(test_db_path, player_id, ranking_position=2, ranking_points=9500)

    # Verify update (no duplicate, values changed)
    with db.get_connection(test_db_path) as conn:
        rows = conn.execute("SELECT * FROM atp_rankings WHERE player_id = ?", (player_id,)).fetchall()
    assert len(rows) == 1, "upsert should not create duplicate rows"
    assert rows[0]["ranking_position"] == 2
    assert rows[0]["ranking_points"] == 9500


def test_upsert_recent_form_inserts_and_updates(test_db_path):
    """Test that upsert_recent_form inserts new form data and updates existing ones."""
    db.init_db(test_db_path)
    # Create player
    player_id = db.upsert_player(test_db_path, name="Novak Djokovic", elo=2050)

    # Insert form data
    db.upsert_recent_form(
        test_db_path, player_id,
        tournaments_played=5,
        wins=15,
        losses=3,
        titles=1,
        finals_reached=2,
        last_tournament_date="2026-06-15"
    )

    # Verify inserted data
    with db.get_connection(test_db_path) as conn:
        row = conn.execute("SELECT * FROM recent_form WHERE player_id = ?", (player_id,)).fetchone()
    assert row is not None
    assert row["tournaments_played"] == 5
    assert row["wins"] == 15
    assert row["losses"] == 3
    assert row["titles"] == 1
    assert row["finals_reached"] == 2
    assert row["last_tournament_date"] == "2026-06-15"
    assert row["updated_at"] is not None

    # Update with new values
    db.upsert_recent_form(
        test_db_path, player_id,
        tournaments_played=6,
        wins=18,
        losses=3,
        titles=2,
        finals_reached=3,
        last_tournament_date="2026-06-28"
    )

    # Verify update (no duplicate, values changed)
    with db.get_connection(test_db_path) as conn:
        rows = conn.execute("SELECT * FROM recent_form WHERE player_id = ?", (player_id,)).fetchall()
    assert len(rows) == 1, "upsert should not create duplicate rows"
    assert rows[0]["tournaments_played"] == 6
    assert rows[0]["wins"] == 18
    assert rows[0]["titles"] == 2
    assert rows[0]["finals_reached"] == 3
    assert rows[0]["last_tournament_date"] == "2026-06-28"
