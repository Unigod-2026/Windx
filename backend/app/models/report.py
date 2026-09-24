"""ORM model for the report metadata table.

Schema is owned by the alembic migration
``backend/alembic/versions/20260924_0001_geo_reports.py`` — see that
file for column-by-column rationale.  This module just exposes the
SQLAlchemy mapping so the rest of the codebase can ``from
app.models.report import Report``.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.common import created_at_column


class Report(Base):
    __tablename__ = "geo_reports"
    __table_args__ = (
        UniqueConstraint("file_path", name="uq_reports_file_path"),
        UniqueConstraint("share_token", name="uq_reports_share_token"),
        # List endpoint: ``WHERE project_id = ? ORDER BY created_at DESC``.
        Index(
            "ix_reports_project_generated",
            "project_id",
            text("created_at DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(Integer, nullable=False)
    customer_id: Mapped[int] = mapped_column(Integer, nullable=False)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    baseline_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    baseline_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # Stored relative to backend/ so the directory can move in deploy.
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # Human-readable scope string assembled at generate time, e.g.
    # ``近 7 天 · 5 档模型 · 8 个问题``. Stored on the row so historical
    # reports don't drift when toolbar options are added/removed later.
    # Migration ``20260924_0002`` adds this column with NOT NULL +
    # server_default="", so legacy rows (none currently exist) get an
    # empty string the UI renders as "未指定".
    scope_text: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default=""
    )
    # URL-safe 256-bit random token generated at report creation. Lets
    # the preview page be reached via ``/public/reports/{share_token}``
    # without any authentication, so a generated report can be shared
    # via IM (e.g. WeChat). Migration ``20260924_0003`` added the
    # column + UNIQUE constraint (declared in ``__table_args__`` below
    # — we don't use ``unique=True`` here because that auto-generates
    # an index named ``ix_geo_reports_share_token`` which the migration
    # doesn't create, and ``test_models_declare_the_same_indexes...``
    # fails on the drift).
    share_token: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default=""
    )
    generated_by_id: Mapped[int] = mapped_column(Integer, nullable=False)
    generated_by_name: Mapped[str] = mapped_column(String(64), nullable=False)
    # Operator-edited narrative content. Filled via the preview page
    # when the operator writes section prose after generation. Empty
    # dict {} means "nothing edited yet". Filled by PATCH
    # /api/reports/{id}.
    manual_overrides: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        # MySQL 8 forbids literal defaults on JSON; the migration uses
        # ``(JSON_OBJECT())`` expression default. Mirror that here so
        # ORM metadata stays in sync with DDL.
        server_default=text("(JSON_OBJECT())"),
    )
    # Public-link visibility gate. False = report is private (operator
    # only); true = public URL serves the rendered snapshot.
    is_published: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime] = created_at_column()

    def __repr__(self) -> str:
        return (
            f"<Report id={self.id} project_id={self.project_id} "
            f"template={self.template_id!r} period={self.period_start}~{self.period_end}>"
        )
