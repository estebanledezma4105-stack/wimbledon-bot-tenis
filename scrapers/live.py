"""Live scores scraper — consumes wimbledon.com's internal JSON endpoint
(see scrapers/draw.py for the rationale on avoiding DOM parsing on this site).
Only polled during match hours; intended to run every 2-3 minutes via the
external scheduler, not in a loop inside this module.
"""
from datetime import datetime, timezone

import db
from scrapers import base

LIVE_ENDPOINT = "https://www.wimbledon.com/en_GB/api/live_scores.json"  # placeholder, confirm via network inspection


def parse_live_json(payload):
    results = []
    for entry in payload:
        if "matchId" not in entry:
            continue
        results.append({
            "external_match_id": entry["matchId"],
            "sets": entry.get("sets"),
            "status": entry.get("status"),
        })
    return results


def _find_local_match_id(db_path, external_match_id, external_id_map):
    """external_id_map maps external_match_id -> local draw_matches.id.
    Built by the caller from a prior reconciliation step (out of scope for
    this scraper, which only knows the external ids returned by the API).
    """
    return external_id_map.get(external_match_id)


def store_live_scores(db_path, parsed, external_id_map):
    updated = 0
    for entry in parsed:
        local_id = _find_local_match_id(db_path, entry["external_match_id"], external_id_map)
        if local_id is None:
            continue
        with db.get_connection(db_path) as conn:
            conn.execute(
                """INSERT INTO live_scores (match_id, sets, status, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(match_id)
                   DO UPDATE SET sets = excluded.sets, status = excluded.status, updated_at = excluded.updated_at""",
                (local_id, entry["sets"], entry["status"], datetime.now(timezone.utc).isoformat()),
            )
        updated += 1
    return updated


def run(db_path, external_id_map, session=None):
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()

    def _fetch():
        response = session.get(LIVE_ENDPOINT, timeout=10)
        response.raise_for_status()
        return response.json()

    try:
        payload = base.fetch_with_retry(_fetch)
        parsed = parse_live_json(payload)
        updated = store_live_scores(db_path, parsed, external_id_map)
        base.log_scraper_run(db_path, "live", "success", rows_fetched=updated, started_at=started_at)
        return updated
    except Exception as exc:
        base.log_scraper_run(db_path, "live", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise
