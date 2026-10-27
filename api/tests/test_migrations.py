"""Numbered database steps: each applied once, and a newer database refused."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vibestream import migrations  # noqa: E402


def _engine(tmp_path):
    return create_engine(f"sqlite:///{tmp_path / 'db.sqlite'}")


def test_a_new_database_starts_at_the_last_step(tmp_path):
    engine = _engine(tmp_path)
    migrations.migrate(engine, fresh=True)
    with engine.connect() as conn:
        assert migrations.schema(conn) == len(migrations.STEPS)


def test_an_old_database_takes_every_step_once(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE torrents (id INTEGER, origin TEXT)"))
        conn.execute(text("CREATE TABLE ratings (id INTEGER, value INTEGER)"))
        conn.execute(text("CREATE TABLE watch_states (id INTEGER)"))
        conn.execute(text("INSERT INTO torrents VALUES (1, 'torrentio'), (2, 'filelist')"))
        conn.execute(text("INSERT INTO ratings VALUES (1, 2), (2, -1)"))
    ran = []
    monkeypatch.setattr(migrations, "STEPS", migrations.STEPS + [lambda conn: ran.append(1)])
    migrations.migrate(engine, fresh=False)
    migrations.migrate(engine, fresh=False)
    with engine.connect() as conn:
        assert migrations.schema(conn) == len(migrations.STEPS)
        assert conn.execute(text("SELECT origin FROM torrents ORDER BY id")).scalars().all() == ["addon", "filelist"]
        assert conn.execute(text("SELECT value FROM ratings ORDER BY id")).scalars().all() == [1, -1]
        assert not conn.execute(text("SELECT name FROM sqlite_master WHERE name = 'watch_states'")).first()
    assert ran == [1]


def test_a_failed_step_leaves_the_schema_number_where_it_was(tmp_path, monkeypatch):
    engine = _engine(tmp_path)
    migrations.migrate(engine, fresh=True)

    def broken(conn):
        conn.execute(text("CREATE TABLE half (id INTEGER)"))
        raise RuntimeError("step failed")

    monkeypatch.setattr(migrations, "STEPS", migrations.STEPS + [broken])
    with pytest.raises(RuntimeError):
        migrations.migrate(engine, fresh=False)
    with engine.connect() as conn:
        assert migrations.schema(conn) == len(migrations.STEPS) - 1


def test_a_database_from_a_newer_version_is_refused(tmp_path):
    engine = _engine(tmp_path)
    with engine.begin() as conn:
        conn.exec_driver_sql(f"PRAGMA user_version = {len(migrations.STEPS) + 1}")
    with pytest.raises(migrations.NewerDatabase):
        migrations.migrate(engine, fresh=False)
