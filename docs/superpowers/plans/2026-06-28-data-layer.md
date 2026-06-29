# Capa de Datos — Wimbledon Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the placeholder JSON files with a real SQLite-backed data pipeline (player rankings, H2H, surface stats, draw, live scores) fed by scrapers, with name normalization and scraper-run logging, and migrate `wimbledon_bot.py` to read from it.

**Architecture:** A `db.py` module owns the SQLite schema and all read/write access. A `scrapers/` package contains one module per data source (`rankings.py`, `h2h.py`, `surface_stats.py`, `draw.py`, `live.py`) plus shared HTTP/retry/jitter utilities in `scrapers/base.py`. A `name_resolver.py` module normalizes player names across sources using a manual seed dictionary plus `rapidfuzz` fallback. Every scraper run is logged to `scraper_runs`. Each scraper is unit-tested against saved HTML/JSON fixtures — no live network calls in tests.

**Tech Stack:** Python 3.11+, `sqlite3` (stdlib), `requests`, `beautifulsoup4` (fallback parser), `rapidfuzz`, `pytest`. No new web framework — this plan only touches data plumbing, not the bot's Telegram handlers.

---

## File Structure

- Create: `db.py` — schema definition, connection helper, typed read/write functions
- Create: `name_resolver.py` — alias resolution (seed dict + rapidfuzz fallback)
- Create: `data/player_aliases_seed.json` — manual Top 100 alias seed data
- Create: `scrapers/__init__.py` — empty, marks package
- Create: `scrapers/base.py` — HTTP session, retry/backoff, jitter sleep, logging helper
- Create: `scrapers/rankings.py` — ATP/WTA rankings scraper (tennisexplorer.com)
- Create: `scrapers/h2h.py` — head-to-head scraper (tennisexplorer.com)
- Create: `scrapers/surface_stats.py` — grass vs total win% scraper (tennisexplorer.com)
- Create: `scrapers/draw.py` — Wimbledon draw scraper (wimbledon.com JSON endpoint)
- Create: `scrapers/live.py` — live scores scraper (wimbledon.com JSON endpoint)
- Modify: `wimbledon_bot.py` — replace `load_all_data()`/`load_json`/`save_json` calls with `db.py` reads; remove now-dead JSON constants
- Test: `tests/test_db.py`
- Test: `tests/test_name_resolver.py`
- Test: `tests/test_scrapers_rankings.py`
- Test: `tests/test_scrapers_h2h.py`
- Test: `tests/test_scrapers_surface_stats.py`
- Test: `tests/test_scrapers_draw.py`
- Test: `tests/test_scrapers_live.py`
- Test fixtures: `tests/fixtures/rankings_atp.html`, `tests/fixtures/h2h_pair.html`, `tests/fixtures/surface_stats.html`, `tests/fixtures/draw.json`, `tests/fixtures/live.json`

---

### Task 1: Project dependencies and pytest setup

**Files:**
- Create: `requirements.txt`
- Test: `tests/test_setup.py`

- [ ] **Step 1: Write requirements.txt**

```
requests==2.32.3
beautifulsoup4==4.12.3
rapidfuzz==3.9.6
python-telegram-bot==21.4
pytest==8.3.2
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: all packages install without error

- [ ] **Step 3: Write a smoke test confirming imports resolve**

```python
def test_dependencies_importable():
    import requests
    import bs4
    import rapidfuzz
    assert True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_setup.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add requirements.txt tests/test_setup.py
git commit -m "chore: add data-layer dependencies"
```

---

### Task 2: SQLite schema and connection helper

**Files:**
- Create: `db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
import os
import sqlite3
import pytest
import db

@pytest.fixture
def test_db_path(tmp_path):
    return str(tmp_path / "test_wimbledon.db")

def test_init_db_creates_all_tables(test_db_path):
    db.init_db(test_db_path)
    conn = sqlite3.connect(test_db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cursor.fetchall()}
    expected = {
        "players", "player_aliases", "unresolved_names", "h2h",
        "grass_stats", "form", "draw_matches", "live_scores",
        "scraper_runs", "match_stats",
    }
    assert expected.issubset(tables)
    conn.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py::test_init_db_creates_all_tables -v`
Expected: FAIL with "module 'db' has no attribute 'init_db'"

- [ ] **Step 3: Write the schema and init_db**

```python
"""SQLite schema and access layer for the Wimbledon data pipeline."""
import sqlite3
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    elo REAL NOT NULL DEFAULT 1500,
    ranking INTEGER,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS player_aliases (
    alias_name TEXT PRIMARY KEY,
    player_id INTEGER NOT NULL REFERENCES players(id)
);

CREATE TABLE IF NOT EXISTS unresolved_names (
    raw_name TEXT NOT NULL,
    source TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    PRIMARY KEY (raw_name, source)
);

CREATE TABLE IF NOT EXISTS h2h (
    player_a_id INTEGER NOT NULL REFERENCES players(id),
    player_b_id INTEGER NOT NULL REFERENCES players(id),
    a_wins INTEGER NOT NULL DEFAULT 0,
    b_wins INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (player_a_id, player_b_id),
    CHECK (player_a_id < player_b_id)
);

CREATE TABLE IF NOT EXISTS grass_stats (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    grass_winrate REAL,
    total_winrate REAL,
    matches_played INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS form (
    player_id INTEGER PRIMARY KEY REFERENCES players(id),
    points REAL NOT NULL DEFAULT 0,
    last_updated TEXT
);

CREATE TABLE IF NOT EXISTS draw_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id TEXT NOT NULL,
    year INTEGER NOT NULL,
    round TEXT NOT NULL,
    player1_id INTEGER NOT NULL REFERENCES players(id),
    player2_id INTEGER NOT NULL REFERENCES players(id),
    winner_id INTEGER REFERENCES players(id),
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS live_scores (
    match_id INTEGER PRIMARY KEY REFERENCES draw_matches(id),
    sets TEXT,
    status TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS scraper_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    rows_fetched INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS match_stats (
    match_id INTEGER NOT NULL REFERENCES draw_matches(id),
    player_id INTEGER NOT NULL REFERENCES players(id),
    first_serve_pct REAL,
    break_points_saved INTEGER,
    aces INTEGER,
    double_faults INTEGER,
    PRIMARY KEY (match_id, player_id)
);
"""


@contextmanager
def get_connection(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path):
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py::test_init_db_creates_all_tables -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add SQLite schema and init_db"
```

---

### Task 3: Player read/write functions in db.py

**Files:**
- Modify: `db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
def test_upsert_player_creates_new_player(test_db_path):
    db.init_db(test_db_path)
    player_id = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2100, ranking=2)
    with db.get_connection(test_db_path) as conn:
        row = conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone()
    assert row["name"] == "Carlos Alcaraz"
    assert row["elo"] == 2100
    assert row["ranking"] == 2

def test_upsert_player_updates_existing_player(test_db_path):
    db.init_db(test_db_path)
    first_id = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2100, ranking=2)
    second_id = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2150, ranking=1)
    assert first_id == second_id
    with db.get_connection(test_db_path) as conn:
        row = conn.execute("SELECT * FROM players WHERE id = ?", (second_id,)).fetchone()
    assert row["elo"] == 2150
    assert row["ranking"] == 1

def test_get_player_by_name_returns_none_if_missing(test_db_path):
    db.init_db(test_db_path)
    assert db.get_player_by_name(test_db_path, "Nobody") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -k player -v`
Expected: FAIL with "module 'db' has no attribute 'upsert_player'"

- [ ] **Step 3: Implement the functions**

Append to `db.py`:

```python
from datetime import datetime, timezone


def _now():
    return datetime.now(timezone.utc).isoformat()


def upsert_player(db_path, name, elo=1500, ranking=None):
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT id FROM players WHERE name = ?", (name,)).fetchone()
        if row is None:
            cursor = conn.execute(
                "INSERT INTO players (name, elo, ranking, last_updated) VALUES (?, ?, ?, ?)",
                (name, elo, ranking, _now()),
            )
            return cursor.lastrowid
        conn.execute(
            "UPDATE players SET elo = ?, ranking = ?, last_updated = ? WHERE id = ?",
            (elo, ranking, _now(), row["id"]),
        )
        return row["id"]


def get_player_by_name(db_path, name):
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -k player -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add player upsert/read functions to db.py"
```

---

### Task 4: Name resolver — manual seed + rapidfuzz fallback

**Files:**
- Create: `data/player_aliases_seed.json`
- Create: `name_resolver.py`
- Test: `tests/test_name_resolver.py`

- [ ] **Step 1: Write the seed file**

```json
{
  "C. Alcaraz": "Carlos Alcaraz",
  "Carlos Alcaraz": "Carlos Alcaraz",
  "Alcaraz C.": "Carlos Alcaraz",
  "N. Djokovic": "Novak Djokovic",
  "Novak Djokovic": "Novak Djokovic",
  "Djokovic N.": "Novak Djokovic",
  "J. Sinner": "Jannik Sinner",
  "Jannik Sinner": "Jannik Sinner",
  "A. Zverev": "Alexander Zverev",
  "Alexander Zverev": "Alexander Zverev",
  "M. Zverev": "Mischa Zverev",
  "Mischa Zverev": "Mischa Zverev"
}
```

- [ ] **Step 2: Write the failing test**

```python
import json
import name_resolver
import db

def test_resolve_known_alias_returns_canonical_name(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    resolved = name_resolver.resolve(db_path, "C. Alcaraz", source="tennisexplorer")
    assert resolved == "Carlos Alcaraz"

def test_resolve_does_not_merge_similar_but_distinct_siblings(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    a = name_resolver.resolve(db_path, "A. Zverev", source="tennisexplorer")
    m = name_resolver.resolve(db_path, "M. Zverev", source="tennisexplorer")
    assert a == "Alexander Zverev"
    assert m == "Mischa Zverev"
    assert a != m

def test_resolve_unknown_name_below_threshold_goes_to_unresolved(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    db.upsert_player(db_path, name="Carlos Alcaraz")
    resolved = name_resolver.resolve(db_path, "Totally Different Person", source="tennisexplorer")
    assert resolved is None
    with db.get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM unresolved_names WHERE raw_name = ?",
            ("Totally Different Person",),
        ).fetchone()
    assert row is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_name_resolver.py -v`
Expected: FAIL with "No module named 'name_resolver'"

- [ ] **Step 4: Implement name_resolver.py**

```python
"""Resolve raw scraped player names to a canonical name.

Resolution order:
1. Exact match in the seed alias dictionary (data/player_aliases_seed.json).
2. Exact match already recorded in player_aliases table.
3. rapidfuzz match against known players.name, threshold > 90.
4. Otherwise: record in unresolved_names, return None.
"""
import json
import os
from datetime import datetime, timezone
from rapidfuzz import fuzz, process

import db

SEED_PATH = os.path.join(os.path.dirname(__file__), "data", "player_aliases_seed.json")
FUZZY_THRESHOLD = 90


def _now():
    return datetime.now(timezone.utc).isoformat()


def _load_seed():
    with open(SEED_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def resolve(db_path, raw_name, source):
    seed = _load_seed()
    if raw_name in seed:
        canonical = seed[raw_name]
        db.upsert_player(db_path, name=canonical)
        _record_alias(db_path, raw_name, canonical)
        return canonical

    with db.get_connection(db_path) as conn:
        alias_row = conn.execute(
            "SELECT player_id FROM player_aliases WHERE alias_name = ?", (raw_name,)
        ).fetchone()
        if alias_row:
            player_row = conn.execute(
                "SELECT name FROM players WHERE id = ?", (alias_row["player_id"],)
            ).fetchone()
            return player_row["name"]

        known_names = [row["name"] for row in conn.execute("SELECT name FROM players").fetchall()]

    if known_names:
        match = process.extractOne(raw_name, known_names, scorer=fuzz.ratio)
        if match and match[1] > FUZZY_THRESHOLD:
            canonical = match[0]
            _record_alias(db_path, raw_name, canonical)
            return canonical

    with db.get_connection(db_path) as conn:
        conn.execute(
            "INSERT OR IGNORE INTO unresolved_names (raw_name, source, first_seen) VALUES (?, ?, ?)",
            (raw_name, source, _now()),
        )
    return None


def _record_alias(db_path, raw_name, canonical):
    with db.get_connection(db_path) as conn:
        player_row = conn.execute("SELECT id FROM players WHERE name = ?", (canonical,)).fetchone()
        if player_row is None:
            return
        conn.execute(
            "INSERT OR IGNORE INTO player_aliases (alias_name, player_id) VALUES (?, ?)",
            (raw_name, player_row["id"]),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_name_resolver.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add data/player_aliases_seed.json name_resolver.py tests/test_name_resolver.py
git commit -m "feat: add name resolver with seed dictionary and rapidfuzz fallback"
```

---

### Task 5: Scraper base utilities — session, retry, jitter, run logging

**Files:**
- Create: `scrapers/__init__.py`
- Create: `scrapers/base.py`
- Test: `tests/test_scrapers_base.py`

- [ ] **Step 1: Write `scrapers/__init__.py`**

```python
```

(empty file, just marks the package)

- [ ] **Step 2: Write the failing test**

```python
import time
import pytest
from unittest.mock import patch
from scrapers import base

def test_jittered_sleep_within_bounds():
    with patch("time.sleep") as mock_sleep:
        base.jittered_sleep(min_seconds=1.5, max_seconds=4.2)
    args, _ = mock_sleep.call_args
    assert 1.5 <= args[0] <= 4.2

def test_log_scraper_run_writes_row(tmp_path):
    import db
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    base.log_scraper_run(db_path, source="rankings", status="success", rows_fetched=50)
    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM scraper_runs WHERE source = ?", ("rankings",)).fetchone()
    assert row["status"] == "success"
    assert row["rows_fetched"] == 50

def test_fetch_with_retry_retries_on_failure():
    call_count = {"n": 0}

    def flaky():
        call_count["n"] += 1
        if call_count["n"] < 2:
            raise ConnectionError("boom")
        return "ok"

    with patch("time.sleep"):
        result = base.fetch_with_retry(flaky, max_attempts=3)
    assert result == "ok"
    assert call_count["n"] == 2
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_scrapers_base.py -v`
Expected: FAIL with "No module named 'scrapers'" or "module 'scrapers.base' has no attribute 'jittered_sleep'"

- [ ] **Step 4: Implement `scrapers/base.py`**

```python
"""Shared scraping utilities: HTTP session, retry/backoff, jitter, run logging."""
import random
import time
from datetime import datetime, timezone

import requests

import db

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
]


def _now():
    return datetime.now(timezone.utc).isoformat()


def get_session():
    session = requests.Session()
    session.headers.update({"User-Agent": random.choice(USER_AGENTS)})
    return session


def jittered_sleep(min_seconds=1.5, max_seconds=4.2):
    time.sleep(random.uniform(min_seconds, max_seconds))


def fetch_with_retry(fn, max_attempts=3, base_delay=1.0):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise last_error


def log_scraper_run(db_path, source, status, rows_fetched=0, error_message=None, started_at=None):
    started = started_at or _now()
    with db.get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO scraper_runs
               (source, status, rows_fetched, error_message, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (source, status, rows_fetched, error_message, started, _now()),
        )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scrapers_base.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add scrapers/__init__.py scrapers/base.py tests/test_scrapers_base.py
git commit -m "feat: add scraper base utilities (retry, jitter, run logging)"
```

---

### Task 6: Rankings scraper (tennisexplorer.com)

**Files:**
- Create: `scrapers/rankings.py`
- Create: `tests/fixtures/rankings_atp.html`
- Test: `tests/test_scrapers_rankings.py`

- [ ] **Step 1: Write the fixture**

```html
<!-- tests/fixtures/rankings_atp.html -->
<table class="result">
  <tr class="head"><td>Rank</td><td>Player</td><td>Points</td></tr>
  <tr><td>1</td><td><a href="/player/alcaraz/">Carlos Alcaraz</a></td><td>9255</td></tr>
  <tr><td>2</td><td><a href="/player/sinner/">Jannik Sinner</a></td><td>8770</td></tr>
  <tr><td>3</td><td><a href="/player/djokovic/">Novak Djokovic</a></td><td>7280</td></tr>
</table>
```

- [ ] **Step 2: Write the failing test**

```python
import os
from scrapers import rankings

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "rankings_atp.html")

def test_parse_rankings_html_extracts_players():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = rankings.parse_rankings_html(html)
    assert parsed == [
        {"rank": 1, "name": "Carlos Alcaraz"},
        {"rank": 2, "name": "Jannik Sinner"},
        {"rank": 3, "name": "Novak Djokovic"},
    ]

def test_parse_rankings_html_returns_empty_list_on_unexpected_structure():
    parsed = rankings.parse_rankings_html("<html><body>nothing here</body></html>")
    assert parsed == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_scrapers_rankings.py -v`
Expected: FAIL with "module 'scrapers.rankings' has no attribute 'parse_rankings_html'"

- [ ] **Step 4: Implement `scrapers/rankings.py`**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scrapers_rankings.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Write a test for `run()` using a mocked session**

```python
from unittest.mock import MagicMock
import db
from scrapers import rankings

def test_run_writes_players_and_logs_success(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    mock_response = MagicMock()
    mock_response.text = html
    mock_response.raise_for_status = MagicMock()
    mock_session = MagicMock()
    mock_session.get.return_value = mock_response

    rows = rankings.run(db_path, session=mock_session)
    assert rows == 3

    with db.get_connection(db_path) as conn:
        players = conn.execute("SELECT name, ranking FROM players ORDER BY ranking").fetchall()
        run_log = conn.execute("SELECT * FROM scraper_runs WHERE source = 'rankings'").fetchone()

    assert [p["name"] for p in players] == ["Carlos Alcaraz", "Jannik Sinner", "Novak Djokovic"]
    assert run_log["status"] == "success"
    assert run_log["rows_fetched"] == 3
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_scrapers_rankings.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit**

```bash
git add scrapers/rankings.py tests/test_scrapers_rankings.py tests/fixtures/rankings_atp.html
git commit -m "feat: add rankings scraper for tennisexplorer.com"
```

---

### Task 7: H2H scraper (tennisexplorer.com)

**Files:**
- Create: `scrapers/h2h.py`
- Create: `tests/fixtures/h2h_pair.html`
- Test: `tests/test_scrapers_h2h.py`

- [ ] **Step 1: Write the fixture**

```html
<!-- tests/fixtures/h2h_pair.html -->
<div class="head2head">
  <div class="result">
    <span class="player1">Carlos Alcaraz</span>
    <span class="score">5</span>
    -
    <span class="score">3</span>
    <span class="player2">Novak Djokovic</span>
  </div>
</div>
```

- [ ] **Step 2: Write the failing test**

```python
import os
from scrapers import h2h

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "h2h_pair.html")

def test_parse_h2h_html_extracts_wins():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = h2h.parse_h2h_html(html)
    assert parsed == {
        "player1": "Carlos Alcaraz",
        "player2": "Novak Djokovic",
        "player1_wins": 5,
        "player2_wins": 3,
    }

def test_parse_h2h_html_returns_none_on_missing_data():
    assert h2h.parse_h2h_html("<html></html>") is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_scrapers_h2h.py -v`
Expected: FAIL with "module 'scrapers.h2h' has no attribute 'parse_h2h_html'"

- [ ] **Step 4: Implement `scrapers/h2h.py`**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scrapers_h2h.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Write a test for `_store_h2h` normalization order**

```python
import db
from scrapers import h2h

def test_store_h2h_normalizes_player_order(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    id_b = db.upsert_player(db_path, name="Novak Djokovic")
    id_a = db.upsert_player(db_path, name="Carlos Alcaraz")

    h2h._store_h2h(db_path, "Carlos Alcaraz", "Novak Djokovic", wins1=5, wins2=3)

    lower_id, higher_id = sorted([id_a, id_b])
    expected_a_wins = 5 if id_a == lower_id else 3
    expected_b_wins = 3 if id_a == lower_id else 5

    with db.get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM h2h WHERE player_a_id = ? AND player_b_id = ?",
            (lower_id, higher_id),
        ).fetchone()
    assert row is not None
    assert row["a_wins"] == expected_a_wins
    assert row["b_wins"] == expected_b_wins
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_scrapers_h2h.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit**

```bash
git add scrapers/h2h.py tests/test_scrapers_h2h.py tests/fixtures/h2h_pair.html
git commit -m "feat: add H2H scraper with normalized player ordering"
```

---

### Task 8: Surface stats scraper (tennisexplorer.com)

**Files:**
- Create: `scrapers/surface_stats.py`
- Create: `tests/fixtures/surface_stats.html`
- Test: `tests/test_scrapers_surface_stats.py`

- [ ] **Step 1: Write the fixture**

```html
<!-- tests/fixtures/surface_stats.html -->
<table class="surface-stats">
  <tr><td class="surface">Grass</td><td class="wins">18</td><td class="losses">4</td></tr>
  <tr><td class="surface">Hard</td><td class="wins">40</td><td class="losses">15</td></tr>
  <tr><td class="surface">Clay</td><td class="wins">22</td><td class="losses">10</td></tr>
</table>
```

- [ ] **Step 2: Write the failing test**

```python
import os
from scrapers import surface_stats

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "surface_stats.html")

def test_parse_surface_stats_computes_winrates():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    parsed = surface_stats.parse_surface_stats_html(html)
    assert parsed["grass_winrate"] == round(18 / 22, 4)
    total_wins = 18 + 40 + 22
    total_matches = 22 + 55 + 32
    assert parsed["total_winrate"] == round(total_wins / total_matches, 4)
    assert parsed["matches_played"] == total_matches

def test_parse_surface_stats_returns_none_without_grass_row():
    html = '<table class="surface-stats"><tr><td class="surface">Hard</td><td class="wins">1</td><td class="losses">1</td></tr></table>'
    assert surface_stats.parse_surface_stats_html(html) is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_scrapers_surface_stats.py -v`
Expected: FAIL with "module 'scrapers.surface_stats' has no attribute 'parse_surface_stats_html'"

- [ ] **Step 4: Implement `scrapers/surface_stats.py`**

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scrapers_surface_stats.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Write a storage test**

```python
import db
from scrapers import surface_stats

def test_store_surface_stats_upserts(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    player_id = db.upsert_player(db_path, name="Carlos Alcaraz")
    parsed = {"grass_winrate": 0.8182, "total_winrate": 0.7339, "matches_played": 109}

    surface_stats.store_surface_stats(db_path, player_id, parsed)
    surface_stats.store_surface_stats(db_path, player_id, {**parsed, "matches_played": 110})

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM grass_stats WHERE player_id = ?", (player_id,)).fetchone()
    assert row["matches_played"] == 110
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_scrapers_surface_stats.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit**

```bash
git add scrapers/surface_stats.py tests/test_scrapers_surface_stats.py tests/fixtures/surface_stats.html
git commit -m "feat: add surface stats scraper"
```

---

### Task 9: Draw scraper (wimbledon.com JSON endpoint)

**Files:**
- Create: `scrapers/draw.py`
- Create: `tests/fixtures/draw.json`
- Test: `tests/test_scrapers_draw.py`

- [ ] **Step 1: Write the fixture**

```json
[
  {"round": "R1", "player1": "Carlos Alcaraz", "player2": "Mark Newcomer", "winner": "Carlos Alcaraz", "completedAt": "2026-06-29T15:00:00Z"},
  {"round": "R1", "player1": "Novak Djokovic", "player2": "Jane Qualifier", "winner": null, "completedAt": null}
]
```

- [ ] **Step 2: Write the failing test**

```python
import json
import os
from scrapers import draw

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "draw.json")

def test_parse_draw_json_normalizes_fields():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    parsed = draw.parse_draw_json(payload)
    assert parsed == [
        {"round": "R1", "player1": "Carlos Alcaraz", "player2": "Mark Newcomer",
         "winner": "Carlos Alcaraz", "completed_at": "2026-06-29T15:00:00Z"},
        {"round": "R1", "player1": "Novak Djokovic", "player2": "Jane Qualifier",
         "winner": None, "completed_at": None},
    ]

def test_parse_draw_json_skips_malformed_entries():
    payload = [{"round": "R1"}]
    assert draw.parse_draw_json(payload) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_scrapers_draw.py -v`
Expected: FAIL with "No module named 'scrapers.draw'"

- [ ] **Step 4: Implement `scrapers/draw.py`**

Per the design note: prefer the site's internal JSON endpoint over HTML parsing. This module assumes that endpoint has already been identified (via browser network inspection) and consumes it directly.

```python
"""Wimbledon draw scraper — consumes the site's internal JSON endpoint directly
(SPA sites like wimbledon.com are Cloudflare-protected and React/Next.js-based;
parsing the DOM is unreliable). If the endpoint disappears, fall back to
Playwright-rendered HTML before resorting to static parsing.
"""
from datetime import datetime, timezone

import db
import name_resolver
from scrapers import base

DRAW_TOURNAMENT_ID = "wimbledon"
DRAW_YEAR = 2026
DRAW_ENDPOINT = "https://www.wimbledon.com/en_GB/api/draw.json"  # placeholder, confirm via network inspection


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
        })
    return results


def _store_match(db_path, entry):
    p1_canonical = name_resolver.resolve(db_path, entry["player1"], source="wimbledon") or entry["player1"]
    p2_canonical = name_resolver.resolve(db_path, entry["player2"], source="wimbledon") or entry["player2"]
    p1_id = db.upsert_player(db_path, name=p1_canonical)
    p2_id = db.upsert_player(db_path, name=p2_canonical)
    winner_id = None
    if entry["winner"]:
        winner_canonical = name_resolver.resolve(db_path, entry["winner"], source="wimbledon") or entry["winner"]
        winner_id = db.upsert_player(db_path, name=winner_canonical)

    with db.get_connection(db_path) as conn:
        existing = conn.execute(
            """SELECT id FROM draw_matches
               WHERE tournament_id = ? AND year = ? AND round = ?
               AND player1_id = ? AND player2_id = ?""",
            (DRAW_TOURNAMENT_ID, DRAW_YEAR, entry["round"], p1_id, p2_id),
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE draw_matches SET winner_id = ?, completed_at = ? WHERE id = ?",
                (winner_id, entry["completed_at"], existing["id"]),
            )
        else:
            conn.execute(
                """INSERT INTO draw_matches
                   (tournament_id, year, round, player1_id, player2_id, winner_id, completed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (DRAW_TOURNAMENT_ID, DRAW_YEAR, entry["round"], p1_id, p2_id, winner_id, entry["completed_at"]),
            )


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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scrapers_draw.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Write a storage test covering insert and update**

```python
import db
from scrapers import draw

def test_store_match_inserts_then_updates(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    entry = {"round": "R1", "player1": "Carlos Alcaraz", "player2": "Mark Newcomer",
              "winner": None, "completed_at": None}
    draw._store_match(db_path, entry)

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM draw_matches").fetchone()
    assert row["winner_id"] is None

    entry["winner"] = "Carlos Alcaraz"
    entry["completed_at"] = "2026-06-29T15:00:00Z"
    draw._store_match(db_path, entry)

    with db.get_connection(db_path) as conn:
        rows = conn.execute("SELECT * FROM draw_matches").fetchall()
    assert len(rows) == 1
    assert rows[0]["completed_at"] == "2026-06-29T15:00:00Z"
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_scrapers_draw.py -v`
Expected: PASS (3 passed)

- [ ] **Step 8: Commit**

```bash
git add scrapers/draw.py tests/test_scrapers_draw.py tests/fixtures/draw.json
git commit -m "feat: add draw scraper consuming wimbledon.com JSON endpoint"
```

---

### Task 10: Live scores scraper (wimbledon.com JSON endpoint)

**Files:**
- Create: `scrapers/live.py`
- Create: `tests/fixtures/live.json`
- Test: `tests/test_scrapers_live.py`

- [ ] **Step 1: Write the fixture**

```json
[
  {"matchId": "wim-2026-r1-001", "sets": "6-4, 3-2", "status": "in_progress"},
  {"matchId": "wim-2026-r1-002", "sets": "6-2, 6-3", "status": "finished"}
]
```

- [ ] **Step 2: Write the failing test**

```python
import json
import os
from scrapers import live

FIXTURE_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "live.json")

def test_parse_live_json_normalizes_fields():
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    parsed = live.parse_live_json(payload)
    assert parsed == [
        {"external_match_id": "wim-2026-r1-001", "sets": "6-4, 3-2", "status": "in_progress"},
        {"external_match_id": "wim-2026-r1-002", "sets": "6-2, 6-3", "status": "finished"},
    ]

def test_parse_live_json_skips_entries_without_match_id():
    assert live.parse_live_json([{"sets": "6-4"}]) == []
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_scrapers_live.py -v`
Expected: FAIL with "No module named 'scrapers.live'"

- [ ] **Step 4: Implement `scrapers/live.py`**

This scraper only updates `live_scores` for matches that already exist in `draw_matches` (matched by `tournament_id`/`year`/`round`/players via the draw scraper). For matches not yet found locally, it skips and logs them as unmatched rather than failing.

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_scrapers_live.py -v`
Expected: PASS (2 passed)

- [ ] **Step 6: Write a storage test**

```python
import db
import name_resolver
from scrapers import live

def test_store_live_scores_updates_matched_rows(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    p1 = db.upsert_player(db_path, name="Carlos Alcaraz")
    p2 = db.upsert_player(db_path, name="Mark Newcomer")
    with db.get_connection(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO draw_matches (tournament_id, year, round, player1_id, player2_id)
               VALUES ('wimbledon', 2026, 'R1', ?, ?)""",
            (p1, p2),
        )
        local_match_id = cursor.lastrowid

    parsed = [{"external_match_id": "wim-2026-r1-001", "sets": "6-4, 3-2", "status": "in_progress"}]
    external_id_map = {"wim-2026-r1-001": local_match_id}

    updated = live.store_live_scores(db_path, parsed, external_id_map)
    assert updated == 1

    with db.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM live_scores WHERE match_id = ?", (local_match_id,)).fetchone()
    assert row["status"] == "in_progress"

def test_store_live_scores_skips_unmatched_entries(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    parsed = [{"external_match_id": "unknown-match", "sets": "6-4", "status": "in_progress"}]
    updated = live.store_live_scores(db_path, parsed, external_id_map={})
    assert updated == 0
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_scrapers_live.py -v`
Expected: PASS (4 passed)

- [ ] **Step 8: Commit**

```bash
git add scrapers/live.py tests/test_scrapers_live.py tests/fixtures/live.json
git commit -m "feat: add live scores scraper"
```

---

### Task 11: form() read function (reuses existing form points, write side deferred)

**Files:**
- Modify: `db.py`
- Test: `tests/test_db.py`

Note: `update_form()` (the algorithm that computes form points from recent results) is part of sub-project 2 (prediction engine). This task only adds the read/write plumbing so the bot and future form-calculation code have a stable interface.

- [ ] **Step 1: Write the failing test**

```python
def test_set_and_get_form_points(test_db_path):
    db.init_db(test_db_path)
    player_id = db.upsert_player(test_db_path, name="Carlos Alcaraz")
    db.set_form_points(test_db_path, player_id, points=4.5)
    points = db.get_form_points(test_db_path, player_id)
    assert points == 4.5

def test_get_form_points_defaults_to_zero_when_missing(test_db_path):
    db.init_db(test_db_path)
    player_id = db.upsert_player(test_db_path, name="Novak Djokovic")
    assert db.get_form_points(test_db_path, player_id) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -k form -v`
Expected: FAIL with "module 'db' has no attribute 'set_form_points'"

- [ ] **Step 3: Implement the functions**

Append to `db.py`:

```python
def set_form_points(db_path, player_id, points):
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO form (player_id, points, last_updated) VALUES (?, ?, ?)
               ON CONFLICT(player_id) DO UPDATE SET points = excluded.points, last_updated = excluded.last_updated""",
            (player_id, points, _now()),
        )


def get_form_points(db_path, player_id):
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT points FROM form WHERE player_id = ?", (player_id,)).fetchone()
        return row["points"] if row else 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -k form -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add form points read/write functions"
```

---

### Task 12: Bulk-read function for the bot (`load_all_data` replacement)

**Files:**
- Modify: `db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write the failing test**

```python
def test_load_all_data_returns_expected_shape(test_db_path):
    db.init_db(test_db_path)
    p1 = db.upsert_player(test_db_path, name="Carlos Alcaraz", elo=2100)
    p2 = db.upsert_player(test_db_path, name="Novak Djokovic", elo=2050)
    db.set_form_points(test_db_path, p1, points=3.0)

    data = db.load_all_data(test_db_path)

    assert data["elo"]["Carlos Alcaraz"] == 2100
    assert data["elo"]["Novak Djokovic"] == 2050
    assert data["form"]["Carlos Alcaraz"] == 3.0
    assert "Novak Djokovic" not in data["form"] or data["form"]["Novak Djokovic"] == 0
    assert isinstance(data["grass_stats"], dict)
    assert isinstance(data["h2h"], dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_db.py -k load_all_data -v`
Expected: FAIL with "module 'db' has no attribute 'load_all_data'"

- [ ] **Step 3: Implement `load_all_data`**

Append to `db.py`:

```python
def load_all_data(db_path):
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

        draw_rows = conn.execute(
            "SELECT round, player1_id, player2_id, winner_id FROM draw_matches"
        ).fetchall()
        matches = []
        for row in draw_rows:
            p1_name = id_to_name.get(row["player1_id"])
            p2_name = id_to_name.get(row["player2_id"])
            if p1_name and p2_name:
                matches.append({"player1": p1_name, "player2": p2_name,
                                 "winner": id_to_name.get(row["winner_id"])})

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
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_db.py -k load_all_data -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db.py tests/test_db.py
git commit -m "feat: add load_all_data for bot consumption"
```

---

### Task 13: Migrate wimbledon_bot.py to use db.py

**Files:**
- Modify: `wimbledon_bot.py`

- [ ] **Step 1: Remove the JSON file constants and load/save helpers**

In `wimbledon_bot.py`, delete these lines:

```python
DATA_DIR = "data"
ELO_FILE = os.path.join(DATA_DIR, "elo_ratings.json")
GRASS_STATS_FILE = os.path.join(DATA_DIR, "grass_stats.json")
FORM_FILE = os.path.join(DATA_DIR, "form.json")
H2H_FILE = os.path.join(DATA_DIR, "h2h.json")
DRAW_FILE = os.path.join(DATA_DIR, "draw.json")
LIVE_FILE = os.path.join(DATA_DIR, "live_scores.json")
```

and the entire `load_json`, `save_json`, `load_all_data` function definitions (the JSON-based ones — they are being replaced by `db.py`).

- [ ] **Step 2: Add the db import and a DB_PATH constant**

At the top of `wimbledon_bot.py`, after the existing imports, add:

```python
import db as data_db

DB_PATH = os.path.join("data", "wimbledon.db")
```

- [ ] **Step 3: Replace every `load_all_data()` call with `data_db.load_all_data(DB_PATH)`**

In `cmd_predict`, `cmd_stats`, `cmd_draw`: replace

```python
data = load_all_data()
```

with

```python
data = data_db.load_all_data(DB_PATH)
```

- [ ] **Step 4: Update `update_elo_from_results` to read/write via db.py**

Replace the function body:

```python
def update_elo_from_results():
    """Actualiza ratings Elo con los partidos completados en draw_matches."""
    data = data_db.load_all_data(DB_PATH)
    completed = data['draw'].get('completed_matches', [])
    if not completed:
        return
    elo = data['elo']
    for m in completed:
        if m['winner']:
            winner = m['winner']
            loser = m['player2'] if m['player1'] == winner else m['player1']
            elo = update_elo_ratings(winner, loser, elo)
    for name, new_elo in elo.items():
        data_db.upsert_player(DB_PATH, name=name, elo=new_elo)
    print("Elo actualizado con resultados recientes.")
```

- [ ] **Step 5: Ensure the DB is initialized before the bot starts**

In the `if __name__ == "__main__":` block, before the existing branches, add:

```python
data_db.init_db(DB_PATH)
```

- [ ] **Step 6: Manually verify the bot still starts**

Run: `python wimbledon_bot.py update`
Expected: prints "Elo actualizado con resultados recientes." (or nothing if no completed matches) without raising an exception. This confirms the db-backed path works end-to-end since there's no existing automated test harness for the Telegram handlers.

- [ ] **Step 7: Commit**

```bash
git add wimbledon_bot.py
git commit -m "refactor: migrate wimbledon_bot.py from JSON files to SQLite via db.py"
```

---

## Self-Review Notes

- **Spec coverage**: schema (Task 2), name resolution with seed+rapidfuzz (Task 4), scraper base with jitter/retry/logging (Task 5), rankings/h2h/surface_stats/draw/live scrapers (Tasks 6-10), `tournament_id`/`year` on `draw_matches` and `match_stats` placeholder (Task 2), `live_scores` foreign key to `draw_matches` (Task 2), bot migration off JSON (Task 13). `update_form()` algorithm itself is explicitly out of scope per the spec (sub-project 2) — Task 11 only adds the storage interface it will use.
- **Placeholder scan**: no TBD/TODO markers; every step has runnable code.
- **Type consistency**: `db.load_all_data` return shape (`elo`, `grass_stats`, `form`, `h2h`, `draw`, `live_scores` keys) matches what `wimbledon_bot.py`'s existing `predict_match`/`calculate_rating`/`get_h2h_bonus` functions already expect (verified against the original file's `load_all_data` shape) — no signature changes needed in those functions, only in how data is sourced.
