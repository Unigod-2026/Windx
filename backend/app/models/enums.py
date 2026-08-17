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


class RegionStrategy(str, Enum):
    """How ``run_project`` picks region codes for the remote submit.

    - ``FIXED``: use the project's ``region_codes`` list verbatim.
    - ``NATIONAL_RANDOM``: pick a random subset from a national pool.
    """

    FIXED = "fixed"
    NATIONAL_RANDOM = "national_random"


class DeliveryMode(str, Enum):
    """Which surface the remote AI platform should answer from."""

    WEB = "web"
    MOBILE = "mobile"


class PromptStatus(str, Enum):
    """Per-prompt monitoring state.

    - ``monitoring`` — actively submitted on each scheduled run
    - ``paused`` — kept in the prompt list but excluded from runs
    - ``archived`` — soft-deleted; kept for historical run breakdowns
    """

    MONITORING = "monitoring"
    PAUSED = "paused"
    ARCHIVED = "archived"


class CompetitorOrigin(str, Enum):
    """How a ``ProjectCompetitor`` row was added to the project.

    Distinct from :class:`CompetitorSource` (which tags *where in the AI
    response* an automatically extracted mention came from — see the
    ``geo_competitors`` table).

    ``MANUAL`` — entered by the user in the project editor.
    ``AUTO_DISCOVERED`` — surfaced by the LLM extraction pass over a
    recent answer; sits in ``status=PENDING`` until the user confirms.
    """

    MANUAL = "manual"
    AUTO_DISCOVERED = "auto_discovered"


class CompetitorStatus(str, Enum):
    """Lifecycle of a ``ProjectCompetitor`` row.

    ``CONFIRMED`` — actively watched, ranks in the analysis.
    ``PENDING`` — Agent-discovered, awaiting user confirmation.
    ``DISMISSED`` — explicitly rejected by the user; excluded from
    future extraction but kept for audit.
    """

    CONFIRMED = "confirmed"
    PENDING = "pending"
    DISMISSED = "dismissed"


class ExtractStatus(str, Enum):
    """Pipeline state for a ``geo_brand_mentions`` row.

    ``PENDING`` — regex hit recorded, LLM pass not yet finished.
    ``SUCCESS`` — every field the LLM was supposed to fill is filled.
    ``FAILED`` — LLM call blew up; row still has the regex data so the
    count is honest, ``extract_error`` carries the traceback tail.
    ``SKIPPED`` — regex did not hit any brand; no LLM call needed.
    """

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
