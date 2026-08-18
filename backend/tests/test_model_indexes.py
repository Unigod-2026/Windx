"""Verify SQLAlchemy model declarations match Alembic migration for question analytics indexes."""

from __future__ import annotations

from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.models.project import BrandMention
from app.models.task import Subtask

# SQLite in-memory — ``mysql_length`` is dialect-gated on MySQL and silently
# ignored on SQLite, so the indexes still come out with the expected names.
test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)

# Importing ``app.models`` registers every model on ``Base.metadata``.
import app.models  # noqa: F401  pylint: disable=unused-import
from app.db import Base

Base.metadata.create_all(test_engine)


def test_subtask_has_prompt_updated_index():
    mapper = inspect(Subtask)
    names = {idx.name for idx in mapper.local_table.indexes}
    assert "ix_subtasks_prompt_updated" in names


def test_brand_mention_has_proj_self_prompt_created_index():
    mapper = inspect(BrandMention)
    names = {idx.name for idx in mapper.local_table.indexes}
    assert "ix_brand_mentions_proj_self_prompt_created" in names