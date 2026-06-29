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
