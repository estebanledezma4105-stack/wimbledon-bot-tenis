"""Prediction logging and accuracy tracking.

Predictions must be locked in via db.record_prediction() BEFORE a match's
result is known — computing "accuracy" by re-running predict_match() after
the fact uses elo/h2h data that has already absorbed the result (or
nearby results), which silently inflates apparent accuracy. This module is
the only place that should call record_prediction(); call
log_pending_predictions() on a schedule (e.g. from live_update.py) so every
still-undecided match gets a prediction snapshot as soon as it's known.

tennisexplorer.com's draw page doesn't keep showing a finished match's
result (it gets replaced by the next round's pairing once decided), so the
winner has to be derived from live_scores' parsed set scores instead.
"""
import db


def _count_set_wins(sets_str):
    """Counts sets won by each player from a formatted string like
    "6-3, 7-6(7), 4-6" (see scrapers/live.py's _format_sets/_format_score_cell)."""
    p1_sets = p2_sets = 0
    for part in (sets_str or "").split(","):
        part = part.strip()
        if "-" not in part:
            continue
        a_raw, b_raw = part.split("-", 1)
        try:
            a_games = int(a_raw.split("(")[0])
            b_games = int(b_raw.split("(")[0])
        except ValueError:
            continue
        if a_games > b_games:
            p1_sets += 1
        elif b_games > a_games:
            p2_sets += 1
    return p1_sets, p2_sets


def backfill_winners_from_live(db_path):
    """For matches marked 'finished' in live_scores but still missing a
    winner in draw_matches, derives the winner from the set scores and
    records it. Skips matches that end in a set-count tie (shouldn't happen
    in real tennis, but a malformed scrape shouldn't silently guess)."""
    with db.get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT ls.match_id, ls.sets, dm.player1_id, dm.player2_id
               FROM live_scores ls
               JOIN draw_matches dm ON dm.id = ls.match_id
               WHERE ls.status = 'finished' AND dm.winner_id IS NULL"""
        ).fetchall()

    updated = 0
    for row in rows:
        p1_sets, p2_sets = _count_set_wins(row["sets"])
        if p1_sets == p2_sets:
            continue
        winner_id = row["player1_id"] if p1_sets > p2_sets else row["player2_id"]
        db.set_match_winner(db_path, row["match_id"], winner_id)
        updated += 1
    return updated


def log_pending_predictions(db_path):
    """Snapshots a prediction for every still-undecided match that doesn't
    already have one locked in. Safe to call repeatedly — record_prediction
    never overwrites an existing row."""
    import wimbledon_bot as bot  # deferred: avoids importing telegram at module load time for callers that don't need it

    data = db.load_all_data(db_path)
    with db.get_connection(db_path) as conn:
        already_logged = {row["match_id"] for row in conn.execute("SELECT match_id FROM predictions").fetchall()}

    logged = 0
    for match in data["draw"]["matches"]:
        if match["winner"] is not None or match["id"] in already_logged:
            continue
        pred = bot.predict_match(match["player1"], match["player2"], data)
        favorite_player = db.get_player_by_name(db_path, pred["favorite"])
        if favorite_player is None:
            continue
        probability = max(pred["prob_a"], pred["prob_b"])
        db.record_prediction(db_path, match["id"], favorite_player["id"], probability)
        logged += 1
    return logged


def compute_accuracy(db_path):
    """Returns (correct, total, details) — see db.get_accuracy_stats."""
    return db.get_accuracy_stats(db_path)
