"""Persistent logging setup.

By default Python's logging writes to stderr only, so any error that
happens between restarts is lost. The lifespan handler in :mod:`app.main`
calls :func:`configure_logging` to mirror every record (including the
``uvicorn`` / ``apscheduler`` / ``app`` loggers) into a rotating file
under ``$LOG_DIR``.

The log directory and level are pulled from :class:`Settings`; relative
paths resolve against the backend working dir so a fresh checkout can
just point at ``./logs`` and have the folder auto-created.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import get_settings


_CONFIGURED = False


def configure_logging() -> None:
    """Idempotent file-handler install for the app / uvicorn / apscheduler tree.

    Safe to call multiple times: subsequent calls are no-ops so tests that
    re-trigger the lifespan handler don't pile up handlers.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    settings = get_settings()
    log_dir = settings.log_dir or "./logs"
    level_name = (settings.log_level or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    log_path = Path(log_dir)
    if not log_path.is_absolute():
        log_path = Path.cwd() / log_path
    log_path.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path / "app.log",
        maxBytes=10 * 1024 * 1024,  # 10 MiB per file
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)

    # Mirror everything under the ``app`` namespace plus the third-party
    # loggers that are actually useful (uvicorn catches request errors;
    # apscheduler is the cron tick path).
    root = logging.getLogger()
    root.setLevel(level)
    # Avoid stacking a second rotating handler on every reload.
    if not any(
        isinstance(h, RotatingFileHandler) and getattr(h, "baseFilename", "").endswith("app.log")
        for h in root.handlers
    ):
        root.addHandler(file_handler)

    for name in ("app", "uvicorn", "uvicorn.error", "uvicorn.access", "apscheduler"):
        lg = logging.getLogger(name)
        lg.setLevel(level)
        # Let the message bubble up to root so a single handler covers
        # everything; setting propagate=True is the default but we set
        # it explicitly to be defensive against future code that flips it.
        lg.propagate = True

    _CONFIGURED = True
    logging.getLogger("app").info(
        "logging configured: dir=%s level=%s", log_path, level_name
    )
