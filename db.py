"""SQLite schema and access layer for the Wimbledon data pipeline."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

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


def _now():
    return datetime.now(timezone.utc).isoformat()


def upsert_player(db_path, name, elo=None, ranking=None):
    """Create a player if missing (defaulting elo to 1500), or update an
    existing one. `elo`/`ranking` left as None are NOT overwritten on an
    existing row — only explicitly-supplied values replace the current ones.
    This lets scrapers that only know player identity (draw, h2h, surface_stats)
    upsert a player for id resolution without wiping out elo/ranking set by
    the rankings scraper."""
    with get_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO players (name, elo, ranking, last_updated) VALUES (?, ?, ?, ?)
               ON CONFLICT(name) DO NOTHING""",
            (name, elo if elo is not None else 1500, ranking, _now()),
        )
        if elo is not None or ranking is not None:
            sets = []
            params = []
            if elo is not None:
                sets.append("elo = ?")
                params.append(elo)
            if ranking is not None:
                sets.append("ranking = ?")
                params.append(ranking)
            sets.append("last_updated = ?")
            params.append(_now())
            params.append(name)
            conn.execute(f"UPDATE players SET {', '.join(sets)} WHERE name = ?", params)
        return conn.execute("SELECT id FROM players WHERE name = ?", (name,)).fetchone()["id"]


def get_player_by_name(db_path, name):
    with get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM players WHERE name = ?", (name,)).fetchone()
        return dict(row) if row else None


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
