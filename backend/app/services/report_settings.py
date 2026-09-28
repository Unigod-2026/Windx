"""Reads the per-project report configuration from a static JSON file.

The file lives at ``backend/configs/report_settings.json`` and looks like:

    {
      "projects": [
        { "project_id": 1, "baseline_date": "2026-06-01", "baseline_rate": 0.0083 }
      ],
      "templates": [
        {
          "id": "weekly_summary",
          "name": "GEO 周报（含整体走势 + 平台周环比）",
          "description": "项目本周 AI 平台提及率走势 + 各平台周环比"
        }
      ]
    }

Why a JSON file rather than a column on ``geo_projects``:
- The baseline date and value are **project-management metadata**, not
  monitoring data. They live outside the alembic-managed schema so we
  can tweak them without a migration.
- The number is a **frozen historical snapshot** taken at project
  kickoff; overwriting it would silently rewrite history. Putting it
  in a file that lives outside the data write path makes accidental
  writes harder.

The ``templates`` array is **display metadata only** (id / name /
description). It does NOT register templates — that lives in
``app.services.report_templates.TEMPLATES`` (Python code). The two
intersect in the API layer: ``GET /api/reports/templates`` returns
only ids that are registered AND have a metadata entry, so an
operator typo'd id or a code-deprecated template doesn't leak into
the UI.

Failure modes:
- File missing or unreadable → ``get_baseline`` returns ``(None, None)``,
  ``get_template_metadata`` returns ``{}``. The report endpoint still
  works, just without the "较基线" column and without templates listed.
- Project / template not in the file → same, ``(None, None)`` / ``None``.
- Malformed JSON → logged + ``(None, None)`` / ``{}``.  We deliberately
  do **not** raise, because the report view should degrade gracefully
  rather than 500 when an operator typo'd the file.

Cache invalidation:
- The cache is shared across both baselines and template metadata
  (single ``_cache_lock`` + ``_settings_cache``). Two refresh paths:
  1. **mtime auto-reload** — every read of the cache checks the file
     mtime against the cached value; if the file is newer, the cache
     transparently reloads. Operators edit
     ``report_settings.json`` and the next request sees the change
     without bouncing the API process.
  2. **explicit ``POST /api/admin/report-templates/reload``** —
     forces a reload even if mtime is unchanged (e.g. touch-less
     re-mount in containerised deploys where mtime is preserved).

  The mtime check uses ``Path.stat().st_mtime_ns`` so sub-second edits
  are detected. Touching the file (e.g. ``touch`` from a watcher
  script) without actually changing contents still triggers a reload
  — cheap, no harm.

  Tests that want deterministic behaviour call ``reset_cache()``
  before asserting; the mtime path stays out of the way when the
  file is unchanged.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolved once at import time so the path lives next to backend/
# regardless of CWD. backend/app/services/report_settings.py →
# backend/configs/report_settings.json.
_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "configs" / "report_settings.json"


@dataclass(frozen=True)
class Baseline:
    date: date | None
    rate: float | None


@dataclass(frozen=True)
class TemplateMetadata:
    """Display metadata for one report template.

    Held in code only as a typed view over the dict loaded from
    ``report_settings.json``. The ``id`` is the canonical identifier
    that ``report_templates.TEMPLATES`` keys against — the two must
    agree, but the source of truth for the *implementation* is the
    Python code; this dataclass just describes how the id is shown.
    """

    id: str
    name: str
    description: str | None


# Single cache holding both buckets — reload is atomic, so a half-
# reloaded state where templates reflect the new file but baselines
# reflect the old one is impossible. ``None`` means "not loaded yet"
# and triggers a read on first access.
_settings_cache: "_SettingsCache | None" = None
_cache_lock = threading.Lock()


@dataclass(frozen=True)
class _SettingsCache:
    baselines: dict[int, Baseline]
    templates: dict[str, TemplateMetadata]
    # mtime_ns of the file as observed when the cache was loaded.
    # Used by ``_get_cache`` to detect external edits since the last
    # load. ``None`` if the file didn't exist at load time.
    mtime_ns: Optional[int]


def _current_mtime_ns() -> Optional[int]:
    """Return the file's current mtime in nanoseconds, or ``None`` if
    the file is missing / unreadable. Cheap — single ``stat`` call."""
    try:
        return _DEFAULT_PATH.stat().st_mtime_ns
    except OSError:
        return None


def _load_locked() -> _SettingsCache:
    """Parse the settings file once. Caller must hold ``_cache_lock``."""
    baselines: dict[int, Baseline] = {}
    templates: dict[str, TemplateMetadata] = {}
    mtime_ns = _current_mtime_ns()
    if mtime_ns is None:
        # File missing — leave both buckets empty but record a
        # sentinel mtime so subsequent edits trigger a reload
        # once the operator creates the file.
        return _SettingsCache(
            baselines=baselines, templates=templates, mtime_ns=None
        )
    try:
        raw = json.loads(_DEFAULT_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("report_settings.json unreadable: %s", exc)
        return _SettingsCache(
            baselines=baselines, templates=templates, mtime_ns=mtime_ns
        )

    for entry in raw.get("projects", []) or []:
        try:
            pid = int(entry["project_id"])
            baseline_date = (
                date.fromisoformat(entry["baseline_date"])
                if entry.get("baseline_date")
                else None
            )
            baseline_rate = (
                float(entry["baseline_rate"])
                if entry.get("baseline_rate") is not None
                else None
            )
            baselines[pid] = Baseline(date=baseline_date, rate=baseline_rate)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "report_settings.json skipping malformed project entry %r: %s",
                entry,
                exc,
            )

    for entry in raw.get("templates", []) or []:
        try:
            tid = str(entry["id"]).strip()
            if not tid:
                raise ValueError("empty id")
            name = str(entry.get("name") or tid).strip() or tid
            description = (
                str(entry["description"]).strip()
                if entry.get("description")
                else None
            )
            templates[tid] = TemplateMetadata(
                id=tid,
                name=name,
                description=description,
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            logger.warning(
                "report_settings.json skipping malformed template entry %r: %s",
                entry,
                exc,
            )

    return _SettingsCache(
        baselines=baselines, templates=templates, mtime_ns=mtime_ns
    )


def _get_cache() -> _SettingsCache:
    """Return the current cache, transparently reloading if the
    underlying file's mtime has changed since the last load.

    The mtime check is intentionally conservative — we only reload
    when the cached ``mtime_ns`` differs from the current one, so a
    read-heavy endpoint (e.g. ``GET /api/reports/templates`` fired
    on every modal open) doesn't do a disk read on every request.
    """
    global _settings_cache
    with _cache_lock:
        if _settings_cache is not None:
            current_mtime = _current_mtime_ns()
            if current_mtime != _settings_cache.mtime_ns:
                logger.info(
                    "report_settings.json mtime changed (%s -> %s); reloading",
                    _settings_cache.mtime_ns,
                    current_mtime,
                )
                _settings_cache = _load_locked()
        else:
            _settings_cache = _load_locked()
        return _settings_cache


def get_baseline(project_id: int) -> Baseline | None:
    """Return the configured baseline for ``project_id``, or ``None`` if unset."""
    return _get_cache().baselines.get(project_id)


def get_template_metadata(template_id: str) -> TemplateMetadata | None:
    """Return the display metadata for a template id, or ``None`` if not
    configured in the file.

    This does NOT check whether the id is registered in
    ``report_templates.TEMPLATES`` — the API router does that
    intersection explicitly so we can report "configured but not
    implemented" separately.
    """
    return _get_cache().templates.get(template_id)


def list_template_metadata() -> dict[str, TemplateMetadata]:
    """Return all configured template metadata, keyed by id."""
    return dict(_get_cache().templates)


def reload_cache() -> _SettingsCache:
    """Force a fresh read of the settings file.

    Used by ``POST /api/admin/report-templates/reload`` so operators
    can edit ``report_settings.json`` and have the change visible
    immediately without restarting the API process. Returns the
    freshly-loaded cache so the route can return a summary.
    """
    global _settings_cache
    with _cache_lock:
        _settings_cache = _load_locked()
        return _settings_cache


def reset_cache() -> None:
    """Drop the cached settings. Used by tests."""
    global _settings_cache
    with _cache_lock:
        _settings_cache = None


def upsert_baseline(
    project_id: int,
    baseline_date: date,
    baseline_rate: float,
) -> Baseline:
    """Persist a baseline for ``project_id`` to ``report_settings.json``
    and update the in-memory cache.

    Called by the report-generation route after a successful POST so
    the operator's freshly-chosen baseline becomes the default for the
    next generation. We rewrite the whole file atomically via
    ``tmp + rename`` so a crash mid-write doesn't leave a half-written
    JSON the next request would refuse to parse.

    The file is intentionally simple — a list of records keyed by
    ``project_id``. We keep it JSON-safe (no ``datetime`` objects,
    no NaN, no comments) and tolerate a missing file by writing a
    fresh one with just this baseline + the existing templates.

    Args:
      project_id: positive int.
      baseline_date: ISO date — caller already validated.
      baseline_rate: 0.0 .. 1.0 — caller already validated.

    Returns: the persisted ``Baseline`` (always non-None; this call
    guarantees an entry exists).
    """
    if not (0.0 <= baseline_rate <= 1.0):
        raise ValueError(f"baseline_rate out of range: {baseline_rate}")
    if project_id <= 0:
        raise ValueError(f"project_id must be positive: {project_id}")

    new_entry = Baseline(
        date=baseline_date,
        rate=round(baseline_rate * 1e4) / 1e4 if baseline_rate is not None else None,
    )

    # Take the cache lock, mutate the cache in place, write to disk.
    # Holding the lock across the disk write keeps reload-and-write
    # from interleaving: an mtime check that fires mid-write would
    # otherwise re-read a partial file.
    global _settings_cache
    with _cache_lock:
        # Make sure the cache reflects the current file before we
        # merge our change.
        if _settings_cache is None:
            _settings_cache = _load_locked()
        # Rebuild the cache dict with the new baseline merged in.
        new_baselines = dict(_settings_cache.baselines)
        new_baselines[project_id] = new_entry
        _settings_cache = _SettingsCache(
            baselines=new_baselines,
            templates=_settings_cache.templates,
            mtime_ns=_settings_cache.mtime_ns,
        )
        _write_locked(new_baselines, _settings_cache.templates)
    return new_entry


def _write_locked(
    baselines: dict[int, Baseline],
    templates: dict[str, TemplateMetadata],
) -> None:
    """Serialize ``baselines`` + ``templates`` to disk. Caller must
    hold ``_cache_lock``.

    Atomic write strategy:
    1. Read whatever the file currently holds (if anything) and merge
       keys we don't know about — operators may have keys we don't
       model; we mustn't drop them on rewrite.
    2. Serialize to ``_DEFAULT_PATH.with_suffix('.json.tmp')``.
    3. ``os.replace(tmp, target)`` is atomic on POSIX and on Win32
       since Python 3.3.
    """
    import os

    existing: dict = {"projects": [], "templates": []}
    if _DEFAULT_PATH.is_file():
        try:
            existing = json.loads(_DEFAULT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning(
                "report_settings.json unreadable during rewrite; "
                "rewriting with merged content"
            )

    # Preserve unknown top-level keys (future-proofing for fields we
    # don't model yet).
    out: dict = dict(existing)
    out["projects"] = [
        {
            "project_id": pid,
            "baseline_date": b.date.isoformat() if b.date else None,
            "baseline_rate": b.rate,
        }
        for pid, b in sorted(baselines.items())
    ]
    out["templates"] = [
        {
            "id": t.id,
            "name": t.name,
            "description": t.description,
        }
        for t in templates.values()
    ]

    tmp = _DEFAULT_PATH.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, _DEFAULT_PATH)
