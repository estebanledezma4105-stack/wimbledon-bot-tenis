"""Live scores scraper.

Two data sources are supported:
1. `run()` — consumes wimbledon.com's internal JSON endpoint directly (still
   an unconfirmed placeholder, see scrapers/draw.py for the rationale).
2. `run_from_tennisexplorer()` — scrapes tennisexplorer.com's `/matches/`
   page, which lists every tournament's matches happening today with live,
   updating set scores. Found by inspecting that page directly: it renders
   one `<table>` per tournament, headed by a row whose link points to that
   tournament's URL (e.g. `/wimbledon/2026/atp-men/`) — used to pick out
   just the Wimbledon table from the many tournaments listed on that page.
   Each match is two consecutive `<tr>` rows (same pairing convention as
   scrapers/h2h.py and scrapers/draw.py): td.result holds sets won, td.score
   (x5) holds each set's game count. There's no explicit "status" field, so
   completion is inferred from reaching the best-of-5 winning threshold —
   this scraper only targets ATP men's matches (best-of-5 at majors), and
   would need a different threshold for a WTA/best-of-3 draw.
   Only polled during match hours; intended to run every 2-3 minutes via the
   external scheduler, not in a loop inside this module.
"""
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import db
from scrapers import base, draw

LIVE_ENDPOINT = "https://www.wimbledon.com/en_GB/api/live_scores.json"  # placeholder, confirm via network inspection
TENNISEXPLORER_MATCHES_URL = "https://www.tennisexplorer.com/matches/"
WINNING_SETS_REQUIRED = 3  # best-of-5; ATP men's majors only


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


_SEED_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*")


def _find_tournament_rows(soup, tournament_url_fragment):
    """The /matches/ page renders every tournament happening today as
    sections of ONE shared <table> per sport, each section starting with its
    own tr.head row (linking to that tournament's URL) and running until the
    next tr.head row. Returns just the rows belonging to our tournament."""
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        target_start = None
        for i, row in enumerate(rows):
            if "head" not in (row.get("class") or []):
                continue
            link = row.find("a")
            if link and tournament_url_fragment in (link.get("href") or "").lower():
                target_start = i
                continue
            if target_start is not None:
                return rows[target_start + 1:i]
        if target_start is not None:
            return rows[target_start + 1:]
    return []


def _format_score_cell(cell):
    """tennisexplorer renders a tiebreak set score as e.g. <td>6<sup>7</sup></td>
    — the main game count plus the tiebreak loser's points in a nested <sup>.
    Naive get_text(strip=True) concatenates them into an ambiguous plain
    number (e.g. "67", or "612" for a 12-point breaker) — formats it instead
    as "6(7)"."""
    sup = cell.find("sup")
    if sup is None:
        return cell.get_text(strip=True)
    tiebreak_points = sup.get_text(strip=True)
    sup.extract()
    main_score = cell.get_text(strip=True)
    return f"{main_score}({tiebreak_points})"


def _format_sets(p1_scores, p2_scores):
    parts = []
    for a, b in zip(p1_scores, p2_scores):
        if a == "" and b == "":
            continue
        parts.append(f"{a}-{b}")
    return ", ".join(parts)


def parse_live_html(html, tournament_url_fragment="/wimbledon/2026/atp-men/"):
    """Returns a list of {"player1", "player2", "sets", "status"} dicts —
    player names are tennisexplorer's short labels (e.g. "Jodar R."), to be
    resolved against known players by the caller, the same way scrapers/draw.py
    resolves its own short labels."""
    soup = BeautifulSoup(html, "html.parser")
    rows = _find_tournament_rows(soup, tournament_url_fragment)

    results = []
    pending = None
    for row in rows:
        if "head" in (row.get("class") or []):
            continue
        name_cell = row.find("td", class_="t-name")
        result_cell = row.find("td", class_="result")
        if name_cell is None or result_cell is None:
            continue
        try:
            sets_won = int(result_cell.get_text(strip=True))
        except ValueError:
            continue
        name = _SEED_SUFFIX_RE.sub(" ", name_cell.get_text(strip=True)).strip()
        scores = [_format_score_cell(c) for c in row.find_all("td", class_="score")]
        is_first_row_of_pair = row.find("td", class_="first") is not None

        if is_first_row_of_pair:
            pending = {"name": name, "sets_won": sets_won, "scores": scores}
        elif pending is not None:
            status = "finished" if max(pending["sets_won"], sets_won) >= WINNING_SETS_REQUIRED else "in_progress"
            results.append({
                "player1": pending["name"],
                "player2": name,
                "sets": _format_sets(pending["scores"], scores),
                "status": status,
            })
            pending = None
    return results


def _label_matches_name(label, player_name):
    """Same token-subset idea as scrapers/h2h.py's _label_matches_canonical:
    checks whether any multi-letter token of a short label (e.g. "Jodar R.")
    appears among the full player name's tokens, skipping single-letter
    initials."""
    name_tokens = set(player_name.lower().split())
    label_tokens = [t.rstrip(".") for t in label.lower().split() if len(t.rstrip(".")) > 1]
    return any(token in name_tokens for token in label_tokens)


def _find_draw_match_id_by_labels(db_path, label1, label2):
    """Matches a live-score entry's short player labels directly against
    whatever names are already stored on draw_matches (which may themselves
    be bare surnames if the draw scraper couldn't resolve them further) —
    deliberately avoids re-resolving names through name_resolver/external
    search here, since a second independent resolution could drift from
    what the draw scraper already stored and silently miss the match.
    Only resolves if exactly one existing match qualifies, in either
    player order."""
    with db.get_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT dm.id, p1.name as p1_name, p2.name as p2_name
               FROM draw_matches dm
               JOIN players p1 ON p1.id = dm.player1_id
               JOIN players p2 ON p2.id = dm.player2_id
               WHERE dm.tournament_id = ? AND dm.year = ?""",
            (draw.DRAW_TOURNAMENT_ID, draw.DRAW_YEAR),
        ).fetchall()

    candidates = [
        row["id"] for row in rows
        if (_label_matches_name(label1, row["p1_name"]) and _label_matches_name(label2, row["p2_name"]))
        or (_label_matches_name(label1, row["p2_name"]) and _label_matches_name(label2, row["p1_name"]))
    ]
    return candidates[0] if len(candidates) == 1 else None


def store_live_scores_by_player_names(db_path, parsed):
    """Upserts into live_scores for whichever existing draw_matches row
    matches each entry's player-label pair. Entries that can't be matched to
    exactly one existing match (unresolved name, or genuine ambiguity) are
    skipped — see _find_draw_match_id_by_labels."""
    updated = 0
    for entry in parsed:
        match_id = _find_draw_match_id_by_labels(db_path, entry["player1"], entry["player2"])
        if match_id is None:
            continue
        with db.get_connection(db_path) as conn:
            conn.execute(
                """INSERT INTO live_scores (match_id, sets, status, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(match_id)
                   DO UPDATE SET sets = excluded.sets, status = excluded.status, updated_at = excluded.updated_at""",
                (match_id, entry["sets"], entry["status"], datetime.now(timezone.utc).isoformat()),
            )
        updated += 1
    return updated


def run_from_tennisexplorer(db_path, session=None):
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()

    def _fetch():
        response = session.get(TENNISEXPLORER_MATCHES_URL, timeout=10)
        response.raise_for_status()
        return response.text

    try:
        html = base.fetch_with_retry(_fetch)
        parsed = parse_live_html(html)
        updated = store_live_scores_by_player_names(db_path, parsed)
        base.log_scraper_run(db_path, "live_tennisexplorer", "success", rows_fetched=updated, started_at=started_at)
        return updated
    except Exception as exc:
        base.log_scraper_run(db_path, "live_tennisexplorer", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise


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
