"""geo_tasks.import_batch_id 加索引。

背景：撤销一次导入 / 计算删除影响时都按 ``WHERE import_batch_id = ?``
找 task，没有索引就是 ``geo_tasks`` 全表扫 —— 批次列表页每打开一次详情
就扫一遍。

Revision ID: 20261104_0002
Revises: 20261104_0001
Create Date: 2026-11-04
"""

from __future__ import annotations

from alembic import op

revision = "20261104_0002"
down_revision = "20261104_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_tasks_import_batch", "geo_tasks", ["import_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_tasks_import_batch", table_name="geo_tasks")
