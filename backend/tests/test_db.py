"""Tests for the SQLAlchemy engine and session factory.

These tests override DATABASE_URL via monkeypatch to use an in-memory SQLite
engine so they don't depend on MySQL being available. They directly import
``app.db`` and inspect ``app.db.engine`` after rebuilding it with the swapped
settings.
"""

import importlib
from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session


@pytest.fixture
def db_module_with_sqlite(monkeypatch: pytest.MonkeyPatch):
    """Reload app.db with DATABASE_URL pointing at in-memory SQLite.

    Yields the reloaded module so tests can inspect ``db_module.engine`` and
    ``db_module.SessionLocal`` after the env override.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "test-secret")  # required by Settings

    from app import config

    config.get_settings.cache_clear()
    from app import db as db_module

    importlib.reload(db_module)
    try:
        yield db_module
    finally:
        importlib.reload(db_module)


def test_engine_uses_sqlite_url(db_module_with_sqlite) -> None:
    """After overriding DATABASE_URL, the engine URL should not be mysql."""
    db_module = db_module_with_sqlite
    assert "sqlite" in str(db_module.engine.url)


def test_sessionlocal_produces_usable_session(db_module_with_sqlite) -> None:
    """SessionLocal opens a session that can execute SELECT 1."""
    db_module = db_module_with_sqlite
    session: Session = db_module.SessionLocal()
    try:
        result = session.execute(text("SELECT 1")).scalar_one()
        assert result == 1
    finally:
        session.close()


def test_get_db_yields_session_then_closes(db_module_with_sqlite) -> None:
    """The get_db dependency yields a Session and closes it after the consumer exits."""
    db_module = db_module_with_sqlite
    gen: Iterator[Session] = db_module.get_db()
    session = next(gen)
    assert isinstance(session, Session)
    # Triggering cleanup should close the session; iterating again raises StopIteration.
    with pytest.raises(StopIteration):
        next(gen)
