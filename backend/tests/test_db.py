"""Tests for the SQLAlchemy engine and session factory.

These tests override ``DATABASE_URL`` via ``monkeypatch`` to point at an
in-memory SQLite engine so they don't depend on MySQL being available.
They then call :func:`app.db.reset_engine` so the lazy engine factory
rebuilds itself against the new URL. Accessing ``db_module.engine`` or
``db_module.SessionLocal`` triggers the rebuild.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import app.db as db_module


@pytest.fixture
def db_module_with_sqlite(monkeypatch: pytest.MonkeyPatch):
    """Reset the cached engine after pointing DATABASE_URL at SQLite.

    ``JWT_SECRET`` is forced for the same reason: ``Settings`` now requires
    it, so the lazy ``_build_engine`` call would otherwise raise during
    the test. ``get_settings.cache_clear()`` is also called so the next
    ``Settings()`` read picks up the patched env vars instead of returning
    a previously-cached instance.
    """
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    from app.config import get_settings

    get_settings.cache_clear()
    db_module.reset_engine()
    try:
        yield db_module
    finally:
        db_module.reset_engine()
        get_settings.cache_clear()


def test_engine_uses_sqlite_url(db_module_with_sqlite) -> None:
    """After overriding DATABASE_URL, the engine URL should not be mysql."""
    db_module = db_module_with_sqlite
    engine: Engine = db_module.engine
    assert "sqlite" in str(engine.url)


def test_sessionlocal_produces_usable_session(db_module_with_sqlite) -> None:
    """SessionLocal opens a session that can execute SELECT 1."""
    db_module = db_module_with_sqlite
    factory: sessionmaker = db_module.SessionLocal
    session: Session = factory()
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
