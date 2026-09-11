"""Schedule time helpers shared by the API and the APScheduler jobs.

Kept separate from ``app.api.projects`` so ``run_project`` can reuse the
exact same cooldown-key derivation — a mismatch between the two would
silently break dedupe between manual and cron triggers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.models.common import now_local


def next_run_at(
    monitor_days: list[str] | None,
    *,
    hour: int,
    minute: int,
    now: datetime | None = None,
) -> datetime | None:
    """Earliest upcoming fire time, or ``None`` if ``monitor_days`` is empty.

    ``monitor_days`` is the ISO weekday key list ("1".."7", Mon=1) from one
    mode's :class:`MonitorScheduleEntry`. Time-of-day is supplied separately
    (``MONITOR_DEFAULT_HOUR`` / ``MONITOR_DEFAULT_MINUTE`` env vars) — it
    used to live per-project in slot1/2_hour/minute, but ops wanted to
    shift the run window in one place. The earliest of the upcoming
    weekdays wins; if today is a configured day and the time hasn't
    passed, today wins.
    """
    if not monitor_days:
        return None
    now = now or now_local()
    today = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    candidates: list[datetime] = []
    for key in monitor_days:
        try:
            weekday = int(key)
        except (TypeError, ValueError):
            continue
        if weekday < 1 or weekday > 7:
            continue
        # Python: Monday=0..Sunday=6. Our keys: Monday=1..Sunday=7.
        delta = (weekday - 1) - now.weekday()
        candidate = today + timedelta(days=delta)
        if candidate <= now:
            candidate += timedelta(days=7)
        candidates.append(candidate)
    return min(candidates) if candidates else None


def next_run_per_mode(
    monitor_schedule: dict | None,
    *,
    hour: int,
    minute: int,
    now: datetime | None = None,
) -> dict[str, datetime | None]:
    """Earliest upcoming fire time per mode from ``monitor_schedule``.

    Returns ``{"fast": dt|None, "think": dt|None}`` — keys with no entry
    (or empty ``days``) map to ``None``. The list-page
    :attr:`ProjectOut.next_run_at` takes the min of these two so a project
    with both modes enabled shows the earliest fire across the union.
    """
    out: dict[str, datetime | None] = {"fast": None, "think": None}
    if not monitor_schedule:
        return out
    for mode in ("fast", "think"):
        entry = monitor_schedule.get(mode)
        if not isinstance(entry, dict):
            continue
        days = entry.get("days") or []
        out[mode] = next_run_at(list(days), hour=hour, minute=minute, now=now)
    return out


def earliest_next_run(
    monitor_schedule: dict | None,
    *,
    hour: int,
    minute: int,
    now: datetime | None = None,
) -> datetime | None:
    """Earliest ``next_run_per_mode`` across all modes — used by
    :attr:`ProjectOut.next_run_at` for the single-value list column.
    """
    per_mode = next_run_per_mode(
        monitor_schedule, hour=hour, minute=minute, now=now
    )
    candidates = [dt for dt in per_mode.values() if dt is not None]
    return min(candidates) if candidates else None


def cooldown_key(
    project_id: int,
    slot_index: int,
    now: datetime | None = None,
    *,
    mode: str = "",
) -> str:
    """``project-{id}-slot-{idx}-{mode}-{YYYYMMDDHH}{floor(minute/5)}`` (A.3).

    ``mode`` is appended so two cron jobs for the same project on the
    same weekday don't collide (one fires ``fast`` platforms, the other
    fires ``think``). Manual triggers pass ``mode=""`` and the existing
    shape (without the trailing ``-mode`` segment for the empty string)
    is preserved so historical rows still collide on the same key.
    """
    now = now or now_local()
    base = (
        f"project-{project_id}-slot-{slot_index}"
        f"-{now.strftime('%Y%m%d%H')}{now.minute // 5}"
    )
    if mode:
        return f"{base}-{mode}"
    return base