"""Shared model helpers: timezone, defaults, mixins.

All DATETIME columns in the schema are naive local time. The container and
MySQL session both run in Asia/Shanghai (see CLAUDE.md); the wall clock from
``datetime.now(SHANGHAI)`` matches what the database expects, so we drop the
tzinfo before storing.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta

from sqlalchemy import DateTime
from sqlalchemy.orm import mapped_column

# Asia/Shanghai is fixed UTC+8 — no DST.
SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


def now_local() -> datetime:
    """Naive ``datetime`` representing the current wall clock in Asia/Shanghai."""
    return datetime.now(SHANGHAI).replace(tzinfo=None)


def created_at_column() -> "mapped_column":
    return mapped_column(DateTime, default=now_local, nullable=False)


def updated_at_column() -> "mapped_column":
    return mapped_column(
        DateTime, default=now_local, onupdate=now_local, nullable=False
    )
