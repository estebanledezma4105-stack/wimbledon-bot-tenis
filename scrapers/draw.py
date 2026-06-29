"""Wimbledon draw scraper — consumes the site's internal JSON endpoint directly
(SPA sites like wimbledon.com are Cloudflare-protected and React/Next.js-based;
parsing the DOM is unreliable). If the endpoint disappears, fall back to
Playwright-rendered HTML before resorting to static parsing.
"""
from datetime import datetime, timezone

import db
import name_resolver
from scrapers import base

DRAW_TOURNAMENT_ID = "wimbledon"
DRAW_YEAR = 2026
DRAW_ENDPOINT = "https://www.wimbledon.com/en_GB/api/draw.json"  # placeholder, confirm via network inspection


def parse_draw_json(payload):
    results = []
    for entry in payload:
        if not all(k in entry for k in ("round", "player1", "player2")):
            continue
        results.append({
            "round": entry["round"],
            "player1": entry["player1"],
            "player2": entry["player2"],
            "winner": entry.get("winner"),
            "completed_at": entry.get("completedAt"),
        })
    return results


def _store_match(db_path, entry):
    p1_canonical = name_resolver.resolve(db_path, entry["player1"], source="wimbledon") or entry["player1"]
    p2_canonical = name_resolver.resolve(db_path, entry["player2"], source="wimbledon") or entry["player2"]
    p1_id = db.upsert_player(db_path, name=p1_canonical)
    p2_id = db.upsert_player(db_path, name=p2_canonical)
    winner_id = None
    if entry["winner"]:
        winner_canonical = name_resolver.resolve(db_path, entry["winner"], source="wimbledon") or entry["winner"]
        winner_id = db.upsert_player(db_path, name=winner_canonical)

    with db.get_connection(db_path) as conn:
        existing = conn.execute(
            """SELECT id FROM draw_matches
               WHERE tournament_id = ? AND year = ? AND round = ?
               AND player1_id = ? AND player2_id = ?""",
            (DRAW_TOURNAMENT_ID, DRAW_YEAR, entry["round"], p1_id, p2_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE draw_matches SET winner_id = ?, completed_at = ? WHERE id = ?",
                (winner_id, entry["completed_at"], existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO draw_matches
                   (tournament_id, year, round, player1_id, player2_id, winner_id, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (DRAW_TOURNAMENT_ID, DRAW_YEAR, entry["round"], p1_id, p2_id, winner_id, entry["completed_at"]),
            )


def run(db_path, session=None):
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()

    def _fetch():
        response = session.get(DRAW_ENDPOINT, timeout=10)
        response.raise_for_status()
        return response.json()

    try:
        payload = base.fetch_with_retry(_fetch)
        parsed = parse_draw_json(payload)
        for entry in parsed:
            _store_match(db_path, entry)
        base.log_scraper_run(db_path, "draw", "success", rows_fetched=len(parsed), started_at=started_at)
        return len(parsed)
    except Exception as exc:
        base.log_scraper_run(db_path, "draw", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise
