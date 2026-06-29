"""Grass vs total win% scraper (tennisexplorer.com)."""
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import db
from scrapers import base


def parse_surface_stats_html(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="surface-stats")
    if table is None:
        return None

    surfaces = {}
    for row in table.find_all("tr"):
        surface_cell = row.find("td", class_="surface")
        wins_cell = row.find("td", class_="wins")
        losses_cell = row.find("td", class_="losses")
        if not (surface_cell and wins_cell and losses_cell):
            continue
        try:
            wins = int(wins_cell.get_text(strip=True))
            losses = int(losses_cell.get_text(strip=True))
        except ValueError:
            continue
        surfaces[surface_cell.get_text(strip=True)] = {"wins": wins, "losses": losses}

    if "Grass" not in surfaces:
        return None

    total_wins = sum(s["wins"] for s in surfaces.values())
    total_matches = sum(s["wins"] + s["losses"] for s in surfaces.values())
    grass_matches = surfaces["Grass"]["wins"] + surfaces["Grass"]["losses"]

    if total_matches == 0 or grass_matches == 0:
        return None

    return {
        "grass_winrate": round(surfaces["Grass"]["wins"] / grass_matches, 4),
        "total_winrate": round(total_wins / total_matches, 4),
        "matches_played": total_matches,
    }


def store_surface_stats(db_path, player_id, parsed):
    with db.get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO grass_stats (player_id, grass_winrate, total_winrate, matches_played)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(player_id)
               DO UPDATE SET grass_winrate = excluded.grass_winrate,
                             total_winrate = excluded.total_winrate,
                             matches_played = excluded.matches_played""",
            (player_id, parsed["grass_winrate"], parsed["total_winrate"], parsed["matches_played"]),
        )


def run_for_player(db_path, player_id, profile_url, session=None):
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()

    def _fetch():
        response = session.get(profile_url, timeout=10)
        response.raise_for_status()
        return response.text

    try:
        html = base.fetch_with_retry(_fetch)
        parsed = parse_surface_stats_html(html)
        if parsed is None:
            base.log_scraper_run(db_path, "surface_stats", "failure", rows_fetched=0,
                                  error_message="parse_surface_stats_html returned None", started_at=started_at)
            return 0
        store_surface_stats(db_path, player_id, parsed)
        base.log_scraper_run(db_path, "surface_stats", "success", rows_fetched=1, started_at=started_at)
        base.jittered_sleep(1.5, 4.2)
        return 1
    except Exception as exc:
        base.log_scraper_run(db_path, "surface_stats", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise
