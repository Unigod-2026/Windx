from collections.abc import Iterator

from sqlalchemy import event
from sqlalchemy.engine import Engine


class QueryCounter:
    """记录 SQLAlchemy 在 block 内执行的 SQL 语句条数。

    只统计核心业务 SELECT/UPDATE/INSERT/DELETE;通过 ``before_cursor_execute``
    事件钩子捕获,跨连接共享同一个 counter 实例。
    """

    def __init__(self, engine: Engine) -> None:
        self.engine = engine
        self.count = 0
        self.queries: list[str] = []

    def __enter__(self) -> "QueryCounter":
        event.listen(self.engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        event.remove(self.engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, params, context, executemany) -> None:
        normalized = statement.strip().split()[0].upper()
        if normalized not in {"SELECT", "INSERT", "UPDATE", "DELETE"}:
            return
        self.count += 1
        self.queries.append(statement)


def assert_query_budget(counter: QueryCounter, budget: int, *, label: str) -> None:
    if counter.count > budget:
        detail = "\n".join(f"  {i + 1}. {q[:200]}" for i, q in enumerate(counter.queries))
        raise AssertionError(
            f"{label}: query budget {budget} exceeded, got {counter.count}\n{detail}"
        )