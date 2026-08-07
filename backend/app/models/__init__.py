"""ORM models for the windx backend.

Every model is imported here so ``from app.models import Customer`` works and
:class:`app.db.Base` sees all tables when ``metadata.create_all`` is called
(e.g. in tests).

The split into submodules roughly follows the table families:

- ``customer`` — multi-tenant boundary (``Customer`` + ``AdminUser``).
- ``project`` — projects, their config rows and the competitor log.
- ``task`` — ingestion tables (``Task`` / ``Subtask`` / ``Callback`` / ``Compensation``).
- ``schedule`` — embedded-schedule execution log (``ScheduleRun``).
- ``enums`` / ``common`` — shared Python enums and timezone-aware defaults.
"""

from __future__ import annotations

from app.models.common import SHANGHAI, now_local  # noqa: F401
from app.models.customer import AdminUser, Customer  # noqa: F401
from app.models.enums import (  # noqa: F401
    AdminRole,
    AdminStatus,
    CallbackProcessStatus,
    CompetitorSource,
    CustomerStatus,
    ProjectStatus,
    RunStatus,
    RunTrigger,
)
from app.models.project import (  # noqa: F401
    Competitor,
    Project,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.models.schedule import ScheduleRun  # noqa: F401
from app.models.task import (  # noqa: F401
    CallbackEvent,
    CompensationEvent,
    Subtask,
    Task,
)
