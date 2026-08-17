"""Unit tests for the molizhishu client's pre-flight validation.

The :func:`validate_platforms` helper is what the scheduler calls before
shipping a batch to the live remote. These tests cover the supported /
unsupported split without touching the network — the remote's accepted
set drifts (e.g. ``wenxinyiyan`` was removed from prod but is still in
docs/api/submit-task.md), so locking the contract here makes regressions
visible at PR time.
"""

from __future__ import annotations

import pytest

from app.services.molizhishu_client import (
    MOLIZHISHU_SUPPORTED_MODES,
    MOLIZHISHU_SUPPORTED_PLATFORMS,
    UnsupportedPlatformError,
    validate_platforms,
)


def _row(platform: str, mode: str = "standard") -> dict:
    return {"platform": platform, "mode": mode, "screenshot": 0}


def test_empty_payload_is_accepted() -> None:
    # No platforms = nothing to validate. Scheduler rejects an empty
    # platform list separately; that's not this function's job.
    validate_platforms([])


def test_all_supported_passes() -> None:
    rows = [
        _row("deepseek", "standard"),
        _row("doubao", "search"),
        _row("kimi", "reasoning"),
        _row("quark", "reasoning_search"),
    ]
    validate_platforms(rows)


def test_wenxinyiyan_is_unsupported() -> None:
    # wenxinyiyan is in docs but the live remote rejects it — see
    # MOLIZHISHU_SUPPORTED_PLATFORMS docstring.
    assert "wenxinyiyan" not in MOLIZHISHU_SUPPORTED_PLATFORMS
    with pytest.raises(UnsupportedPlatformError) as exc_info:
        validate_platforms([_row("wenxinyiyan")])
    assert exc_info.value.bad_platforms == ["wenxinyiyan"]
    assert exc_info.value.bad_modes == []


def test_unsupported_mode_is_rejected() -> None:
    # ``web`` / ``mobile`` describe the delivery surface, not the LLM
    # mode — they belong on ``delivery_mode`` (a separate, non-forwarded
    # field), not in the ``mode`` slot.
    with pytest.raises(UnsupportedPlatformError) as exc_info:
        validate_platforms([_row("deepseek", "web")])
    assert exc_info.value.bad_platforms == []
    assert exc_info.value.bad_modes == ["web"]


def test_multiple_bad_rows_are_deduplicated() -> None:
    # Two rows with the same bad platform should appear once in the error.
    rows = [
        _row("wenxinyiyan", "search"),
        _row("wenxinyiyan", "standard"),
        _row("deepseek", "web"),
    ]
    with pytest.raises(UnsupportedPlatformError) as exc_info:
        validate_platforms(rows)
    assert exc_info.value.bad_platforms == ["wenxinyiyan"]
    assert exc_info.value.bad_modes == ["web"]


def test_error_message_lists_supported_set() -> None:
    # The admin-facing message must include the supported set so they
    # can fix their config without reading source.
    with pytest.raises(UnsupportedPlatformError) as exc_info:
        validate_platforms([_row("wenxinyiyan"), _row("deepseek", "web")])
    msg = str(exc_info.value)
    assert "wenxinyiyan" in msg
    assert "web" in msg
    assert "supported" in msg