import pytest

from recsys import core


def version():
    with core.db() as c:
        return c.execute("PRAGMA user_version").fetchone()[0]


def test_fresh_database_is_at_the_current_schema(rs):
    assert version() == core.SCHEMA


def test_init_is_idempotent(rs):
    core.init()
    assert version() == core.SCHEMA


def test_migrations_run_once_in_order(rs, monkeypatch):
    ran = []
    monkeypatch.setattr(core, "SCHEMA", 3)
    monkeypatch.setattr(core, "MIGRATIONS", {**core.MIGRATIONS, 2: lambda c: ran.append(2), 3: lambda c: ran.append(3)})
    core.init()
    core.init()
    assert ran == [2, 3] and version() == 3


def test_refuses_a_newer_database(rs):
    with core.db() as c:
        c.execute(f"PRAGMA user_version = {core.SCHEMA + 1}")
    with pytest.raises(RuntimeError, match="newer"):
        core.init()
