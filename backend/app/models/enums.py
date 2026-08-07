"""Python ``enum.Enum`` mirrors of the migration's MySQL ``ENUM`` columns.

Each enum's ``.value`` is the exact string stored in the database — that is also
what ``deps.py`` and the API layer compare against, so equality with strings
(e.g. ``AdminRole.SUPER_ADMIN == "super_admin"``) must hold.
"""

from __future__ import annotations

from enum import Enum


class CustomerStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class AdminRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    CUSTOMER_ADMIN = "customer_admin"


class AdminStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"


class RunTrigger(str, Enum):
    CRON = "cron"
    MANUAL = "manual"


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


class CompetitorSource(str, Enum):
    ANSWER_CONTENT = "answer_content"
    REFERENCE_LIST = "reference_list"


class CallbackProcessStatus(str, Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    FAILED = "failed"
