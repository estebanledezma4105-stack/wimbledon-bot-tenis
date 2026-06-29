"""Head-to-head scraper (tennisexplorer.com).

The original implementation guessed at a `/head-to-head/?p1=...&p2=...` URL
and a `div.head2head` HTML structure that don't exist on the real site
(confirmed: that URL 404s). The real flow, found by reading tennisexplorer's
own main.js.php (`searchLoad`/`mutualSubmit` functions):

1. Resolve each player's URL slug via the AJAX player search endpoint
   `/res/ajax/search.php?s={query}&t=p&c=` (returns JSON `{"links": [...]}`).
   Searching with a full "Firstname Lastname" query disambiguates correctly
   even for same-surname players (e.g. "Alexander Zverev" doesn't return
   Mischa Zverev) — verified against the live site.
2. Fetch `/mutual/{slug1}/{slug2}/`, which renders the real match-by-match
   history table (header row literally reads "Year").
3. Each historical match is two consecutive `<tr>` rows: the first row
   (with a `td.first` year cell) is always the WINNER of that match, the
   second row is the loser — verified against several real matches.
"""
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import db
import name_resolver
from scrapers import base

SEARCH_ENDPOINT = "https://www.tennisexplorer.com/res/ajax/search.php"
MUTUAL_URL_TEMPLATE = "https://www.tennisexplorer.com/mutual/{slug1}/{slug2}/"


def search_player_slug(session, name, sex="man"):
    """Returns the tennisexplorer URL slug for a player name, or None if no
    (or still-ambiguous) result. Searching with a full "Firstname Lastname"
    query disambiguates same-surname players (e.g. the Zverev siblings).
    `sex` filters cross-gender surname collisions (e.g. a man and woman both
    surnamed "Hurkacz") before falling back to treating multiple remaining
    results as ambiguous — pass sex=None to skip this filter."""
    response = session.get(SEARCH_ENDPOINT, params={"s": name, "t": "p", "c": ""}, timeout=10)
    response.raise_for_status()
    payload = response.json()
    links = payload.get("links", [])
    if sex is not None and len(links) > 1:
        sex_filtered = [link for link in links if link.get("sex") == sex]
        if len(sex_filtered) == 1:
            return sex_filtered[0]["url"]
    return links[0]["url"] if len(links) == 1 else None


def _find_h2h_table(soup):
    for table in soup.find_all("table", class_="result"):
        header = table.find("tr", class_="head")
        if header is None:
            continue
        first_cell = header.find(["td", "th"])
        if first_cell and first_cell.get_text(strip=True).lower() == "year":
            return table
    return None


def parse_h2h_html(html):
    """Returns a list of {"winner": label, "loser": label} dicts, one per
    historical match, where label is tennisexplorer's short form (e.g.
    "Sinner J.")."""
    soup = BeautifulSoup(html, "html.parser")
    table = _find_h2h_table(soup)
    if table is None:
        return []

    results = []
    pending = None  # (name, sets_won) from the first row of the current match pair
    for row in table.find_all("tr"):
        if "head" in (row.get("class") or []):
            continue
        name_cells = row.find_all("td", class_="t-name")
        result_cell = row.find("td", class_="result")
        if not name_cells or result_cell is None:
            continue
        try:
            sets_won = int(result_cell.get_text(strip=True))
        except ValueError:
            continue
        name = name_cells[-1].get_text(strip=True)
        is_first_row_of_pair = row.find("td", class_="first") is not None

        if is_first_row_of_pair:
            pending = (name, sets_won)
        elif pending is not None:
            winner, loser = (pending[0], name) if pending[1] > sets_won else (name, pending[0])
            results.append({"winner": winner, "loser": loser})
            pending = None
    return results


def _label_matches_canonical(label, canonical_name):
    """tennisexplorer match-history labels are short forms like "Sinner J."
    Checks whether any multi-letter token in the label (skipping single-letter
    initials) appears among the canonical name's tokens."""
    canonical_tokens = set(canonical_name.lower().split())
    label_tokens = [t.rstrip(".") for t in label.lower().split() if len(t.rstrip(".")) > 1]
    return any(token in canonical_tokens for token in label_tokens)


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


def run_for_pair(db_path, name1, name2, session=None):
    """name1/name2 are canonical "Firstname Lastname" player names already
    known in the players table (or resolvable via name_resolver)."""
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()

    try:
        slug1 = search_player_slug(session, name1)
        slug2 = search_player_slug(session, name2)
        if slug1 is None or slug2 is None:
            base.log_scraper_run(db_path, "h2h", "failure", rows_fetched=0,
                                  error_message=f"could not resolve slug for {name1!r} or {name2!r}",
                                  started_at=started_at)
            return 0

        def _fetch():
            response = session.get(
                MUTUAL_URL_TEMPLATE.format(slug1=slug1, slug2=slug2), timeout=10
            )
            response.raise_for_status()
            return response.text

        html = base.fetch_with_retry(_fetch)
        matches = parse_h2h_html(html)

        wins1 = sum(1 for m in matches if _label_matches_canonical(m["winner"], name1))
        wins2 = sum(1 for m in matches if _label_matches_canonical(m["winner"], name2))

        _store_h2h(db_path, name1, name2, wins1, wins2)
        base.log_scraper_run(db_path, "h2h", "success", rows_fetched=len(matches), started_at=started_at)
        base.jittered_sleep(1.5, 4.2)
        return len(matches)
    except Exception as exc:
        base.log_scraper_run(db_path, "h2h", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise
