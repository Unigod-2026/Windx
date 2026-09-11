"""geo_brand_mentions: add is_correct column for LLM-judged answer accuracy.

需求:大模型拿着「项目核心卖点(最多 10 行)」+「subtask 回答」判断该
回答是否与卖点的内容相符(例:卖点说"这是眼霜",回答却完全无关眼霜 →
不正确;卖点说"医保产品",回答否认医保 → 不正确)。只对 ``is_self=true``
行做判断,``is_self=false`` 行保持 NULL(语义上不适用)。

数据来源:
- ``Project.semantic_json["selling_points"]``:用户在向导 step 6 填的
  核心卖点(最多 10 行;list[str])。
- ``Subtask.answer_content``:远端返回的 LLM 回答正文。

短路规则:项目无 ``selling_points`` 时不调 LLM,所有行 ``is_correct=True``
(用户没填卖点,谈不上"答错",项目记忆
``project_brand_nonempty`` 也说明 brand 一定有值)。

LLM 失败降级:抽 5s / 10s 两次重试,仍失败 → ``is_correct=None``,
``extract_status`` 不动(不抹掉 rank / sentiment / is_recommended 的
SUCCESS 状态)。

Revision ID: 20260911_0002
Revises: 20260911_0001
Create Date: 2026-09-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "20260911_0002"
down_revision = "20260911_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable:三态(NULL = 未判断 / 不适用,TRUE / FALSE = 评判结果)。
    # 历史行(迁移前已经存在的 BrandMention)保持 NULL,由
    # ``extraction._populate_correctness_pass`` 在下次 raw_result_json
    # 落地时回填。
    op.add_column(
        "geo_brand_mentions",
        sa.Column("is_correct", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("geo_brand_mentions", "is_correct")