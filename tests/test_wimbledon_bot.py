import db
import wimbledon_bot


def test_update_elo_from_results_persists_winner_and_loser_elo(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(wimbledon_bot, "DB_PATH", db_path)
    db.init_db(db_path)

    winner_id = db.upsert_player(db_path, name="Carlos Alcaraz", elo=2100)
    loser_id = db.upsert_player(db_path, name="Mark Newcomer", elo=1500)

    with db.get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO draw_matches
               (tournament_id, year, round, player1_id, player2_id, winner_id, completed_at)
               VALUES ('wimbledon', 2026, 'R1', ?, ?, ?, '2026-06-29T15:00:00Z')""",
            (winner_id, loser_id, winner_id),
        )

    wimbledon_bot.update_elo_from_results()

    winner_row = db.get_player_by_name(db_path, "Carlos Alcaraz")
    loser_row = db.get_player_by_name(db_path, "Mark Newcomer")
    assert winner_row["elo"] > 2100
    assert loser_row["elo"] < 1500


def test_update_elo_from_results_no_completed_matches_does_not_raise(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr(wimbledon_bot, "DB_PATH", db_path)
    db.init_db(db_path)

    wimbledon_bot.update_elo_from_results()


def test_resolve_player_name_is_case_insensitive():
    """Regression test: scraped/canonical names are stored mixed-case
    (e.g. "Carlos Alcaraz"), but Telegram users type lowercase commands
    like '/predict alcaraz vs djokovic' — lookup must not be case-sensitive."""
    elo_dict = {"Carlos Alcaraz": 2100, "Novak Djokovic": 2050}
    assert wimbledon_bot._resolve_player_name("alcaraz", {}) is None
    assert wimbledon_bot._resolve_player_name("carlos alcaraz", elo_dict) == "Carlos Alcaraz"
    assert wimbledon_bot._resolve_player_name("  Novak Djokovic  ", elo_dict) == "Novak Djokovic"
    assert wimbledon_bot._resolve_player_name("Someone Else", elo_dict) is None


def test_win_probability_is_symmetric_and_bounded():
    higher = wimbledon_bot.win_probability(2100, 1500)
    lower = wimbledon_bot.win_probability(1500, 2100)
    assert higher > 0.5 > lower
    assert abs(higher + lower - 1.0) < 1e-9
    assert wimbledon_bot.win_probability(1500, 1500) == 0.5


def test_predict_match_picks_favorite_by_elo():
    data = {
        "elo": {"Carlos Alcaraz": 2100, "Mark Newcomer": 1500},
        "grass_stats": {},
        "form": {},
        "h2h": {},
    }
    pred = wimbledon_bot.predict_match("Carlos Alcaraz", "Mark Newcomer", data)
    assert pred["favorite"] == "Carlos Alcaraz"
    assert pred["prob_a"] > pred["prob_b"]
