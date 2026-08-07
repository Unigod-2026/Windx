"""SQLAlchemy engine and session factory.

The engine is built lazily: ``engine`` and ``SessionLocal`` are populated on
first use via :func:`_ensure_engine_initialized`, not at module import. This
keeps ``import app.db`` side-effect free so tests and tools that only want
to read configuration are not forced to construct a database connection.

The active engine is also re-buildable via :func:`reset_engine`, which clears
the cached globals. Tests that swap ``DATABASE_URL`` (and therefore the
cached settings) call this to ensure the next access reflects the new URL.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def _build_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=3600,
        future=True,
    )


def _ensure_engine_initialized() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = _build_engine()
        _SessionLocal = sessionmaker(
            bind=_engine, autoflush=False, autocommit=False, future=True
        )
    return _engine


def reset_engine() -> None:
    """Discard the cached engine/sessionmaker so the next use rebuilds them.

    Intended for tests that override ``DATABASE_URL`` after the module has
    already been imported.
    """
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def get_engine() -> Engine:
    return _ensure_engine_initialized()


def get_session_factory() -> sessionmaker:
    _ensure_engine_initialized()
    assert _SessionLocal is not None  # for type checkers
    return _SessionLocal


# Module-level proxies retained for backwards compatibility with existing
# call sites (``from app.db import engine, SessionLocal``). They are
# materialized lazily through __getattr__ so import itself is side-effect
# free.

def __getattr__(name: str):
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_db():
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
