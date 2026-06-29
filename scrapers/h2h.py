"""Head-to-head scraper (tennisexplorer.com)."""
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import db
import name_resolver
from scrapers import base

H2H_URL_TEMPLATE = "https://www.tennisexplorer.com/head-to-head/?p1={p1}&p2={p2}"


def parse_h2h_html(html):
    soup = BeautifulSoup(html, "html.parser")
    container = soup.find("div", class_="head2head")
    if container is None:
        return None
    result = container.find("div", class_="result")
    if result is None:
        return None
    player1 = result.find("span", class_="player1")
    player2 = result.find("span", class_="player2")
    scores = result.find_all("span", class_="score")
    if not (player1 and player2 and len(scores) == 2):
        return None
    try:
        wins1 = int(scores[0].get_text(strip=True))
        wins2 = int(scores[1].get_text(strip=True))
    except ValueError:
        return None
    return {
        "player1": player1.get_text(strip=True),
        "player2": player2.get_text(strip=True),
        "player1_wins": wins1,
        "player2_wins": wins2,
    }


def _store_h2h(db_path, name1, name2, wins1, wins2):
    canonical1 = name_resolver.resolve(db_path, name1, source="tennisexplorer") or name1
    canonical2 = name_resolver.resolve(db_path, name2, source="tennisexplorer") or name2
    id1 = db.upsert_player(db_path, name=canonical1)
    id2 = db.upsert_player(db_path, name=canonical2)

    if id1 < id2:
        a_id, b_id, a_wins, b_wins = id1, id2, wins1, wins2
    else:
        a_id, b_id, a_wins, b_wins = id2, id1, wins2, wins1

    with db.get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO h2h (player_a_id, player_b_id, a_wins, b_wins)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(player_a_id, player_b_id)
               DO UPDATE SET a_wins = excluded.a_wins, b_wins = excluded.b_wins""",
            (a_id, b_id, a_wins, b_wins),
        )


def run_for_pair(db_path, slug1, slug2, session=None):
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()
    url = H2H_URL_TEMPLATE.format(p1=slug1, p2=slug2)

    def _fetch():
        response = session.get(url, timeout=10)
        response.raise_for_status()
        return response.text

    try:
        html = base.fetch_with_retry(_fetch)
        parsed = parse_h2h_html(html)
        if parsed is None:
            base.log_scraper_run(db_path, "h2h", "failure", rows_fetched=0,
                                  error_message="parse_h2h_html returned None", started_at=started_at)
            return 0
        _store_h2h(db_path, parsed["player1"], parsed["player2"],
                   parsed["player1_wins"], parsed["player2_wins"])
        base.log_scraper_run(db_path, "h2h", "success", rows_fetched=1, started_at=started_at)
        base.jittered_sleep(1.5, 4.2)
        return 1
    except Exception as exc:
        base.log_scraper_run(db_path, "h2h", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise
