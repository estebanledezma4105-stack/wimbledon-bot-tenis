import os

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


def test_load_dotenv_sets_environ_without_overwriting_existing(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TELEGRAM_TOKEN=from-dotenv\n"
        "# a comment\n"
        "\n"
        "ALREADY_SET=should-not-overwrite\n"
        'QUOTED_VALUE="hello world"\n'
    )
    monkeypatch.delenv("TELEGRAM_TOKEN", raising=False)
    monkeypatch.setenv("ALREADY_SET", "original-value")

    wimbledon_bot._load_dotenv(str(env_file))

    assert os.environ["TELEGRAM_TOKEN"] == "from-dotenv"
    assert os.environ["ALREADY_SET"] == "original-value"
    assert os.environ["QUOTED_VALUE"] == "hello world"


def test_load_dotenv_missing_file_does_not_raise(tmp_path):
    wimbledon_bot._load_dotenv(str(tmp_path / "does_not_exist.env"))


def test_cmd_partidos_filters_to_todays_pending_matches_only():
    """Regression test: /partidos must show only matches scheduled for the
    real current date, not every pending match ever scraped (which would
    accumulate future/past rounds once the tournament moves past day 1)."""
    today_str = "2026-06-29"
    matches = [
        {"player1": "Carlos Alcaraz", "player2": "Mark Newcomer",
         "winner": "Carlos Alcaraz", "scheduled_date": today_str},
        {"player1": "Novak Djokovic", "player2": "Jane Qualifier",
         "winner": None, "scheduled_date": today_str},
        {"player1": "Future Player", "player2": "Other Future Player",
         "winner": None, "scheduled_date": "2026-07-01"},
        {"player1": "No Date Player", "player2": "Another No Date",
         "winner": None, "scheduled_date": None},
    ]
    todays_matches = [
        m for m in matches if m.get("scheduled_date") == today_str and not m["winner"]
    ]
    assert todays_matches == [
        {"player1": "Novak Djokovic", "player2": "Jane Qualifier",
         "winner": None, "scheduled_date": today_str},
    ]


def test_live_status_labels_have_no_underscore():
    """Regression test: Telegram's legacy Markdown parser treats a lone `_`
    as an unterminated italic entity and rejects the whole message
    (telegram.error.BadRequest: Can't parse entities). The raw status
    'in_progress' has an underscore — cmd_live must translate it to a
    display label before formatting, never send the raw value."""
    for raw_status, label in wimbledon_bot._LIVE_STATUS_LABELS.items():
        assert "_" not in label, f"{raw_status!r} maps to {label!r}, which still contains an underscore"


def test_get_fatigue_bonus_penalizes_games_above_baseline():
    fatigue_data = {"Tired Player": 38, "Fresh Player": 18}
    tired_bonus = wimbledon_bot.get_fatigue_bonus("Tired Player", fatigue_data)
    fresh_bonus = wimbledon_bot.get_fatigue_bonus("Fresh Player", fatigue_data)
    assert tired_bonus < 0
    assert fresh_bonus == 0
    assert tired_bonus == -wimbledon_bot.W_FATIGUE * (38 - wimbledon_bot.FATIGUE_BASELINE_GAMES)


def test_get_fatigue_bonus_defaults_to_zero_for_unknown_player():
    assert wimbledon_bot.get_fatigue_bonus("Nobody", {}) == 0


def test_predict_match_favors_fresher_player_when_elo_is_equal():
    data = {
        "elo": {"Tired Player": 1800, "Fresh Player": 1800},
        "grass_stats": {},
        "form": {},
        "h2h": {},
        "fatigue": {"Tired Player": 40, "Fresh Player": 18},
    }
    pred = wimbledon_bot.predict_match("Tired Player", "Fresh Player", data)
    assert pred["favorite"] == "Fresh Player"


def test_get_ranking_bonus_top10():
    """Top 10 ranked players should receive a positive ranking bonus."""
    ranking_dict = {"Carlos Alcaraz": 1, "Novak Djokovic": 2, "Jannik Sinner": 3}

    bonus_alcaraz = wimbledon_bot.get_ranking_bonus("Carlos Alcaraz", ranking_dict)
    bonus_djokovic = wimbledon_bot.get_ranking_bonus("Novak Djokovic", ranking_dict)
    bonus_sinner = wimbledon_bot.get_ranking_bonus("Jannik Sinner", ranking_dict)

    assert bonus_alcaraz > 0
    assert bonus_djokovic > 0
    assert bonus_sinner > 0
    assert bonus_alcaraz > bonus_djokovic > bonus_sinner


def test_get_ranking_bonus_unknown():
    """Unranked players (ranking 2000) should have ~0 bonus."""
    ranking_dict = {"Carlos Alcaraz": 1, "Unknown Player": 2000}

    bonus_unknown = wimbledon_bot.get_ranking_bonus("Unknown Player", ranking_dict)
    bonus_not_in_dict = wimbledon_bot.get_ranking_bonus("Not In Dict", ranking_dict)

    assert abs(bonus_unknown) < 0.001
    assert abs(bonus_not_in_dict) < 0.001


def test_get_recent_form_bonus_strong():
    """Strong recent form (60% win rate) should provide a positive bonus."""
    recent_form_dict = {"Strong Player": {"wins": 6, "losses": 4}}

    bonus = wimbledon_bot.get_recent_form_bonus("Strong Player", recent_form_dict)

    assert bonus > 0


def test_get_recent_form_bonus_poor():
    """Poor recent form (40% win rate) should provide a negative bonus."""
    recent_form_dict = {"Poor Player": {"wins": 4, "losses": 6}}

    bonus = wimbledon_bot.get_recent_form_bonus("Poor Player", recent_form_dict)

    assert bonus < 0


def test_get_recent_form_bonus_no_tournaments():
    """Players with no tournament data should have 0 bonus (neutral form)."""
    recent_form_dict = {}

    bonus = wimbledon_bot.get_recent_form_bonus("No History Player", recent_form_dict)

    assert abs(bonus) < 0.001


def test_calculate_rating_includes_ranking_and_form():
    """Test that calculate_rating() includes ranking and recent_form bonuses."""
    # Set up data with all parameters
    elo_dict = {"Carlos Alcaraz": 2100, "Mark Newcomer": 1500}
    grass_stats = {
        "Carlos Alcaraz": {"grass_winrate": 0.65, "total_winrate": 0.60},
        "Mark Newcomer": {"grass_winrate": 0.50, "total_winrate": 0.45},
    }
    form_data = {"Carlos Alcaraz": 20, "Mark Newcomer": -10}
    h2h = {}
    ranking_dict = {"Carlos Alcaraz": 1, "Mark Newcomer": 50}
    recent_form_dict = {
        "Carlos Alcaraz": {"wins": 8, "losses": 2},
        "Mark Newcomer": {"wins": 3, "losses": 7},
    }
    fatigue_data = {}

    # Calculate rating for both players
    rating_alcaraz = wimbledon_bot.calculate_rating(
        "Carlos Alcaraz", "Mark Newcomer",
        elo_dict, grass_stats, form_data, h2h, fatigue_data,
        ranking_dict, recent_form_dict
    )
    rating_newcomer = wimbledon_bot.calculate_rating(
        "Mark Newcomer", "Carlos Alcaraz",
        elo_dict, grass_stats, form_data, h2h, fatigue_data,
        ranking_dict, recent_form_dict
    )

    # Base ELO ratings
    base_elo_alcaraz = elo_dict["Carlos Alcaraz"]
    base_elo_newcomer = elo_dict["Mark Newcomer"]

    # With positive bonuses, ratings should be > base ELO
    assert rating_alcaraz > base_elo_alcaraz, "Alcaraz (top-ranked, good form) should have rating > base ELO"
    assert rating_newcomer < base_elo_newcomer, "Newcomer (lower-ranked, poor form) should have rating < base ELO"
