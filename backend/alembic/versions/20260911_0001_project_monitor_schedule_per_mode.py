"""geo_projects: replace monitor_freq + monitor_days with monitor_schedule (per-mode).

需求:每个监控项目可以独立配置快速模式和思考模式的频率/日期,所以旧
的单组 ``monitor_freq`` + ``monitor_days`` 不够用。新形状::

    monitor_schedule: {"fast": {"freq": "w1", "days": ["1"]},
                       "think": {"freq": "w2", "days": ["3", "5"]}}

迁移策略(用户确认):
- **只赋 fast**:旧 freq/days 写入 ``fast`` 键,``think`` 留空。带 think
  平台(``thinking_mode=true``)的老项目暂时不再被调度,需要 super_admin
  在项目编辑面板手动补 think schedule —— 副作用是有意为之,避免歧义。
- **直接 drop 旧列**:``monitor_freq`` / ``monitor_days`` 不保留 fallback。

Revision ID: 20260911_0001
Revises: 20260910_0002
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy import JSON, String

# revision identifiers, used by Alembic.
revision = "20260911_0001"
down_revision = "20260910_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. 新列先建出来,允许 NULL —— 走审批流的 PENDING 项目压根还没 schedule,
    #    ``schedule_enabled`` 一开始就是 False,空 dict 也能表达「没排」。
    op.add_column(
        "geo_projects",
        sa.Column("monitor_schedule", JSON, nullable=True),
    )

    # 2. 回填:旧 freq/days 同时存在时,写进 ``fast`` 键;``think`` 不写(等价 null)。
    #    用 connection.execute 直连,绕过 ORM 的实例化成本。
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE geo_projects
            SET monitor_schedule = JSON_OBJECT(
                'fast', JSON_OBJECT('freq', monitor_freq, 'days', monitor_days)
            )
            WHERE monitor_freq IS NOT NULL AND monitor_days IS NOT NULL
            """
        )
    )

    # 3. drop 旧列(monitor_freq / monitor_days)。Alembic 在 MySQL 上需要显式
    #    existing_type 才能 drop —— 这里都 nullable,直接给类型即可。
    op.drop_column("geo_projects", "monitor_freq")
    op.drop_column("geo_projects", "monitor_days")

    # 4. ScheduleRun.mode 列。新建走 default '' 兼容历史 NULL —— 旧行
    #    (manual trigger,没有 mode 概念)落 '';新行(cron 触发)落 'fast' / 'think'。
    op.add_column(
        "geo_schedule_runs",
        sa.Column("mode", String(16), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("geo_schedule_runs", "mode")

    op.add_column(
        "geo_projects",
        sa.Column("monitor_freq", String(8), nullable=True),
    )
    op.add_column(
        "geo_projects",
        sa.Column("monitor_days", JSON, nullable=True),
    )
    # 把 fast 键里的 freq/days 写回旧列,其他 mode 丢弃。
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE geo_projects
            SET monitor_freq = JSON_UNQUOTE(JSON_EXTRACT(monitor_schedule, '$.fast.freq')),
                monitor_days = JSON_EXTRACT(monitor_schedule, '$.fast.days')
            WHERE monitor_schedule IS NOT NULL
              AND JSON_EXTRACT(monitor_schedule, '$.fast.freq') IS NOT NULL
            """
        )
    )

    op.drop_column("geo_projects", "monitor_schedule")
