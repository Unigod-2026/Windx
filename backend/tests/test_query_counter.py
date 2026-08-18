from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from ._query_counter import QueryCounter, assert_query_budget


def _memory_engine():
    return create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )


def test_counts_select_only():
    engine = _memory_engine()
    with QueryCounter(engine) as counter:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            conn.execute(text("SELECT 2"))
    assert counter.count == 2


def test_budget_pass():
    engine = _memory_engine()
    with QueryCounter(engine) as counter:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    assert_query_budget(counter, 2, label="smoke")


def test_budget_fail_shows_queries():
    engine = _memory_engine()
    try:
        with QueryCounter(engine) as counter:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
                conn.execute(text("SELECT 2"))
        assert_query_budget(counter, 1, label="smoke")
    except AssertionError as exc:
        assert "got 2" in str(exc)
        assert "SELECT 1" in str(exc)
    else:
        raise AssertionError("expected AssertionError")