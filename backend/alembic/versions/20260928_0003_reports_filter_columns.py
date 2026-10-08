"""geo_reports 加 filter_prompts + filter_platform_codes,持久化生成时的筛选条件。

背景:``generate_report`` 把 toolbar 选的 ``platform_codes`` 和 ``prompts``
都接到了 payload,但写完行就返回;snapshot 是 ``GET /api/reports/{id}`` 临时
重算的,那里的 ``BuildContext`` 把这两个字段硬编码成 ``None``。于是「选了
3 个模型 + 10 个问题」只是写进了 ``scope_text`` 的展示文案,从未真正作为
指标函数的过滤项。

修复:把「生成时刻解析后的结果」存到行里 —— ``filter_prompts`` 存 prompt
**文本**(不是 ID,这样 GET 时不必再查 ``geo_project_prompts``,且 prompt 之后
被改名/删除也不会影响历史报告);``filter_platform_codes`` 原样存。预览 / 公网
HTML 都基于 GET snapshot,筛选自然贯穿。

两列都允许 NULL:历史报告(NULL 列)= 无筛选 = 行为与改动前一致,零迁移代价。

Revision ID: 20260928_0003
Revises: 20260928_0002
Create Date: 2026-09-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260928_0003"
down_revision = "20260928_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "geo_reports",
        sa.Column("filter_prompts", sa.JSON, nullable=True),
    )
    op.add_column(
        "geo_reports",
        sa.Column("filter_platform_codes", sa.JSON, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_reports", "filter_platform_codes")
    op.drop_column("geo_reports", "filter_prompts")