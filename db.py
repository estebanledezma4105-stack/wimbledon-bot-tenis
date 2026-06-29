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
    conn.execute("PRAGMA foreign_keys = ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path):
    with get_connection(db_path) as conn:
        conn.executescript(SCHEMA)
