import json
import sqlite3
from pathlib import Path

import pytest

from app import db

SCHEMA = json.loads((Path(__file__).resolve().parents[2] / "docs" / "schema.json").read_text(encoding="utf-8"))


def migrations(tmp_path, **files):
    folder = tmp_path / "migrations"
    folder.mkdir(exist_ok=True)
    for file_name, sql in files.items():
        (folder / file_name.replace("_sql", ".sql")).write_text(sql, encoding="utf-8")
    return folder


def version(conn):
    return conn.execute("PRAGMA user_version").fetchone()[0]


def tables(conn):
    return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# ---- the real migrations ---------------------------------------------------------------------------


def test_a_new_database_gets_every_migration_and_the_schema_version(tmp_path):
    conn = db.connect(tmp_path / "new.db")
    assert version(conn) == 0
    assert db.migrate(conn, db_file=tmp_path / "new.db") == SCHEMA["schema_version"]
    assert version(conn) == SCHEMA["schema_version"]


def test_the_created_database_matches_docs_schema_json(db_file, client, conn):
    """docs/schema.json is the design; the migrations must produce exactly that."""
    strict = {r["name"]: r["strict"] for r in conn.execute("PRAGMA table_list")}
    for table in SCHEMA["tables"]:
        name = table["name"]
        assert strict[name] == 1, f"{name} is not STRICT"

        columns = {r["name"]: r for r in conn.execute(f"PRAGMA table_info('{name}')")}
        assert list(columns) == [c["name"] for c in table["columns"]], f"{name}: columns or their order differ"
        pk = table.get("primary_key") or [c["name"] for c in table["columns"] if c.get("primary_key")]
        for c in table["columns"]:
            actual = columns[c["name"]]
            assert actual["type"] == c["type"], f"{name}.{c['name']} type"
            if c["name"] in pk:
                assert actual["pk"] > 0, f"{name}.{c['name']} should be part of the primary key"
            else:
                assert actual["notnull"] == (0 if c["nullable"] else 1), f"{name}.{c['name']} nullability"
        assert {n for n, r in columns.items() if r["pk"]} == set(pk), f"{name}: primary key"

        fks = {(r["from"], r["table"], r["to"], r["on_delete"]) for r in conn.execute(f"PRAGMA foreign_key_list('{name}')")}
        expected = {(f["column"], f["references"]["table"], f["references"]["column"], f["on_delete"]) for f in table.get("foreign_keys", [])}
        assert fks == expected, f"{name}: foreign keys"

        indexes = {}
        for r in conn.execute(f"PRAGMA index_list('{name}')"):
            cols = tuple(i["name"] for i in conn.execute(f"PRAGMA index_info('{r['name']}')"))
            indexes[r["name"]] = (cols, bool(r["unique"]), bool(r["partial"]), r["origin"])
        for i in table.get("indexes", []):
            assert indexes[i["name"]][:3] == (tuple(i["columns"]), i["unique"], "where" in i), f"{name}: index {i['name']}"
        # Unique constraints (not named indexes): single-column UNIQUE and table-level UNIQUE (...)
        constraints = {cols for cols, unique, _, origin in indexes.values() if origin == "u"}
        wanted = {tuple(u) for u in table.get("unique", [])} | {(c["name"],) for c in table["columns"] if c.get("unique")}
        assert constraints == wanted, f"{name}: unique constraints"
        named = {n for n, v in indexes.items() if v[3] == "c"}
        assert named == {i["name"] for i in table.get("indexes", [])}, f"{name}: named indexes"

    assert {t["name"] for t in SCHEMA["tables"]} == tables(conn) - {"sqlite_sequence"}


# ---- the runner ------------------------------------------------------------------------------------


def test_nothing_to_do_makes_no_backup(tmp_path):
    folder = migrations(tmp_path, **{"0001_a_sql": "CREATE TABLE a (x INTEGER);"})
    path = tmp_path / "t.db"
    conn = db.connect(path)
    db.migrate(conn, folder, path)
    db.migrate(conn, folder, path)
    assert not list(tmp_path.glob("*.bak-*"))


def test_upgrading_an_existing_database_keeps_data_and_makes_a_backup(tmp_path):
    folder = migrations(tmp_path, **{"0001_a_sql": "CREATE TABLE a (x INTEGER);"})
    path = tmp_path / "t.db"
    conn = db.connect(path)
    db.migrate(conn, folder, path)
    conn.execute("INSERT INTO a VALUES (42)")

    migrations(tmp_path, **{"0002_b_sql": "CREATE TABLE b (y INTEGER); ALTER TABLE a ADD COLUMN z TEXT;"})
    assert db.migrate(conn, folder, path) == 2
    assert conn.execute("SELECT x, z FROM a").fetchone()[:] == (42, None)
    assert "b" in tables(conn)

    backup = sqlite3.connect(tmp_path / "t.db.bak-v1")  # the state before the upgrade
    assert version(backup) == 1
    assert "b" not in tables(backup)
    assert backup.execute("SELECT x FROM a").fetchone()[0] == 42


def test_a_failing_migration_changes_nothing(tmp_path):
    folder = migrations(tmp_path, **{"0001_a_sql": "CREATE TABLE a (x INTEGER);"})
    path = tmp_path / "t.db"
    conn = db.connect(path)
    db.migrate(conn, folder, path)
    migrations(tmp_path, **{"0002_bad_sql": "CREATE TABLE b (y INTEGER); INSERT INTO missing VALUES (1);"})
    with pytest.raises(sqlite3.Error):
        db.migrate(conn, folder, path)
    assert version(conn) == 1  # still the old version
    assert "b" not in tables(conn)  # and no half-applied table
    assert not conn.in_transaction


def test_a_database_newer_than_the_app_is_refused(tmp_path):
    folder = migrations(tmp_path, **{"0001_a_sql": "CREATE TABLE a (x INTEGER);"})
    path = tmp_path / "t.db"
    conn = db.connect(path)
    conn.execute("PRAGMA user_version = 7")
    with pytest.raises(RuntimeError, match="newer than this app"):
        db.migrate(conn, folder, path)
    with pytest.raises(RuntimeError):
        db.init_db(path, folder)  # the app would refuse to start
    assert "a" not in tables(conn)


def test_migrations_run_in_order(tmp_path):
    folder = migrations(
        tmp_path,
        **{
            "0002_second_sql": "INSERT INTO log VALUES ('second');",
            "0001_first_sql": "CREATE TABLE log (step TEXT); INSERT INTO log VALUES ('first');",
        },
    )
    conn = db.connect(tmp_path / "t.db")
    db.migrate(conn, folder)
    assert [r[0] for r in conn.execute("SELECT step FROM log ORDER BY rowid")] == ["first", "second"]
