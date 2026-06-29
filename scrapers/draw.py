"""Wimbledon draw scraper.

Two data sources are supported:
1. `run()` — consumes wimbledon.com's internal JSON endpoint directly (SPA
   sites are Cloudflare-protected and React/Next.js-based; parsing the DOM
   is unreliable). The endpoint below is still a placeholder pending network
   inspection of the live site.
2. `run_from_tennisexplorer()` — scrapes tennisexplorer.com's tournament
   match-list page instead, which is real and working today. This page only
   lists surnames (no first name), so name resolution falls back to a
   surname-only lookup against already-known players when the normal
   resolver (seed dict + fuzzy match on full names) can't find a match.
"""
import re
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

import db
import name_resolver
from scrapers import base

DRAW_TOURNAMENT_ID = "wimbledon"
DRAW_YEAR = 2026
DRAW_ENDPOINT = "https://www.wimbledon.com/en_GB/api/draw.json"  # placeholder, confirm via network inspection
TENNISEXPLORER_DRAW_URL = "https://www.tennisexplorer.com/wimbledon/2026/atp-men/"


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
            "scheduled_date": entry.get("scheduledDate"),
        })
    return results


def _resolve_by_surname(db_path, raw_surname):
    """Fallback for sources (like tennisexplorer's match-list page) that only
    give a surname. Only resolves if exactly one known player has that
    surname — an ambiguous match (e.g. two Zverevs) falls through to the
    caller's normal fallback instead of guessing wrong."""
    with db.get_connection(db_path) as conn:
        rows = conn.execute("SELECT name FROM players").fetchall()
    raw_lower = raw_surname.strip().lower()
    matches = [row["name"] for row in rows if row["name"].lower().split()[-1] == raw_lower]
    return matches[0] if len(matches) == 1 else None


def _resolve_or_fallback(db_path, raw_name, source):
    return (
        name_resolver.resolve(db_path, raw_name, source)
        or _resolve_by_surname(db_path, raw_name)
        or raw_name
    )


def _store_match(db_path, entry):
    p1_canonical = _resolve_or_fallback(db_path, entry["player1"], source="wimbledon")
    p2_canonical = _resolve_or_fallback(db_path, entry["player2"], source="wimbledon")
    p1_id = db.upsert_player(db_path, name=p1_canonical)
    p2_id = db.upsert_player(db_path, name=p2_canonical)
    winner_id = None
    if entry["winner"]:
        winner_canonical = _resolve_or_fallback(db_path, entry["winner"], source="wimbledon")
        winner_id = db.upsert_player(db_path, name=winner_canonical)

    with db.get_connection(db_path) as conn:
        existing = conn.execute(
            """SELECT id FROM draw_matches
               WHERE tournament_id = ? AND year = ? AND round = ?
               AND player1_id = ? AND player2_id = ?""",
            (DRAW_TOURNAMENT_ID, DRAW_YEAR, entry["round"], p1_id, p2_id),
        ).fetchone()
        scheduled_date = entry.get("scheduled_date")
        if existing:
            conn.execute(
                """UPDATE draw_matches SET winner_id = ?, completed_at = ?,
                       scheduled_date = COALESCE(?, scheduled_date) WHERE id = ?""",
                (winner_id, entry["completed_at"], scheduled_date, existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO draw_matches
                   (tournament_id, year, round, player1_id, player2_id, winner_id, completed_at, scheduled_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (DRAW_TOURNAMENT_ID, DRAW_YEAR, entry["round"], p1_id, p2_id, winner_id,
                 entry["completed_at"], scheduled_date),
            )


_SEED_SUFFIX_RE = re.compile(r"\s*\(\d+\)\s*")


def _find_match_table(soup):
    for table in soup.find_all("table", class_="result"):
        header = table.find("tr", class_="head")
        if header is None:
            continue
        if header.find("td", class_="round") is not None:
            return table
    return None


def _extract_scheduled_date(row, today=None):
    """tennisexplorer.com's "Start" column reads "today , 12:00" for matches
    happening today, or a different label for other days. Only the "today"
    case is resolved to a real calendar date here — matches scheduled for
    other days are intentionally left with scheduled_date=None rather than
    guessed, so they don't get misfiled into "today" by a parsing mistake."""
    time_cell = row.find("td", class_="time")
    if time_cell is None:
        return None
    text = time_cell.get_text(" ", strip=True).lower()
    if text.startswith("today"):
        return (today or date.today()).isoformat()
    return None


def parse_draw_html(html, today=None):
    soup = BeautifulSoup(html, "html.parser")
    table = _find_match_table(soup)
    if table is None:
        return []
    results = []
    for row in table.find_all("tr"):
        if "head" in (row.get("class") or []):
            continue
        round_cell = row.find("td", class_="round")
        name_cell = row.find("td", class_="t-name")
        if round_cell is None or name_cell is None:
            continue
        raw_text = name_cell.get_text(" ", strip=True)
        if " - " not in raw_text:
            continue
        p1_raw, p2_raw = raw_text.split(" - ", 1)
        player1 = _SEED_SUFFIX_RE.sub(" ", p1_raw).strip()
        player2 = _SEED_SUFFIX_RE.sub(" ", p2_raw).strip()
        if not player1 or not player2:
            continue
        results.append({
            "round": round_cell.get_text(strip=True),
            "player1": player1,
            "player2": player2,
            "winner": None,
            "completed_at": None,
            "scheduled_date": _extract_scheduled_date(row, today=today),
        })
    return results


def run_from_tennisexplorer(db_path, url=TENNISEXPLORER_DRAW_URL, session=None):
    """Alternative to run(): scrapes tennisexplorer.com's match-list page
    instead of wimbledon.com's (still-unconfirmed) JSON endpoint."""
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()

    def _fetch():
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text

    try:
        html = base.fetch_with_retry(_fetch)
        parsed = parse_draw_html(html)
        for entry in parsed:
            _store_match(db_path, entry)
            base.jittered_sleep(0.1, 0.3)
        base.log_scraper_run(db_path, "draw_tennisexplorer", "success", rows_fetched=len(parsed), started_at=started_at)
        return len(parsed)
    except Exception as exc:
        base.log_scraper_run(db_path, "draw_tennisexplorer", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise


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
