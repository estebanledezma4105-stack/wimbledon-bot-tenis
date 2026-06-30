import db
import backtesting


def _make_match(db_path, p1_name, p2_name, winner_name, round_="1R"):
    """Helper to create a completed match in the database."""
    p1 = db.upsert_player(db_path, name=p1_name)
    p2 = db.upsert_player(db_path, name=p2_name)
    winner = db.upsert_player(db_path, name=winner_name)
    with db.get_connection(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO draw_matches (tournament_id, year, round, player1_id, player2_id, winner_id)
               VALUES ('wimbledon', 2026, ?, ?, ?, ?)""",
            (round_, p1, p2, winner),
        )
        return cursor.lastrowid, p1, p2, winner


def test_backtest_weights_returns_accuracy(tmp_path):
    """Test that backtest_weights returns a float between 0 and 1."""
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    # Create a few completed matches
    _make_match(db_path, "Alcaraz", "Opponent1", "Alcaraz")
    _make_match(db_path, "Djokovic", "Opponent2", "Djokovic")

    # Set up initial Elo ratings
    db.upsert_player(db_path, name="Alcaraz", elo=2100)
    db.upsert_player(db_path, name="Djokovic", elo=2000)
    db.upsert_player(db_path, name="Opponent1", elo=1500)
    db.upsert_player(db_path, name="Opponent2", elo=1500)

    # Load data
    data = db.load_all_data(db_path)

    # Define a weight combination
    weight_combo = {
        'K_ELO': 32,
        'W_GRASS': 1.5,
        'W_FORM': 0.7,
        'W_H2H': 25,
        'W_FATIGUE': 0.15,
        'W_RANKING': 0.0,
        'W_RECENT_FORM': 0.0,
    }

    # Run backtest
    accuracy = backtesting.backtest_weights(
        data['draw']['completed_matches'],
        data['elo'].copy(),
        data['grass_stats'],
        data['h2h'],
        data['form'],
        {},  # ranking_dict
        {},  # recent_form_dict
        weight_combo
    )

    # Verify it returns a float between 0 and 1
    assert isinstance(accuracy, float)
    assert 0.0 <= accuracy <= 1.0


def test_run_grid_search_finds_best(tmp_path):
    """Test that run_grid_search returns best_accuracy and best_weights."""
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)

    # Create a few completed matches
    _make_match(db_path, "Alcaraz", "Opponent1", "Alcaraz")
    _make_match(db_path, "Djokovic", "Opponent2", "Djokovic")
    _make_match(db_path, "Federer", "Opponent3", "Federer")

    # Set up initial Elo ratings
    db.upsert_player(db_path, name="Alcaraz", elo=2100)
    db.upsert_player(db_path, name="Djokovic", elo=2000)
    db.upsert_player(db_path, name="Federer", elo=1950)
    db.upsert_player(db_path, name="Opponent1", elo=1500)
    db.upsert_player(db_path, name="Opponent2", elo=1500)
    db.upsert_player(db_path, name="Opponent3", elo=1500)

    # Load data
    data = db.load_all_data(db_path)

    # Run grid search with a small grid for fast testing
    results = backtesting.run_grid_search(
        data['draw']['completed_matches'],
        data['elo'].copy(),
        data['grass_stats'],
        data['h2h'],
        data['form'],
        {},  # ranking_dict
        {},  # recent_form_dict
    )

    # Verify the results structure
    assert 'best_accuracy' in results
    assert 'best_weights' in results
    assert 'top_10' in results

    # Verify types and ranges
    assert isinstance(results['best_accuracy'], float)
    assert 0.0 <= results['best_accuracy'] <= 1.0
    assert isinstance(results['best_weights'], dict)
    assert isinstance(results['top_10'], list)

    # Verify best_weights has all required keys
    required_keys = {'K_ELO', 'W_GRASS', 'W_FORM', 'W_H2H', 'W_FATIGUE', 'W_RANKING', 'W_RECENT_FORM'}
    assert set(results['best_weights'].keys()) == required_keys

    # Verify top_10 structure
    if len(results['top_10']) > 0:
        for item in results['top_10']:
            assert 'accuracy' in item
            assert 'weights' in item
            assert isinstance(item['accuracy'], float)
            assert isinstance(item['weights'], dict)
