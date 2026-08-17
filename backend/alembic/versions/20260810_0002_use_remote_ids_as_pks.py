"""switch geo_tasks / geo_subtasks primary keys to remote task_id / subtask_id

Revision ID: 20260810_0002
Revises: 20260810_0001
Create Date: 2026-08-10

MySQL-only migration. SQLite (used by the backend test suite) skips this
revision and relies on ``Base.metadata.create_all`` to produce the current
schema directly from the SQLAlchemy models — see the ``test_migrations``
fixture.

Why this migration exists
-------------------------
The auto-increment ``id`` columns on ``geo_tasks`` and ``geo_subtasks`` were
a remnant of treating these tables as local-only logs. Every Task row
corresponds to a single molizhishu API submission and the remote
``taskId`` (32-char hex) is globally unique — so we use it as the PK and
drop the surrogate id.

The same logic applies to ``geo_subtasks`` and the remote ``subTaskId``.

Consequences:

1. ``Subtask.task_id`` widens from INT to VARCHAR(64) (the remote id).
2. ``Competitor.task_id`` / ``Competitor.subtask_id`` widen from INT to
   VARCHAR(64).
3. ``geo_schedule_runs.task_id`` widens from INT to VARCHAR(64).

Pre-flight: foreign keys
------------------------
This migration does *not* drop the FKs from ``geo_subtasks.task_id`` and
``geo_competitors.task_id`` / ``geo_competitors.subtask_id``. The operator
removes them out-of-band before applying this migration, because:

- The application-layer SQLAlchemy models already declare these columns
  with no FK constraint.
- Letting MySQL drop a FK that's about to lose its referenced column
  produces a clearer error if the FK is still in place than letting this
  migration silently struggle with the PK swap.

The required pre-flight on MySQL is::

    ALTER TABLE geo_subtasks    DROP FOREIGN KEY fk_subtasks_task;
    ALTER TABLE geo_competitors DROP FOREIGN KEY fk_competitors_task;
    ALTER TABLE geo_competitors DROP FOREIGN KEY fk_competitors_subtask;

Why the manual dance
--------------------
MySQL refuses to ``DROP PRIMARY KEY`` while the column is still
``AUTO_INCREMENT`` (error 1075), so each PK swap is preceded by a
``MODIFY id <type> NOT NULL`` to strip the auto-increment flag.
"""

from __future__ import annotations

from alembic import op

revision = "20260810_0002"
down_revision = "20260810_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- 1. Backfill any pre-existing rows ---------------------------------
    # Map local surrogate ids to remote task_id strings before the id columns
    # are dropped. With the FKs gone this is a plain join.
    op.execute(
        """
        UPDATE geo_subtasks s
          JOIN geo_tasks t ON t.id = s.task_id
           SET s.task_id = t.task_id
        """
    )
    op.execute(
        """
        UPDATE geo_schedule_runs r
          JOIN geo_tasks t ON t.id = r.task_id
           SET r.task_id = t.task_id
         WHERE r.task_id IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE geo_competitors c
          JOIN geo_tasks t ON t.id = c.task_id
           SET c.task_id = t.task_id
        """
    )
    op.execute(
        """
        UPDATE geo_competitors c
          JOIN geo_subtasks s ON s.id = c.subtask_id
           SET c.subtask_id = s.subtask_id
         WHERE c.subtask_id IS NOT NULL
        """
    )

    # ---- 2. geo_subtasks: strip auto_increment, swap PK to subtask_id ------
    op.execute("ALTER TABLE geo_subtasks MODIFY task_id VARCHAR(64) NOT NULL")
    op.execute("ALTER TABLE geo_subtasks MODIFY id INT NOT NULL")
    op.execute("ALTER TABLE geo_subtasks DROP PRIMARY KEY")
    op.execute("ALTER TABLE geo_subtasks DROP COLUMN id")
    op.execute("ALTER TABLE geo_subtasks DROP INDEX uq_subtasks_subtask_id")
    op.execute("ALTER TABLE geo_subtasks ADD PRIMARY KEY (subtask_id)")

    # ---- 3. geo_tasks: strip auto_increment, swap PK to task_id ------------
    op.execute("ALTER TABLE geo_tasks MODIFY id INT NOT NULL")
    op.execute("ALTER TABLE geo_tasks DROP PRIMARY KEY")
    op.execute("ALTER TABLE geo_tasks DROP COLUMN id")
    op.execute("ALTER TABLE geo_tasks DROP INDEX uq_tasks_task_id")
    op.execute("ALTER TABLE geo_tasks ADD PRIMARY KEY (task_id)")

    # ---- 4. Re-type the now-orphan reference columns -----------------------
    op.execute("ALTER TABLE geo_competitors MODIFY task_id VARCHAR(64) NOT NULL")
    op.execute("ALTER TABLE geo_competitors MODIFY subtask_id VARCHAR(64) NULL")
    op.execute("ALTER TABLE geo_schedule_runs MODIFY task_id VARCHAR(64) NULL")


def downgrade() -> None:
    # Restore the surrogate id columns. The remote task_id strings are
    # preserved on each row, but we cannot recover the original
    # auto-increment values, so we let MySQL assign fresh ones.
    # Foreign keys are intentionally NOT recreated — see module docstring.
    op.execute("ALTER TABLE geo_schedule_runs MODIFY task_id INT NULL")
    op.execute("ALTER TABLE geo_competitors MODIFY subtask_id INT NULL")
    op.execute("ALTER TABLE geo_competitors MODIFY task_id INT NOT NULL")

    op.execute("ALTER TABLE geo_tasks DROP PRIMARY KEY")
    op.execute("ALTER TABLE geo_tasks ADD COLUMN id INT NOT NULL AUTO_INCREMENT FIRST")
    op.execute("ALTER TABLE geo_tasks ADD PRIMARY KEY (id)")
    op.execute("ALTER TABLE geo_tasks ADD CONSTRAINT uq_tasks_task_id UNIQUE (task_id)")

    op.execute("ALTER TABLE geo_subtasks DROP PRIMARY KEY")
    op.execute("ALTER TABLE geo_subtasks MODIFY task_id INT NOT NULL")
    op.execute(
        "ALTER TABLE geo_subtasks ADD COLUMN id INT NOT NULL AUTO_INCREMENT FIRST"
    )
    op.execute("ALTER TABLE geo_subtasks ADD PRIMARY KEY (id)")
    op.execute(
        "ALTER TABLE geo_subtasks ADD CONSTRAINT uq_subtasks_subtask_id UNIQUE (subtask_id)"
    )
