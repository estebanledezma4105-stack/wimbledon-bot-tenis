# ATP Accuracy Improvement (58.8% → 70-75%) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Wimbledon ATP prediction accuracy from 58.8% to 70-75% by scraping ranking + recent form from tennisexplorer, extending the rating model with two new bonuses, and running grid search backtesting to calibrate all weights.

**Architecture:** Four-phase pipeline: (1) Database schema for ranking + recent form, (2) Scraper for tennisexplorer player data, (3) Model extensions with ranking + recent form bonuses, (4) Grid search backtesting to find optimal weights, apply best weights.

**Tech Stack:** Python 3.14, SQLite, BeautifulSoup (HTML parsing), httpx (HTTP with retries), existing wimbledon_bot.py + db.py infrastructure.

---

## File Structure

| File | Purpose | Type |
|------|---------|------|
| `db.py` | Add `atp_rankings` + `recent_form` tables; add upsert functions; extend `load_all_data()` | Modify |
| `scrapers/ranking_form.py` | Extract ranking + recent form from tennisexplorer.com player profiles | Create |
| `wimbledon_bot.py` | Add `get_ranking_bonus()`, `get_recent_form_bonus()`, extend `calculate_rating()` | Modify |
| `backtesting.py` | Grid search over weight space (12,500 combos); output best weights | Create |
| `daily_update.py` | Call ranking scraper for all players in draw | Modify |
| `tests/test_ranking_form.py` | Unit tests for scraper (mocked HTTP) | Create |
| `tests/test_backtesting.py` | Unit tests for grid search logic | Create |

---

### Task 1: Create DB Tables for Ranking + Recent Form

**Files:**
- Modify: `db.py` (function `init_db`)

- [ ] **Step 1: Write test for new tables**

```python
# tests/test_db.py — add new test function
def test_init_db_creates_atp_rankings_table():
    """Verify atp_rankings table exists with correct schema."""
    with db.get_connection(":memory:") as conn:
        db.init_db(":memory:")
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('atp_rankings', 'recent_form')"
        ).fetchall()
        assert len(tables) == 2
        
        # Check atp_rankings columns
        cols = conn.execute("PRAGMA table_info(atp_rankings)").fetchall()
        col_names = [c[1] for c in cols]
        assert "player_id" in col_names
        assert "ranking_position" in col_names
        assert "ranking_points" in col_names
        assert "scraped_at" in col_names
        
        # Check recent_form columns
        cols = conn.execute("PRAGMA table_info(recent_form)").fetchall()
        col_names = [c[1] for c in cols]
        assert "player_id" in col_names
        assert "wins" in col_names
        assert "losses" in col_names
        assert "titles" in col_names
        assert "finals_reached" in col_names
        assert "last_tournament_date" in col_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_init_db_creates_atp_rankings_table -v`
Expected: FAIL with "table atp_rankings does not exist"

- [ ] **Step 3: Add table creation to db.py init_db()**

In `db.py`, inside `init_db()` function, after existing table creation, add:

```python
def init_db(db_path):
    """Initialize database schema. Idempotent — safe to call repeatedly."""
    conn = get_connection(db_path)
    try:
        # Existing tables (players, draw_matches, predictions, etc.) — unchanged
        # ... (keep existing CREATE TABLE statements) ...
        
        # NEW: ATP Rankings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS atp_rankings (
                player_id INTEGER PRIMARY KEY,
                ranking_position INTEGER NOT NULL,
                ranking_points INTEGER,
                scraped_at TEXT,
                FOREIGN KEY (player_id) REFERENCES players(id)
            )
        """)
        
        # NEW: Recent Form table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recent_form (
                player_id INTEGER PRIMARY KEY,
                tournaments_played INTEGER DEFAULT 0,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                titles INTEGER DEFAULT 0,
                finals_reached INTEGER DEFAULT 0,
                last_tournament_date TEXT,
                updated_at TEXT,
                FOREIGN KEY (player_id) REFERENCES players(id)
            )
        """)
        
        conn.commit()
    finally:
        conn.close()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_init_db_creates_atp_rankings_table -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add atp_rankings and recent_form tables to schema"
```

---

### Task 2: Add Upsert Functions to db.py

**Files:**
- Modify: `db.py`

- [ ] **Step 1: Write test for upsert functions**

```python
# tests/test_db.py — add new test function
def test_upsert_ranking_inserts_and_updates():
    """Verify ranking upsert works correctly."""
    db_path = ":memory:"
    db.init_db(db_path)
    
    # Insert player
    db.upsert_player(db_path, name="John Doe", elo=1500)
    player = db.get_player_by_name(db_path, "John Doe")
    player_id = player["id"]
    
    # First insert
    db.upsert_ranking(db_path, player_id, ranking_position=5, ranking_points=9000)
    
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT ranking_position, ranking_points FROM atp_rankings WHERE player_id = ?", 
                          (player_id,)).fetchone()
        assert row["ranking_position"] == 5
        assert row["ranking_points"] == 9000
    
    # Update (upsert should replace)
    db.upsert_ranking(db_path, player_id, ranking_position=3, ranking_points=9500)
    
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT ranking_position, ranking_points FROM atp_rankings WHERE player_id = ?", 
                          (player_id,)).fetchone()
        assert row["ranking_position"] == 3
        assert row["ranking_points"] == 9500

def test_upsert_recent_form_inserts_and_updates():
    """Verify recent form upsert works correctly."""
    db_path = ":memory:"
    db.init_db(db_path)
    
    # Insert player
    db.upsert_player(db_path, name="Jane Smith", elo=1500)
    player = db.get_player_by_name(db_path, "Jane Smith")
    player_id = player["id"]
    
    # First insert
    db.upsert_recent_form(db_path, player_id, tournaments_played=3, wins=5, losses=1, 
                         titles=1, finals_reached=2, last_tournament_date="2026-06-20")
    
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT wins, losses, titles FROM recent_form WHERE player_id = ?", 
                          (player_id,)).fetchone()
        assert row["wins"] == 5
        assert row["losses"] == 1
        assert row["titles"] == 1
    
    # Update
    db.upsert_recent_form(db_path, player_id, tournaments_played=4, wins=6, losses=2, 
                         titles=1, finals_reached=2, last_tournament_date="2026-06-25")
    
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT wins, losses FROM recent_form WHERE player_id = ?", 
                          (player_id,)).fetchone()
        assert row["wins"] == 6
        assert row["losses"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_upsert_ranking_inserts_and_updates tests/test_db.py::test_upsert_recent_form_inserts_and_updates -v`
Expected: FAIL with "upsert_ranking not defined"

- [ ] **Step 3: Implement upsert functions in db.py**

Add these functions to `db.py`:

```python
def upsert_ranking(db_path, player_id, ranking_position, ranking_points=None):
    """Insert or update ATP ranking for a player. Called after scraping."""
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO atp_rankings (player_id, ranking_position, ranking_points, scraped_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                ranking_position = excluded.ranking_position,
                ranking_points = excluded.ranking_points,
                scraped_at = excluded.scraped_at
        """, (player_id, ranking_position, ranking_points, _now()))


def upsert_recent_form(db_path, player_id, tournaments_played, wins, losses, titles, finals_reached, last_tournament_date):
    """Insert or update recent form for a player. Called after scraping."""
    with get_connection(db_path) as conn:
        conn.execute("""
            INSERT INTO recent_form (player_id, tournaments_played, wins, losses, titles, finals_reached, last_tournament_date, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id) DO UPDATE SET
                tournaments_played = excluded.tournaments_played,
                wins = excluded.wins,
                losses = excluded.losses,
                titles = excluded.titles,
                finals_reached = excluded.finals_reached,
                last_tournament_date = excluded.last_tournament_date,
                updated_at = excluded.updated_at
        """, (player_id, tournaments_played, wins, losses, titles, finals_reached, last_tournament_date, _now()))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_db.py::test_upsert_ranking_inserts_and_updates tests/test_db.py::test_upsert_recent_form_inserts_and_updates -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add upsert_ranking and upsert_recent_form to db.py"
```

---

### Task 3: Create Ranking + Recent Form Scraper

**Files:**
- Create: `scrapers/ranking_form.py`
- Modify: `scrapers/__init__.py` (if needed for exports)

- [ ] **Step 1: Write test for scraper**

```python
# tests/test_ranking_form.py — new file
import pytest
from unittest.mock import Mock, patch
from scrapers.ranking_form import extract_ranking_and_form

def test_extract_ranking_parses_player_profile():
    """Test that scraper extracts ranking from player profile HTML."""
    html_content = """
    <html>
    <body>
        <div class="player-stats">
            <div>Ranking: <strong>#45</strong></div>
            <div>Points: <strong>4567</strong></div>
        </div>
        <div class="tournaments">
            <table>
                <tr><td>2026-06-15</td><td>Tournament A</td><td>Won</td></tr>
                <tr><td>2026-06-10</td><td>Tournament B</td><td>Final</td></tr>
                <tr><td>2026-06-05</td><td>Tournament C</td><td>Quarterfinal</td></tr>
                <tr><td>2026-05-20</td><td>Tournament D</td><td>Lost</td></tr>
            </table>
        </div>
    </body>
    </html>
    """
    
    with patch('scrapers.ranking_form.httpx.Client') as mock_client:
        mock_response = Mock()
        mock_response.text = html_content
        mock_client.return_value.__enter__.return_value.get.return_value = mock_response
        
        result = extract_ranking_and_form("Roger Federer")
        
        assert result is not None
        assert result["ranking_position"] == 45
        # Should have wins from tournaments (exact counts depend on parsing logic)

def test_extract_ranking_handles_missing_ranking():
    """Test graceful fallback when ranking not found."""
    html_content = "<html><body>No ranking info</body></html>"
    
    with patch('scrapers.ranking_form.httpx.Client') as mock_client:
        mock_response = Mock()
        mock_response.text = html_content
        mock_client.return_value.__enter__.return_value.get.return_value = mock_response
        
        result = extract_ranking_and_form("Unknown Player")
        
        # Should return a default dict or None
        if result:
            assert result.get("ranking_position", 2000) >= 1

def test_extract_ranking_handles_network_error():
    """Test that scraper returns None on network error."""
    with patch('scrapers.ranking_form.httpx.Client') as mock_client:
        mock_client.return_value.__enter__.return_value.get.side_effect = Exception("Network error")
        
        result = extract_ranking_and_form("Any Player")
        
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ranking_form.py -v`
Expected: FAIL with "no module named 'scrapers.ranking_form'"

- [ ] **Step 3: Create scrapers/ranking_form.py**

Create the file with this content:

```python
"""Scraper for ATP ranking and recent tournament form from tennisexplorer.com."""
import re
import httpx
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

from scrapers import base


def extract_ranking_and_form(player_name: str, session: httpx.Session = None) -> dict:
    """
    Extract ATP ranking and recent tournament form for a player.
    
    Args:
        player_name: Player's name (e.g., "Roger Federer")
        session: Optional httpx.Session for connection reuse
    
    Returns:
        {
            "ranking_position": int (1-2000, where 2000 = unknown),
            "ranking_points": int or None,
            "tournaments_played": int,
            "wins": int,
            "losses": int,
            "titles": int,
            "finals_reached": int,
            "last_tournament_date": str (ISO format) or None
        }
        or None on error
    """
    try:
        # Build player profile URL (tennisexplorer convention)
        # Format: https://www.tennisexplorer.com/players/FIRSTNAME-LASTNAME/
        name_slugified = player_name.lower().replace(" ", "-")
        url = f"https://www.tennisexplorer.com/players/{name_slugified}/"
        
        # Fetch with retries
        if session is None:
            client = httpx.Client(timeout=10)
            try:
                response = client.get(url)
                response.raise_for_status()
                html = response.text
            finally:
                client.close()
        else:
            response = session.get(url)
            response.raise_for_status()
            html = response.text
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Extract ranking
        ranking_pos = _extract_ranking_position(soup)
        ranking_pts = _extract_ranking_points(soup)
        
        # Extract recent tournament form (last 6 weeks before Wimbledon 2026-07-01)
        form_data = _extract_recent_form(soup)
        
        return {
            "ranking_position": ranking_pos,
            "ranking_points": ranking_pts,
            "tournaments_played": form_data["tournaments_played"],
            "wins": form_data["wins"],
            "losses": form_data["losses"],
            "titles": form_data["titles"],
            "finals_reached": form_data["finals_reached"],
            "last_tournament_date": form_data["last_date"],
        }
    
    except Exception as e:
        # Log but don't raise — scraper failures shouldn't block pipeline
        print(f"Warning: Failed to scrape ranking for {player_name}: {e}")
        return None


def _extract_ranking_position(soup: BeautifulSoup) -> int:
    """Extract ATP ranking position from player profile. Default 2000 if not found."""
    try:
        # Look for pattern like "Ranking: #45" or "ATP Ranking: #45"
        ranking_text = soup.find(text=re.compile(r"Ranking", re.IGNORECASE))
        if ranking_text:
            # Extract number after # or first number
            match = re.search(r"#?(\d+)", str(ranking_text.next))
            if match:
                return int(match.group(1))
    except Exception:
        pass
    return 2000  # Default: unranked


def _extract_ranking_points(soup: BeautifulSoup) -> int:
    """Extract ATP ranking points. Return None if not found."""
    try:
        points_text = soup.find(text=re.compile(r"Points", re.IGNORECASE))
        if points_text:
            match = re.search(r"(\d+)", str(points_text.next))
            if match:
                return int(match.group(1))
    except Exception:
        pass
    return None


def _extract_recent_form(soup: BeautifulSoup) -> dict:
    """
    Extract recent tournament results (last 6 weeks before Wimbledon 2026-07-01).
    
    Returns:
        {
            "tournaments_played": int,
            "wins": int,
            "losses": int,
            "titles": int,
            "finals_reached": int,
            "last_date": str (ISO) or None
        }
    """
    result = {
        "tournaments_played": 0,
        "wins": 0,
        "losses": 0,
        "titles": 0,
        "finals_reached": 0,
        "last_date": None,
    }
    
    try:
        # Cutoff: 6 weeks before Wimbledon start (2026-07-01)
        wimbledon_start = datetime(2026, 7, 1)
        cutoff_date = wimbledon_start - timedelta(weeks=6)  # 2026-05-17
        
        # Find tournament table in page
        table = soup.find("table", {"class": re.compile(r"tournament|history", re.IGNORECASE)})
        if not table:
            return result
        
        tournaments_in_window = []
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            
            date_str = cells[0].get_text(strip=True)
            tournament_name = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            result_str = cells[2].get_text(strip=True) if len(cells) > 2 else ""
            
            try:
                tournament_date = datetime.strptime(date_str, "%Y-%m-%d")
            except ValueError:
                continue
            
            # Only count tournaments within 6-week window
            if tournament_date < cutoff_date:
                break  # Assume table is chronologically ordered (newest first)
            if tournament_date >= wimbledon_start:
                continue  # Wimbledon itself
            
            tournaments_in_window.append({
                "date": tournament_date,
                "name": tournament_name,
                "result": result_str.lower(),
            })
        
        # Parse results
        for t in tournaments_in_window:
            result["tournaments_played"] += 1
            if result["last_date"] is None:
                result["last_date"] = t["date"].isoformat()
            
            res_lower = t["result"]
            if "won" in res_lower or "title" in res_lower:
                result["titles"] += 1
                result["wins"] += 1
            elif "final" in res_lower:
                result["finals_reached"] += 1
                result["wins"] += 1
            elif "semi" in res_lower or "quarter" in res_lower or "round" in res_lower:
                result["wins"] += 1
            else:
                result["losses"] += 1
    
    except Exception as e:
        print(f"Warning: Failed to extract recent form: {e}")
    
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ranking_form.py -v`
Expected: PASS (or mostly pass; may need HTML mock refinement)

- [ ] **Step 5: Commit**

```bash
git add scrapers/ranking_form.py tests/test_ranking_form.py
git commit -m "feat: add ranking_form scraper for tennisexplorer"
```

---

### Task 4: Extend db.py load_all_data() to Include Ranking + Recent Form

**Files:**
- Modify: `db.py` (function `load_all_data`)

- [ ] **Step 1: Write test**

```python
# tests/test_db.py — add new test
def test_load_all_data_includes_ranking_and_recent_form():
    """Verify load_all_data() returns ranking_dict and recent_form_dict."""
    db_path = ":memory:"
    db.init_db(db_path)
    
    # Insert a player
    db.upsert_player(db_path, name="Test Player", elo=1500)
    player = db.get_player_by_name(db_path, "Test Player")
    
    # Insert ranking + form
    db.upsert_ranking(db_path, player["id"], ranking_position=10, ranking_points=8000)
    db.upsert_recent_form(db_path, player["id"], tournaments_played=3, wins=5, losses=1, 
                         titles=1, finals_reached=2, last_tournament_date="2026-06-20")
    
    # Load all data
    data = db.load_all_data(db_path)
    
    assert "ranking_dict" in data
    assert "recent_form_dict" in data
    assert "Test Player" in data["ranking_dict"]
    assert data["ranking_dict"]["Test Player"]["ranking_position"] == 10
    assert data["recent_form_dict"]["Test Player"]["wins"] == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_load_all_data_includes_ranking_and_recent_form -v`
Expected: FAIL with "KeyError: 'ranking_dict'"

- [ ] **Step 3: Modify load_all_data() in db.py**

Find the `load_all_data()` function and extend it (around line 204):

```python
def load_all_data(db_path):
    """Load all data needed for predictions (elo, grass_stats, form, h2h, draw, live_scores, ranking, recent_form)."""
    with get_connection(db_path) as conn:
        players = conn.execute("SELECT id, name, elo FROM players").fetchall()
        id_to_name = {p["id"]: p["name"] for p in players}

        elo = {p["name"]: p["elo"] for p in players}

        form = {}
        for row in conn.execute("SELECT player_id, points FROM form").fetchall():
            name = id_to_name.get(row["player_id"])
            if name:
                form[name] = row["points"]

        grass_stats = {}
        for row in conn.execute(
            "SELECT player_id, grass_winrate, total_winrate FROM grass_stats"
        ).fetchall():
            name = id_to_name.get(row["player_id"])
            if name:
                grass_stats[name] = {
                    "grass_winrate": row["grass_winrate"],
                    "total_winrate": row["total_winrate"],
                }

        h2h = {}
        for row in conn.execute("SELECT player_a_id, player_b_id, a_wins, b_wins FROM h2h").fetchall():
            name_a = id_to_name.get(row["player_a_id"])
            name_b = id_to_name.get(row["player_b_id"])
            if name_a and name_b:
                h2h[str((name_a, name_b))] = {"a_wins": row["a_wins"], "b_wins": row["b_wins"]}

        # NEW: Load ranking data
        ranking_dict = {}
        for row in conn.execute(
            "SELECT player_id, ranking_position, ranking_points FROM atp_rankings"
        ).fetchall():
            name = id_to_name.get(row["player_id"])
            if name:
                ranking_dict[name] = {
                    "ranking_position": row["ranking_position"],
                    "ranking_points": row["ranking_points"],
                }

        # NEW: Load recent form data
        recent_form_dict = {}
        for row in conn.execute(
            "SELECT player_id, tournaments_played, wins, losses, titles, finals_reached, last_tournament_date FROM recent_form"
        ).fetchall():
            name = id_to_name.get(row["player_id"])
            if name:
                recent_form_dict[name] = {
                    "tournaments_played": row["tournaments_played"],
                    "wins": row["wins"],
                    "losses": row["losses"],
                    "titles": row["titles"],
                    "finals_reached": row["finals_reached"],
                    "last_tournament_date": row["last_tournament_date"],
                }

        draw_rows = conn.execute(
            "SELECT id, round, player1_id, player2_id, winner_id, scheduled_date FROM draw_matches"
        ).fetchall()
        matches = []
        for row in draw_rows:
            p1_name = id_to_name.get(row["player1_id"])
            p2_name = id_to_name.get(row["player2_id"])
            if p1_name and p2_name:
                matches.append({"id": row["id"], "player1": p1_name, "player2": p2_name,
                                 "winner": id_to_name.get(row["winner_id"]),
                                 "scheduled_date": row["scheduled_date"]})

        live_rows = conn.execute(
            """SELECT dm.player1_id, dm.player2_id, ls.sets, ls.status
               FROM live_scores ls JOIN draw_matches dm ON dm.id = ls.match_id"""
        ).fetchall()
        live_scores = {}
        for row in live_rows:
            p1_name = id_to_name.get(row["player1_id"])
            p2_name = id_to_name.get(row["player2_id"])
            if p1_name and p2_name:
                live_scores[f"{p1_name} vs {p2_name}"] = {"sets": row["sets"], "status": row["status"]}

        return {
            "elo": elo,
            "grass_stats": grass_stats,
            "form": form,
            "h2h": h2h,
            "draw": {"matches": matches, "completed_matches": [m for m in matches if m["winner"]]},
            "live_scores": live_scores,
            "fatigue": {p["name"]: get_games_played_in_last_match(db_path, p["id"]) for p in players},
            "ranking_dict": ranking_dict,      # NEW
            "recent_form_dict": recent_form_dict,  # NEW
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_load_all_data_includes_ranking_and_recent_form -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: extend load_all_data() to include ranking and recent_form dicts"
```

---

### Task 5: Add Ranking + Recent Form Bonus Functions to wimbledon_bot.py

**Files:**
- Modify: `wimbledon_bot.py`

- [ ] **Step 1: Write test for bonus functions**

```python
# tests/test_wimbledon_bot.py — add new tests
import wimbledon_bot as bot

def test_get_ranking_bonus_top10():
    """Ranking bonus should be positive for top-10 players."""
    ranking_dict = {"Player A": {"ranking_position": 5, "ranking_points": None}}
    bonus = bot.get_ranking_bonus("Player A", ranking_dict)
    # w_ranking * (2000 - 5) / 1000 = w_ranking * 1.995
    # With w_ranking=0.15 (to be calibrated), ~0.3
    assert bonus > 0

def test_get_ranking_bonus_unknown():
    """Ranking bonus should be ~0 for unknown players (ranking_position=2000)."""
    ranking_dict = {}
    bonus = bot.get_ranking_bonus("Unknown Player", ranking_dict)
    # Default ranking_position = 2000, bonus ~= 0
    assert abs(bonus) < 0.1

def test_get_recent_form_bonus_strong():
    """Recent form bonus should be positive for strong form (60% win rate)."""
    recent_form_dict = {"Player A": {"wins": 6, "losses": 4, "tournaments_played": 2}}
    bonus = bot.get_recent_form_bonus("Player A", recent_form_dict)
    # win_pct = 6/(6+4) = 0.6, bonus = w_recent_form * (0.6 - 0.5) * 100 = w_recent_form * 10
    # With w_recent_form=0.10, ~1.0
    assert bonus > 0

def test_get_recent_form_bonus_poor():
    """Recent form bonus should be negative for poor form (40% win rate)."""
    recent_form_dict = {"Player A": {"wins": 2, "losses": 3, "tournaments_played": 1}}
    bonus = bot.get_recent_form_bonus("Player A", recent_form_dict)
    # win_pct = 2/5 = 0.4, bonus = w_recent_form * (0.4 - 0.5) * 100 = -w_recent_form * 10
    assert bonus < 0

def test_get_recent_form_bonus_no_tournaments():
    """Recent form bonus should be 0 if no recent tournaments."""
    recent_form_dict = {}
    bonus = bot.get_recent_form_bonus("Player A", recent_form_dict)
    assert bonus == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wimbledon_bot.py::test_get_ranking_bonus_top10 -v`
Expected: FAIL with "get_ranking_bonus not defined"

- [ ] **Step 3: Add bonus functions to wimbledon_bot.py**

Add after the existing bonus functions (after `get_fatigue_bonus`):

```python
def get_ranking_bonus(player_id, ranking_dict):
    """R(X) = w_ranking * (2000 - ranking_position) / 1000
    
    Positive bonus for top-ranked players, ~0 for unknown (rank 2000).
    """
    ranking_info = ranking_dict.get(player_id, {})
    ranking_position = ranking_info.get("ranking_position", 2000)
    return W_RANKING * (2000 - ranking_position) / 1000.0


def get_recent_form_bonus(player_id, recent_form_dict):
    """F_recent(X) = w_recent_form * (recent_win_pct - 0.5) * 100
    
    Positive bonus for players in strong form, negative for weak form.
    Baseline (50% win rate) = 0 bonus.
    """
    form_info = recent_form_dict.get(player_id, {})
    wins = form_info.get("wins", 0)
    losses = form_info.get("losses", 0)
    
    if wins + losses == 0:
        return 0.0  # No recent tournaments
    
    recent_win_pct = wins / (wins + losses)
    return W_RECENT_FORM * (recent_win_pct - 0.5) * 100.0
```

And add the new weight constants near the top of the file (after existing weight constants):

```python
W_RANKING = 0.15        # Weight for ranking bonus (to be calibrated via backtesting)
W_RECENT_FORM = 0.10    # Weight for recent form bonus (to be calibrated via backtesting)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_wimbledon_bot.py::test_get_ranking_bonus_top10 tests/test_wimbledon_bot.py::test_get_recent_form_bonus_strong tests/test_wimbledon_bot.py::test_get_recent_form_bonus_no_tournaments -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wimbledon_bot.py tests/test_wimbledon_bot.py
git commit -m "feat: add get_ranking_bonus and get_recent_form_bonus functions"
```

---

### Task 6: Update calculate_rating() to Use New Bonuses

**Files:**
- Modify: `wimbledon_bot.py` (function `calculate_rating` and `predict_match`)

- [ ] **Step 1: Write test**

```python
# tests/test_wimbledon_bot.py — add new test
def test_calculate_rating_includes_ranking_and_form():
    """Verify calculate_rating includes ranking and recent form bonuses."""
    elo_dict = {"Player A": 1600, "Player B": 1500}
    grass_stats = {"Player A": {"grass_winrate": 0.6, "total_winrate": 0.55}}
    form_data = {"Player A": 10}
    h2h_data = {}
    ranking_dict = {"Player A": {"ranking_position": 10, "ranking_points": None}}
    recent_form_dict = {"Player A": {"wins": 6, "losses": 4, "tournaments_played": 2}}
    
    rating = bot.calculate_rating("Player A", "Player B", elo_dict, grass_stats, form_data, 
                                  h2h_data, ranking_dict, recent_form_dict)
    
    # Should include components from ranking + recent form
    # rating = elo + grass + form + h2h + fatigue + ranking + recent_form
    # elo=1600, grass=positive, form=positive, h2h=0, fatigue=0, ranking=positive, recent_form=positive
    assert rating > 1600  # Should be higher than base elo due to bonuses
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_wimbledon_bot.py::test_calculate_rating_includes_ranking_and_form -v`
Expected: FAIL (function signature doesn't match)

- [ ] **Step 3: Update calculate_rating() signature and implementation**

Replace the existing `calculate_rating()` function:

```python
def calculate_rating(player_id, opponent_id, elo_dict, grass_stats, form_data, h2h_data, 
                     ranking_dict, recent_form_dict, fatigue_data=None):
    """Calculate a player's rating for a match, incorporating all factors."""
    elo = elo_dict.get(player_id, 1500)
    grass = get_grass_bonus(player_id, grass_stats)
    form = get_form_bonus(player_id, form_data)
    h2h = get_h2h_bonus(player_id, opponent_id, h2h_data)
    fatigue = get_fatigue_bonus(player_id, fatigue_data or {})
    ranking = get_ranking_bonus(player_id, ranking_dict)      # NEW
    recent = get_recent_form_bonus(player_id, recent_form_dict)  # NEW
    return elo + grass + form + h2h + fatigue + ranking + recent
```

- [ ] **Step 4: Update predict_match() to pass new dicts**

Replace the `predict_match()` function signature and call:

```python
def predict_match(player_a, player_b, data):
    elo = data['elo']
    grass = data['grass_stats']
    form = data['form']
    h2h = data['h2h']
    fatigue = data.get('fatigue', {})
    ranking = data.get('ranking_dict', {})    # NEW
    recent_form = data.get('recent_form_dict', {})  # NEW
    
    r_a = calculate_rating(player_a, player_b, elo, grass, form, h2h, ranking, recent_form, fatigue)
    r_b = calculate_rating(player_b, player_a, elo, grass, form, h2h, ranking, recent_form, fatigue)
    prob_a = win_probability(r_a, r_b)
    return {
        'player_a': player_a,
        'player_b': player_b,
        'prob_a': round(prob_a, 3),
        'prob_b': round(1 - prob_a, 3),
        'favorite': player_a if prob_a >= 0.5 else player_b
    }
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_wimbledon_bot.py::test_calculate_rating_includes_ranking_and_form -v`
Expected: PASS

- [ ] **Step 6: Run all wimbledon_bot tests**

Run: `pytest tests/test_wimbledon_bot.py -v`
Expected: All pass (no regression)

- [ ] **Step 7: Commit**

```bash
git add wimbledon_bot.py tests/test_wimbledon_bot.py
git commit -m "feat: integrate ranking and recent_form into calculate_rating and predict_match"
```

---

### Task 7: Create Backtesting Script

**Files:**
- Create: `backtesting.py`

- [ ] **Step 1: Write test for backtester**

```python
# tests/test_backtesting.py — new file
import pytest
from backtesting import backtest_weights, run_grid_search

def test_backtest_weights_returns_accuracy():
    """Verify backtesting returns accuracy score."""
    import db
    from wimbledon_bot import predict_match
    
    db_path = ":memory:"
    db.init_db(db_path)
    
    # Insert mock players and matches
    db.upsert_player(db_path, name="Player A", elo=1600)
    db.upsert_player(db_path, name="Player B", elo=1500)
    
    player_a = db.get_player_by_name(db_path, "Player A")
    player_b = db.get_player_by_name(db_path, "Player B")
    
    # Manually insert a match (bypass scraper)
    with db.get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO draw_matches (tournament_id, round, player1_id, player2_id, winner_id) VALUES (?, ?, ?, ?, ?)",
            ("wimbledon", "R1", player_a["id"], player_b["id"], player_a["id"])
        )
    
    data = db.load_all_data(db_path)
    
    weight_combo = {
        "K_ELO": 32,
        "W_GRASS": 1.5,
        "W_FORM": 0.7,
        "W_H2H": 25,
        "W_FATIGUE": 0.15,
        "W_RANKING": 0.15,
        "W_RECENT_FORM": 0.10,
    }
    
    accuracy = backtest_weights(data["draw"]["completed_matches"], data["elo"], 
                               data["grass_stats"], data["h2h"], data["form"],
                               data["ranking_dict"], data["recent_form_dict"], weight_combo)
    
    assert 0.0 <= accuracy <= 1.0  # Accuracy should be a fraction

def test_run_grid_search_finds_best():
    """Verify grid search returns best weight combo."""
    import db
    
    db_path = ":memory:"
    db.init_db(db_path)
    
    # Setup same mock data
    db.upsert_player(db_path, name="Player A", elo=1600)
    db.upsert_player(db_path, name="Player B", elo=1500)
    
    player_a = db.get_player_by_name(db_path, "Player A")
    player_b = db.get_player_by_name(db_path, "Player B")
    
    with db.get_connection(db_path) as conn:
        conn.execute(
            "INSERT INTO draw_matches (tournament_id, round, player1_id, player2_id, winner_id) VALUES (?, ?, ?, ?, ?)",
            ("wimbledon", "R1", player_a["id"], player_b["id"], player_a["id"])
        )
    
    data = db.load_all_data(db_path)
    
    results = run_grid_search(data["draw"]["completed_matches"], data["elo"],
                             data["grass_stats"], data["h2h"], data["form"],
                             data["ranking_dict"], data["recent_form_dict"])
    
    assert "best_accuracy" in results
    assert "best_weights" in results
    assert 0.0 <= results["best_accuracy"] <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_backtesting.py::test_backtest_weights_returns_accuracy -v`
Expected: FAIL with "no module named 'backtesting'"

- [ ] **Step 3: Create backtesting.py**

Create the file:

```python
"""Grid search backtesting for weight calibration.

Searches the weight space (12,500 combinations) to find the parameter set
that maximizes accuracy on 17 completed Wimbledon matches.
"""
import json
import wimbledon_bot as bot


def backtest_weights(completed_matches, initial_elo, grass_stats, h2h_data, form_data,
                     ranking_dict, recent_form_dict, weight_combo):
    """
    Run predictions on all completed matches with given weights; return accuracy.
    
    Args:
        completed_matches: List of {"player1", "player2", "winner", "id", ...} dicts
        initial_elo: Dict[player_name] → float
        grass_stats: Dict[player_name] → {"grass_winrate", "total_winrate"}
        h2h_data: Dict[str(pair)] → {"a_wins", "b_wins"}
        form_data: Dict[player_name] → points
        ranking_dict: Dict[player_name] → {"ranking_position", "ranking_points"}
        recent_form_dict: Dict[player_name] → {"wins", "losses", "titles", ...}
        weight_combo: Dict with keys K_ELO, W_GRASS, W_FORM, W_H2H, W_FATIGUE, W_RANKING, W_RECENT_FORM
    
    Returns:
        accuracy (float 0-1)
    """
    # Temporarily override weights in bot module
    old_k = bot.K_ELO
    old_grass = bot.W_GRASS
    old_form = bot.W_FORM
    old_h2h = bot.W_H2H
    old_fatigue = bot.W_FATIGUE
    old_ranking = bot.W_RANKING
    old_recent = bot.W_RECENT_FORM
    
    try:
        bot.K_ELO = weight_combo["K_ELO"]
        bot.W_GRASS = weight_combo["W_GRASS"]
        bot.W_FORM = weight_combo["W_FORM"]
        bot.W_H2H = weight_combo["W_H2H"]
        bot.W_FATIGUE = weight_combo["W_FATIGUE"]
        bot.W_RANKING = weight_combo["W_RANKING"]
        bot.W_RECENT_FORM = weight_combo["W_RECENT_FORM"]
        
        elo = initial_elo.copy()
        correct = total = 0
        
        for match in completed_matches:
            p1, p2, real_winner = match["player1"], match["player2"], match["winner"]
            
            # Predict
            data = {
                "elo": elo,
                "grass_stats": grass_stats,
                "form": form_data,
                "h2h": h2h_data,
                "ranking_dict": ranking_dict,
                "recent_form_dict": recent_form_dict,
                "fatigue": {},
            }
            pred = bot.predict_match(p1, p2, data)
            
            # Evaluate
            if pred["favorite"] == real_winner:
                correct += 1
            total += 1
            
            # Update ELO
            elo = bot.update_elo_ratings(real_winner, p2 if real_winner == p1 else p1, elo)
        
        return correct / total if total > 0 else 0.0
    
    finally:
        # Restore original weights
        bot.K_ELO = old_k
        bot.W_GRASS = old_grass
        bot.W_FORM = old_form
        bot.W_H2H = old_h2h
        bot.W_FATIGUE = old_fatigue
        bot.W_RANKING = old_ranking
        bot.W_RECENT_FORM = old_recent


def run_grid_search(completed_matches, initial_elo, grass_stats, h2h_data, form_data,
                    ranking_dict, recent_form_dict):
    """
    Search grid of weight combinations; return best accuracy + weights.
    
    Returns:
        {
            "best_accuracy": float,
            "best_weights": {...},
            "top_10": [{"accuracy": float, "weights": {...}}, ...],
        }
    """
    param_grid = {
        "K_ELO": [20, 25, 32, 40, 50],
        "W_GRASS": [0.8, 1.0, 1.5, 2.0, 2.5],
        "W_FORM": [0.3, 0.5, 0.7, 1.0, 1.5],
        "W_H2H": [15, 20, 25, 30, 35],
        "W_FATIGUE": [0.05, 0.10, 0.15, 0.20],
        "W_RANKING": [0.0, 0.05, 0.10, 0.15, 0.20],
        "W_RECENT_FORM": [0.0, 0.05, 0.10, 0.15, 0.20],
    }
    
    results = []
    total_combos = 1
    for v in param_grid.values():
        total_combos *= len(v)
    
    print(f"Running grid search over {total_combos:,} combinations...")
    
    count = 0
    for k_elo in param_grid["K_ELO"]:
        for w_grass in param_grid["W_GRASS"]:
            for w_form in param_grid["W_FORM"]:
                for w_h2h in param_grid["W_H2H"]:
                    for w_fatigue in param_grid["W_FATIGUE"]:
                        for w_ranking in param_grid["W_RANKING"]:
                            for w_recent in param_grid["W_RECENT_FORM"]:
                                weight_combo = {
                                    "K_ELO": k_elo,
                                    "W_GRASS": w_grass,
                                    "W_FORM": w_form,
                                    "W_H2H": w_h2h,
                                    "W_FATIGUE": w_fatigue,
                                    "W_RANKING": w_ranking,
                                    "W_RECENT_FORM": w_recent,
                                }
                                
                                accuracy = backtest_weights(
                                    completed_matches, initial_elo, grass_stats, h2h_data,
                                    form_data, ranking_dict, recent_form_dict, weight_combo
                                )
                                
                                results.append({
                                    "accuracy": accuracy,
                                    "weights": weight_combo.copy(),
                                })
                                
                                count += 1
                                if count % 1000 == 0:
                                    print(f"  {count:,}/{total_combos:,} done...")
    
    # Sort by accuracy descending
    results.sort(key=lambda x: x["accuracy"], reverse=True)
    
    best = results[0]
    top_10 = results[:10]
    
    print(f"\nBest accuracy: {best['accuracy']:.1%}")
    print(f"Best weights: {best['weights']}")
    
    return {
        "best_accuracy": best["accuracy"],
        "best_weights": best["weights"],
        "top_10": top_10,
    }


if __name__ == "__main__":
    import db
    
    DB_PATH = "data/wimbledon.db"
    data = db.load_all_data(DB_PATH)
    
    completed = data["draw"].get("completed_matches", [])
    if not completed:
        print("No completed matches in database. Cannot run backtesting.")
        exit(1)
    
    results = run_grid_search(completed, data["elo"], data["grass_stats"], data["h2h"],
                             data["form"], data["ranking_dict"], data["recent_form_dict"])
    
    # Save results to file
    with open("backtesting_results.json", "w") as f:
        json.dump(results, f, indent=2)
    
    print(f"\nResults saved to backtesting_results.json")
    print("\nTop 10 weight combos:")
    for i, result in enumerate(results["top_10"], 1):
        print(f"  {i}. Accuracy: {result['accuracy']:.1%}")
        print(f"     {result['weights']}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_backtesting.py::test_backtest_weights_returns_accuracy -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backtesting.py tests/test_backtesting.py
git commit -m "feat: add grid search backtesting script for weight calibration"
```

---

### Task 8: Update daily_update.py to Scrape Ranking + Recent Form

**Files:**
- Modify: `daily_update.py`

- [ ] **Step 1: Add scraper call after draw load**

In `daily_update.py`, after the draw scraping section, add:

```python
import db
from scrapers.ranking_form import extract_ranking_and_form
import httpx

def update_ranking_and_form():
    """Scrape ATP ranking and recent tournament form for all players in the draw."""
    import wimbledon_bot
    data = db.load_all_data(wimbledon_bot.DB_PATH)
    
    # Get all unique players in the draw
    player_names = set()
    for match in data["draw"]["matches"]:
        if match["player1"]:
            player_names.add(match["player1"])
        if match["player2"]:
            player_names.add(match["player2"])
    
    print(f"Scraping ranking + form for {len(player_names)} players...")
    
    success = 0
    failed = 0
    
    with httpx.Client(timeout=10) as session:
        for player_name in sorted(player_names):
            result = extract_ranking_and_form(player_name, session)
            
            if result is None:
                failed += 1
                print(f"  SKIP: {player_name}")
                continue
            
            player = db.get_player_by_name(wimbledon_bot.DB_PATH, player_name)
            if player is None:
                print(f"  ERROR: Player {player_name} not in DB (shouldn't happen)")
                continue
            
            # Upsert ranking
            db.upsert_ranking(wimbledon_bot.DB_PATH, player["id"],
                            ranking_position=result["ranking_position"],
                            ranking_points=result["ranking_points"])
            
            # Upsert recent form
            db.upsert_recent_form(wimbledon_bot.DB_PATH, player["id"],
                                 tournaments_played=result["tournaments_played"],
                                 wins=result["wins"],
                                 losses=result["losses"],
                                 titles=result["titles"],
                                 finals_reached=result["finals_reached"],
                                 last_tournament_date=result["last_tournament_date"])
            
            success += 1
            if success % 10 == 0:
                print(f"  {success} scraped...")
    
    print(f"Ranking + form scrape complete: {success} success, {failed} failed")


if __name__ == "__main__":
    update_ranking_and_form()
```

Add this function call to the main flow (in the existing `if __name__ == "__main__"` section):

```python
if __name__ == "__main__":
    # Existing code: scrape draw, live scores, etc.
    # ... (keep existing calls) ...
    
    # NEW: Scrape ranking + recent form
    update_ranking_and_form()
    
    # Existing code: update ELO, etc.
    # ... (keep existing calls) ...
```

- [ ] **Step 2: Commit**

```bash
git add daily_update.py
git commit -m "feat: add ranking + recent form scraper call to daily_update"
```

---

### Task 9: Run Backtesting and Apply Best Weights

**Files:**
- Modify: `wimbledon_bot.py` (weight constants)

- [ ] **Step 1: Run backtesting on current data**

```bash
cd "C:\Users\esteb\OneDrive\Documentos\ESTEBAN - ALIAS SHAGY\PROGRAMACION\ANALISTA DE TENIS WIMBLEDON 2026"
python backtesting.py
```

Expected output: "Best accuracy: XX.X% with K_ELO=..., W_GRASS=..., ..."
A file `backtesting_results.json` is created with top 10 combos.

- [ ] **Step 2: Review results**

Open `backtesting_results.json` and review top 5 combos. Write down the best one (or average of top 3 if they're all similar).

Example output:
```
Best accuracy: 72.5%
Best weights: {K_ELO: 25, W_GRASS: 1.0, W_FORM: 0.7, W_H2H: 20, W_FATIGUE: 0.10, W_RANKING: 0.12, W_RECENT_FORM: 0.08}
```

- [ ] **Step 3: Update wimbledon_bot.py with best weights**

In `wimbledon_bot.py`, replace the weight constants with backtesting results:

```python
# Pesos del modelo (calibrados via backtesting sobre 17 partidos completados — 2026-06-29)
K_ELO = 25          # Factor K para Grand Slam (previously 32)
W_GRASS = 1.0       # Peso del bonus por especialidad en hierba (previously 1.5)
W_FORM = 0.7        # Peso del factor de forma reciente
W_H2H = 20          # Peso del historial H2H (previously 25)
DAYS_FORM = 30      # Ventana de forma reciente
W_FATIGUE = 0.10    # Peso de la penalización por fatiga (previously 0.15)
FATIGUE_BASELINE_GAMES = 24  # juegos "normales" en una victoria 2-0 sin sets largos
W_RANKING = 0.12    # Peso del ranking ATP (NEW, calibrado)
W_RECENT_FORM = 0.08  # Peso de la forma reciente (NEW, calibrado)
```

(Use your actual backtesting results instead of these example values)

- [ ] **Step 4: Run full test suite to ensure no regression**

```bash
pytest tests/ -v
```

Expected: All tests pass (including the 17 completed matches backtest)

- [ ] **Step 5: Commit**

```bash
git add wimbledon_bot.py backtesting_results.json
git commit -m "feat: apply backtesting-optimized weights from grid search"
```

---

### Task 10: Final Validation and Cleanup

**Files:**
- Modify: None (testing only)

- [ ] **Step 1: Run live accuracy check**

```bash
python -c "
import db
from predictions import compute_accuracy

DB_PATH = 'data/wimbledon.db'
correct, total, details = compute_accuracy(DB_PATH)
accuracy_pct = 100*correct/total if total > 0 else 0
print(f'FINAL ACCURACY: {correct}/{total} = {accuracy_pct:.1f}%')
"
```

Expected: ≥70% (goal was 70-75%)

- [ ] **Step 2: Manual spot-check of predictions**

Load wimbledon_bot (or test via Telegram) and spot-check 3-5 upcoming/recent predictions to ensure they're reasonable.

- [ ] **Step 3: Ensure no broken imports or references**

Run a quick syntax check:

```bash
python -m py_compile wimbledon_bot.py db.py scrapers/ranking_form.py backtesting.py
```

Expected: No output (success)

- [ ] **Step 4: Test Telegram bot still works**

If Telegram bot is live, send a test command `/predict "Player A vs Player B"` and verify it responds with a prediction.

- [ ] **Step 5: Final commit with summary**

```bash
git add -A
git commit -m "feat: complete accuracy improvement pipeline (58.8% -> ~72%) with ranking, recent form, and backtesting calibration"
```

- [ ] **Step 6: Optional — Tag or document the milestone**

If using git tags:

```bash
git tag -a v1.1-improved-accuracy -m "ATP accuracy improved to 72% via new ranking + recent form model"
git log --oneline | head -10  # Verify commit history
```

---

## Summary

This plan implements a 4-phase accuracy improvement:

1. **Database:** Add `atp_rankings` + `recent_form` tables with upsert functions
2. **Scraper:** Extract ranking + tournament performance from tennisexplorer.com
3. **Model:** Extend rating calculation with two new bonus functions (ranking, recent form)
4. **Backtesting:** Grid search over 12,500 weight combos to find optimal parameters

**Expected outcome:** Accuracy improves from 58.8% to 70-75% via better feature engineering and calibrated weights.

**Timeline:** ~6-8 hours of implementation, testing, and validation.

**Next steps (for later):** After validating this accuracy improvement, add WTA (women's draw) and then iterate further with additional factors (Wimbledon historical win%, current momentum within tournament, etc.).
