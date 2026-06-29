"""Real Elo ratings from ultimatetennisstatistics.com's JSON API.

UTS exposes its rankings table via a bootgrid AJAX endpoint
(/rankingsTableTable) rather than server-rendered HTML — found by inspecting
the page's embedded JS, not by guessing. `rankType=GRASS_ELO_RANK` returns
real surface-specific Elo points, which is exactly what's missing from the
rankings scraper (tennisexplorer.com only gives ATP ranking position, not a
rating). Names come back with extra middle/maiden tokens (e.g. "Carlos Alcaraz
Garfia", "Taylor Harry Fritz", "Alex De Minaur") that don't follow a fixed
position — naively truncating to N tokens mangles names differently
depending on whether the extra token is in the middle or at the end. Instead,
a known player is matched if ALL of their canonical name's tokens appear
somewhere in the raw UTS name (order-independent), and exactly one player
qualifies — this is robust to extra tokens in any position.
"""
from datetime import datetime, timezone

import db
import name_resolver
from scrapers import base

UTS_ENDPOINT = "https://www.ultimatetennisstatistics.com/rankingsTableTable"


def _resolve_by_token_subset(db_path, raw_name):
    """Match a known player whose every name-token appears somewhere in the
    raw UTS name, regardless of position. Only resolves if exactly one
    player qualifies, to avoid guessing wrong on an ambiguous match."""
    with db.get_connection(db_path) as conn:
        rows = conn.execute("SELECT name FROM players").fetchall()
    raw_tokens = set(raw_name.lower().split())
    matches = [
        row["name"] for row in rows
        if set(row["name"].lower().split()).issubset(raw_tokens)
    ]
    return matches[0] if len(matches) == 1 else None


def parse_uts_json(payload):
    results = []
    for row in payload.get("rows", []):
        if "name" not in row or "points" not in row:
            continue
        results.append({"name": row["name"], "elo": row["points"]})
    return results


def run(db_path, rank_type="GRASS_ELO_RANK", row_count=100, session=None):
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()

    def _fetch():
        response = session.get(
            UTS_ENDPOINT, params={"rankType": rank_type, "rowCount": row_count}, timeout=10
        )
        response.raise_for_status()
        return response.json()

    try:
        payload = base.fetch_with_retry(_fetch)
        parsed = parse_uts_json(payload)
        rows_written = 0
        for entry in parsed:
            canonical = (
                name_resolver.resolve(db_path, entry["name"], source="ultimatetennisstatistics")
                or _resolve_by_token_subset(db_path, entry["name"])
                or entry["name"]
            )
            db.upsert_player(db_path, name=canonical, elo=entry["elo"])
            rows_written += 1
            base.jittered_sleep(0.1, 0.3)
        base.log_scraper_run(db_path, "elo_uts", "success", rows_fetched=rows_written, started_at=started_at)
        return rows_written
    except Exception as exc:
        base.log_scraper_run(db_path, "elo_uts", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise
