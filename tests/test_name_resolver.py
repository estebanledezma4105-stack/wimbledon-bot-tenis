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
