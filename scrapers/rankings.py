"""ATP/WTA rankings scraper (tennisexplorer.com)."""
from datetime import datetime, timezone

from bs4 import BeautifulSoup

import db
import name_resolver
from scrapers import base

RANKINGS_URL = "https://www.tennisexplorer.com/ranking/atp-men/"


def parse_rankings_html(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="result")
    if table is None:
        return []
    results = []
    for row in table.find_all("tr"):
        if "head" in (row.get("class") or []):
            continue
        cells = row.find_all("td")
        if len(cells) < 2:
            continue
        try:
            rank = int(cells[0].get_text(strip=True))
        except ValueError:
            continue
        name_link = cells[1].find("a")
        name = name_link.get_text(strip=True) if name_link else cells[1].get_text(strip=True)
        if not name:
            continue
        results.append({"rank": rank, "name": name})
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
