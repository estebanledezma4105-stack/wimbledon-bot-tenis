"""ATP/WTA rankings scraper (tennisexplorer.com)."""
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import db
import name_resolver
from scrapers import base

RANKINGS_URL = "https://www.tennisexplorer.com/ranking/atp-men/"


def _find_rankings_table(soup):
    """tennisexplorer.com renders several <table class="result"> elements per
    page (a date picker, betting-odds tables, "interesting matches" tables).
    The actual rankings table is identified by its header row's first cell
    reading "Rank" — relying on table order or row count is unreliable."""
    for table in soup.find_all("table", class_="result"):
        header = table.find("tr", class_="head")
        if header is None:
            continue
        first_cell = header.find("td")
        if first_cell and first_cell.get_text(strip=True).lower() == "rank":
            return table
    return None


def _normalize_name(raw_name):
    """tennisexplorer lists names as "Lastname Firstname". Swap two-token
    names to the conventional "Firstname Lastname" order so they line up
    with the seed alias dictionary; leave multi-word names as scraped since
    the split point is ambiguous (e.g. multi-word surnames)."""
    tokens = raw_name.split()
    if len(tokens) == 2:
        return f"{tokens[1]} {tokens[0]}"
    return raw_name


def parse_rankings_html(html):
    soup = BeautifulSoup(html, "html.parser")
    table = _find_rankings_table(soup)
    if table is None:
        return []
    results = []
    for row in table.find_all("tr"):
        if "head" in (row.get("class") or []):
            continue
        name_cell = row.find("td", class_="t-name")
        rank_cell = row.find("td", class_="rank")
        if name_cell is None or rank_cell is None:
            continue
        try:
            rank = int(rank_cell.get_text(strip=True).rstrip("."))
        except ValueError:
            continue
        raw_name = name_cell.get_text(strip=True)
        if not raw_name:
            continue
        results.append({"rank": rank, "name": _normalize_name(raw_name)})
    return results


def run(db_path, session=None):
    started_at = datetime.now(timezone.utc).isoformat()
    session = session or base.get_session()

    def _fetch():
        response = session.get(RANKINGS_URL, timeout=10)
        response.raise_for_status()
        return response.text

    try:
        html = base.fetch_with_retry(_fetch)
        parsed = parse_rankings_html(html)
        rows_written = 0
        for entry in parsed:
            canonical = name_resolver.resolve(db_path, entry["name"], source="tennisexplorer")
            name_to_use = canonical or entry["name"]
            db.upsert_player(db_path, name=name_to_use, ranking=entry["rank"])
            rows_written += 1
            base.jittered_sleep(0.2, 0.6)
        base.log_scraper_run(db_path, "rankings", "success", rows_fetched=rows_written, started_at=started_at)
        return rows_written
    except Exception as exc:
        base.log_scraper_run(db_path, "rankings", "failure", rows_fetched=0, error_message=str(exc), started_at=started_at)
        raise
