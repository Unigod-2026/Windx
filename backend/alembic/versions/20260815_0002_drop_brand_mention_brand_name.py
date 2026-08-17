"""drop geo_brand_mentions.brand_name

Revision ID: 20260815_0002
Revises: 20260815_0001
Create Date: 2026-08-15

Rationale
---------
``brand_name`` was the literal string the regex actually matched (e.g.
"deepseek 旗舰版" vs the canonical "deepseek"). The information was only
useful as a "via alias" footnote in the UI; the canonical form and
alias set are already authoritatively stored on the parent tables:

- self: ``geo_projects.brand`` + ``geo_projects.aliases``
- competitor: ``geo_project_competitors.name`` + ``geo_project_competitors.aliases``

So ``brand_name`` was strictly redundant: every value ever written
could be recovered by looking up the canonical's alias list and picking
the matched needle. It was never queried (no API consumer reads it
out), never indexed, and never used to drive a metric.

Downgrade is no-op (information-losing), consistent with the
cap-mention-count-to-down migration that came before it.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260815_0002"
down_revision = "20260815_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("geo_brand_mentions", "brand_name")


def downgrade() -> None:
    # No-op: the original per-row literal isn't preserved anywhere, so
    # we can't recreate the column with its real values.
    pass