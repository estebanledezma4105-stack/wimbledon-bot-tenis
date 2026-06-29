import os
from unittest.mock import MagicMock

import db
from scrapers import surface_stats

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "surface_stats.html")


def test_parse_surface_stats_computes_winrates():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = surface_stats.parse_surface_stats_html(html)
    assert parsed["grass_winrate"] == round(18 / 22, 4)
    total_wins = 18 + 40 + 22
    total_matches = 22 + 55 + 32
    assert parsed["total_winrate"] == round(total_wins / total_matches, 4)
    assert parsed["matches_played"] == total_matches


def test_parse_surface_stats_returns_none_without_grass_row():
    html = '<table class="surface-stats"><tr><td class="surface">Hard</td><td class="wins">1</td><td class="losses">1</td></tr></table>'
    assert surface_stats.parse_surface_stats_html(html) is None


def test_store_surface_stats_upserts(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    player_id = db.upsert_player(db_path, name="Carlos Alcaraz")
    parsed = {"grass_winrate": 0.8182, "total_winrate": 0.7339, "matches_played": 109}

    surface_stats.store_surface_stats(db_path, player_id, parsed)
    surface_stats.store_surface_stats(db_path, player_id, {**parsed, "matches_played": 110})

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM grass_stats WHERE player_id = ?", (player_id,)).fetchone()
    assert row["matches_played"] == 110


def test_run_for_player_logs_failure_and_reraises_on_fetch_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    player_id = db.upsert_player(db_path, name="Carlos Alcaraz")

    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("network down")

    try:
        surface_stats.run_for_player(db_path, player_id, "https://example.com/profile", session=mock_session)
        assert False, "expected ConnectionError to propagate"
    except ConnectionError:
        pass

    with db.get_connection(db_path) as conn:
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'surface_stats'").fetchone()
    assert run_log["status"] == "failure"
    assert run_log["rows_fetched"] == 0
    assert "network down" in run_log["error_message"]
