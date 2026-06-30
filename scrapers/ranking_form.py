"""
ATP ranking and recent tournament form scraper (tennisexplorer.com player profiles).

Extracts:
- Ranking position (1-2000)
- Ranking points
- Wins/losses in last 6 weeks
- Tournament stats: titles, finals reached
"""
from datetime import datetime, timedelta
from urllib.parse import quote

from bs4 import BeautifulSoup

from scrapers import base

# Wimbledon 2026 start date
WIMBLEDON_DATE = datetime(2026, 7, 1)
# 6 weeks before Wimbledon
FORM_CUTOFF_DATE = WIMBLEDON_DATE - timedelta(weeks=6)


def extract_ranking_position(soup):
    """Extract ranking position from player profile HTML.

    Returns:
        int: Ranking position (1-2000), or 2000 if not found.
    """
    try:
        ranking_div = soup.find("div", class_="ranking")
        if ranking_div:
            value_span = ranking_div.find("span", class_="value")
            if value_span:
                rank_text = value_span.get_text(strip=True)
                rank = int(rank_text)
                if 1 <= rank <= 2000:
                    return rank
    except (ValueError, AttributeError):
        pass
    return 2000


def extract_ranking_points(soup):
    """Extract ranking points from player profile HTML.

    Returns:
        int: Ranking points, or 0 if not found.
    """
    try:
        points_div = soup.find("div", class_="ranking-points")
        if points_div:
            value_span = points_div.find("span", class_="value")
            if value_span:
                points_text = value_span.get_text(strip=True)
                points = int(points_text)
                return max(0, points)
    except (ValueError, AttributeError):
        pass
    return 0


def _parse_date(date_str):
    """Parse date string in format YYYY-MM-DD.

    Returns:
        datetime or None: Parsed date or None if parse fails.
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str.strip(), "%Y-%m-%d")
    except ValueError:
        return None


def _extract_recent_form(soup):
    """Extract wins/losses and tournament stats from recent tournament table.

    Returns:
        dict: {
            "tournaments_played": int,
            "wins": int,
            "losses": int,
            "titles": int,
            "finals_reached": int,
            "last_tournament_date": str or None (YYYY-MM-DD)
        }
    """
    result = {
        "tournaments_played": 0,
        "wins": 0,
        "losses": 0,
        "titles": 0,
        "finals_reached": 0,
        "last_tournament_date": None,
    }

    try:
        # Try to find form statistics section first
        form_stats = soup.find("div", class_="form-stats")
        if form_stats:
            stats_divs = form_stats.find_all("div", class_="stat")
            for stat_div in stats_divs:
                label = stat_div.find("span", class_="label")
                value = stat_div.find("span", class_="value")
                if label and value:
                    label_text = label.get_text(strip=True).lower()
                    value_text = value.get_text(strip=True)
                    try:
                        val = int(value_text)
                        if "tournament" in label_text and "played" in label_text:
                            result["tournaments_played"] = val
                        elif "wins" in label_text:
                            result["wins"] = val
                        elif "losses" in label_text:
                            result["losses"] = val
                        elif "titles" in label_text:
                            result["titles"] = val
                        elif "finals" in label_text:
                            result["finals_reached"] = val
                    except ValueError:
                        pass

            # Get last tournament date from form statistics if available
            last_date_elem = form_stats.find("div", class_="last-tournament-date")
            if last_date_elem:
                date_value = last_date_elem.find("span", class_="value")
                if date_value:
                    date_text = date_value.get_text(strip=True)
                    parsed = _parse_date(date_text)
                    if parsed:
                        result["last_tournament_date"] = date_text

        # Parse recent tournament table for form data
        table = soup.find("table", class_="player-stats")
        if table:
            last_date = None
            for row in table.find_all("tr"):
                if "head" in (row.get("class") or []):
                    continue

                tds = row.find_all("td")
                if len(tds) < 4:
                    continue

                # Extract date from second column
                date_text = tds[1].get_text(strip=True)
                date_obj = _parse_date(date_text)

                # Check if tournament is within form cutoff
                if date_obj and date_obj >= FORM_CUTOFF_DATE:
                    result["tournaments_played"] += 1
                    if not last_date or date_obj > last_date:
                        last_date = date_obj

                    # Extract W-L record from fourth column
                    wl_text = tds[3].get_text(strip=True)
                    try:
                        w, l = wl_text.split("-")
                        result["wins"] += int(w)
                        result["losses"] += int(l)
                    except (ValueError, IndexError):
                        pass

                    # Extract result from third column
                    result_text = tds[2].get_text(strip=True).lower()
                    if "winner" in result_text or "champion" in result_text:
                        result["titles"] += 1
                    elif "final" in result_text:
                        result["finals_reached"] += 1

            if last_date:
                result["last_tournament_date"] = last_date.strftime("%Y-%m-%d")

    except (AttributeError, IndexError):
        pass

    return result


def extract_ranking_and_form(player_name, session=None):
    """
    Extract ATP ranking and recent tournament form for a player.

    Args:
        player_name (str): Player name to search for
        session: Optional requests.Session instance for testing

    Returns:
        dict or None: Dictionary with keys:
            - ranking_position: int (1-2000)
            - ranking_points: int
            - tournaments_played: int (last 6 weeks)
            - wins: int (last 6 weeks)
            - losses: int (last 6 weeks)
            - titles: int (last 6 weeks)
            - finals_reached: int (last 6 weeks)
            - last_tournament_date: str (YYYY-MM-DD) or None

        Returns None if player not found or network error occurs.
    """
    session = session or base.get_session()

    # Build tennisexplorer.com search URL
    # Note: this is a simplified search; real implementation may need more robust URL construction
    search_url = f"https://www.tennisexplorer.com/search/?q={quote(player_name)}"

    try:
        # Fetch player profile page
        response = session.get(search_url, timeout=10)
        response.raise_for_status()
        html = response.text

        soup = BeautifulSoup(html, "html.parser")

        # Verify player profile was found (basic check)
        if not soup.find("div", class_="player-profile"):
            return None

        # Extract ranking information
        ranking_position = extract_ranking_position(soup)
        ranking_points = extract_ranking_points(soup)

        # Extract recent form
        form_data = _extract_recent_form(soup)

        return {
            "ranking_position": ranking_position,
            "ranking_points": ranking_points,
            "tournaments_played": form_data["tournaments_played"],
            "wins": form_data["wins"],
            "losses": form_data["losses"],
            "titles": form_data["titles"],
            "finals_reached": form_data["finals_reached"],
            "last_tournament_date": form_data["last_tournament_date"],
        }

    except Exception as exc:
        # Return None on error instead of raising
        print(f"Warning: Failed to extract ranking and form for {player_name}: {exc}")
        return None
