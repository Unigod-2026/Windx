"""geo_subtasks: add fields from updated Molizhishu subTaskList[] payload.

Revision ID: 20260910_0001
Revises: 20260909_0001
Create Date: 2026-09-10

背景
----
模力指数监控 API 的 ``GET /task/result/{taskId}`` 与
``GET /task/result/{taskId}/{subTaskId}`` 接口升级后,在 ``subTaskList[]``
返回了若干 ``geo_subtasks`` 之前没存的字段。完整字段对照见
https://raw.githubusercontent.com/molizhishu/molizhishu-api-pub/main/docs/api/get-task-result.md
(``subTaskList[]`` 段)。

新增列
------
- ``share_url``           : String(1024),AI 平台官方对话分享链接
- ``search_keywords_json`` : JSON,本次回答实际搜索词
                            (≠ 项目级 ``geo_project_keywords``,那是配置)
- ``video_list_json``      : JSON,回答中嵌入视频列表
- ``goods_json``           : JSON,回答中嵌入商品列表
- ``amount``               : Numeric(10, 4),本次子任务扣费金额(运营对账用)

Schema 设计
-----------
全部 nullable —— 历史 sync 不会回填这些字段,新 sync 写入才有值。下游
**当前没有**消费方(sync 是唯一生产方,前端无 UI 读取入口),所以这次纯
schema 推进,等真有 UI 需求再补消费方。

Downgrade
---------
直接 DROP,无 backfill 数据要回滚。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260910_0001"
down_revision = "20260909_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("geo_subtasks") as batch:
        batch.add_column(
            sa.Column("share_url", sa.String(length=1024), nullable=True)
        )
        batch.add_column(
            sa.Column("search_keywords_json", sa.JSON(), nullable=True)
        )
        batch.add_column(
            sa.Column("video_list_json", sa.JSON(), nullable=True)
        )
        batch.add_column(
            sa.Column("goods_json", sa.JSON(), nullable=True)
        )
        batch.add_column(
            sa.Column(
                "amount",
                sa.Numeric(precision=10, scale=4),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("geo_subtasks") as batch:
        batch.drop_column("amount")
        batch.drop_column("goods_json")
        batch.drop_column("video_list_json")
        batch.drop_column("search_keywords_json")
        batch.drop_column("share_url")
