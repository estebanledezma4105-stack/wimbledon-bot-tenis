from unittest.mock import MagicMock

import db
from scrapers import elo_uts

SAMPLE_PAYLOAD = {
    "rows": [
        {"rank": 1, "name": "Novak Djokovic", "points": 2450},
        {"rank": 2, "name": "Carlos Alcaraz Garfia", "points": 2346},
        {"rank": 7, "name": "Alex De Minaur", "points": 2108},
        {"rank": 99, "name": "No Points Player"},
    ]
}


def test_parse_uts_json_extracts_name_and_elo():
    parsed = elo_uts.parse_uts_json(SAMPLE_PAYLOAD)
    assert parsed == [
        {"name": "Novak Djokovic", "elo": 2450},
        {"name": "Carlos Alcaraz Garfia", "elo": 2346},
        {"name": "Alex De Minaur", "elo": 2108},
    ]


def test_resolve_by_token_subset_matches_name_with_extra_tokens(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    db.upsert_player(db_path, name="Carlos Alcaraz")
    assert elo_uts._resolve_by_token_subset(db_path, "Carlos Alcaraz Garfia") == "Carlos Alcaraz"


def test_resolve_by_token_subset_matches_extra_token_in_middle(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    db.upsert_player(db_path, name="Taylor Fritz")
    assert elo_uts._resolve_by_token_subset(db_path, "Taylor Harry Fritz") == "Taylor Fritz"


def test_resolve_by_token_subset_returns_none_when_ambiguous(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    db.upsert_player(db_path, name="Alex De Minaur")
    db.upsert_player(db_path, name="Alex Smith")
    assert elo_uts._resolve_by_token_subset(db_path, "Alex Someone") is None


def test_run_updates_elo_without_creating_duplicate_for_known_player(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    db.upsert_player(db_path, name="Carlos Alcaraz", ranking=2)

    mock_response = MagicMock()
    mock_response.json.return_value = SAMPLE_PAYLOAD
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    rows = elo_uts.run(db_path, session=mock_session)
    assert rows == 3

    with db.get_connection(db_path) as conn:
        alcaraz_rows = conn.execute("SELECT * FROM players WHERE name = 'Carlos Alcaraz'").fetchall()
    assert len(alcaraz_rows) == 1
    assert alcaraz_rows[0]["elo"] == 2346
    assert alcaraz_rows[0]["ranking"] == 2


def test_run_logs_failure_and_reraises_on_fetch_error(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    mock_session = MagicMock()
    mock_session.get.side_effect = ConnectionError("network down")

    try:
        elo_uts.run(db_path, session=mock_session)
        assert False, "expected ConnectionError to propagate"
    except ConnectionError:
        pass

    with db.get_connection(db_path) as conn:
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'elo_uts'").fetchone()
    assert run_log["status"] == "failure"
    assert run_log["rows_fetched"] == 0


def test_run_form_stores_delta_between_recent_and_current_elo(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    player_id = db.upsert_player(db_path, name="Jannik Sinner", elo=2162)

    payload = {"rows": [{"rank": 1, "name": "Jannik Sinner", "points": 2570}]}
    mock_response = MagicMock()
    mock_response.json.return_value = payload
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    rows = elo_uts.run_form(db_path, session=mock_session)
    assert rows == 1
    assert db.get_form_points(db_path, player_id) == 2570 - 2162


def test_run_form_skips_unknown_players_without_creating_them(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    payload = {"rows": [{"rank": 1, "name": "Totally Unknown Player", "points": 2000}]}
    mock_response = MagicMock()
    mock_response.json.return_value = payload
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    rows = elo_uts.run_form(db_path, session=mock_session)
    assert rows == 0
    assert db.get_player_by_name(db_path, "Totally Unknown Player") is None
