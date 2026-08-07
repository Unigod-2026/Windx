"""Schedule time helpers shared by the API and (later) the APScheduler jobs.

Kept separate from ``app.api.projects`` so Task 7's ``run_project`` can
reuse the exact same cooldown-key derivation — a mismatch between the two
would silently break dedupe between manual and cron triggers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.common import now_local


def next_run_at(slots: list[dict], *, now: datetime | None = None) -> datetime | None:
    """Earliest upcoming occurrence of any daily slot, or ``None`` if no slots.

    Slots are daily wall-clock times in Asia/Shanghai; a slot whose time has
    already passed today rolls over to tomorrow.
    """
    if not slots:
        return None
    now = now or now_local()
    candidates = []
    for slot in slots:
        today = now.replace(
            hour=slot["hour"], minute=slot["minute"], second=0, microsecond=0
        )
        candidates.append(today if today > now else today + timedelta(days=1))
    return min(candidates)


def cooldown_key(project_id: int, slot_index: int, now: datetime | None = None) -> str:
    """``project-{id}-slot-{idx}-{YYYYMMDDHH}{floor(minute/5)}`` (Appendix A.3).

    The trailing bucket collapses every 5 minutes into one key, so repeat
    triggers inside that window collide on the ``cooldown_key`` unique index.
    """
    now = now or now_local()
    return f"project-{project_id}-slot-{slot_index}-{now.strftime('%Y%m%d%H')}{now.minute // 5}"
