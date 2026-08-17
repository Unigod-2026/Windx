from __future__ import annotations

import asyncio
from typing import Any, Iterable

import httpx


# Platforms the live molizhishu endpoint accepts. Source: docs/api/submit-task.md
# §平台. ``wenxinyiyan`` is still listed in docs but prod rejects it at submit
# time ("暂不支持以下模型: wenxinyiyan") so it's intentionally omitted here —
# callers should fail loud instead of submitting a row that will be rejected.
MOLIZHISHU_SUPPORTED_PLATFORMS: frozenset[str] = frozenset(
    {
        "deepseek",
        "doubao",
        "yuanbao",
        "kimi",
        "qianwen",
        "quark",
        "baiduai",
        "weibo_zhisou",
        "doubao_mobile",
    }
)

# Modes the live endpoint accepts. ``web`` / ``mobile`` are NOT valid here —
# those describe the delivery surface and belong on ``delivery_mode`` (a
# separate field that's intentionally not forwarded; the live remote has no
# concept of surface choice).
MOLIZHISHU_SUPPORTED_MODES: frozenset[str] = frozenset(
    {"standard", "reasoning", "search", "reasoning_search"}
)


class UnsupportedPlatformError(ValueError):
    """Raised before submit when the local config names a platform or mode
    the live molizhishu remote doesn't accept.

    Surfaced via :func:`app.services.scheduler.run_project` → caught by the
    outer ``except Exception`` and persisted to ``schedule_runs.error_message``
    so the admin sees which row in their config is bad.
    """

    def __init__(self, bad_platforms: list[str], bad_modes: list[str]):
        self.bad_platforms = bad_platforms
        self.bad_modes = bad_modes
        parts: list[str] = []
        if bad_platforms:
            parts.append(
                f"unsupported platform(s) {bad_platforms}; "
                f"supported = {sorted(MOLIZHISHU_SUPPORTED_PLATFORMS)}"
            )
        if bad_modes:
            parts.append(
                f"unsupported mode(s) {bad_modes}; "
                f"supported = {sorted(MOLIZHISHU_SUPPORTED_MODES)}"
            )
        super().__init__("molizhishu " + "; ".join(parts))


def validate_platforms(platforms: list[dict]) -> None:
    """Pre-flight check before :meth:`MolizhishuClient.submit_task`.

    Raises :class:`UnsupportedPlatformError` if any platform / mode isn't in
    the live remote's accepted set. Keeping this client-side means the
    operator gets a clear message instead of a vague HTTP error from prod.
    """
    bad_platforms = sorted(
        {p["platform"] for p in platforms if p["platform"] not in MOLIZHISHU_SUPPORTED_PLATFORMS}
    )
    bad_modes = sorted(
        {p["mode"] for p in platforms if p["mode"] not in MOLIZHISHU_SUPPORTED_MODES}
    )
    if bad_platforms or bad_modes:
        raise UnsupportedPlatformError(bad_platforms, bad_modes)


class MolizhishuError(Exception):
    def __init__(
        self,
        code: int | None,
        message: str,
        http_status: int | None = None,
        body: Any = None,
    ):
        super().__init__(f"molizhishu error code={code} message={message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.body = body


def _unwrap(response: httpx.Response) -> dict:
    """Validate an HTTP response and return the ``data`` block.

    Two failure modes to handle (per docs/api/overview.md §通用响应格式):

    1. **Transport failure** (HTTP non-2xx): the wrapper never has
       ``success=true`` so we surface it as :class:`MolizhishuError` with
       ``http_status`` populated.
    2. **Business failure** (HTTP 200 but ``success=false``): the wrapper
       rejects it without ``data``; we still raise so callers can react.

    Success returns ``body["data"]`` directly — callers don't have to
    re-read the envelope on every call.
    """
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code // 100 != 2:
        raise MolizhishuError(
            body.get("code"),
            body.get("message", "http error"),
            response.status_code,
            body,
        )
    if body.get("success") is not True or body.get("code") != 200:
        raise MolizhishuError(
            body.get("code"),
            body.get("message", "business error"),
            response.status_code,
            body,
        )
    return body["data"]


class MolizhishuClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    async def submit_task(self, payload: dict) -> dict:
        url = f"{self.base_url}/task/batch/shared"
        headers = {**self._auth_headers(), "Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload, headers=headers)
        return _unwrap(response)

    def submit_task_sync(
        self,
        payload: dict,
        *,
        brand: str | None = None,
        aliases: Iterable[str] | None = None,
    ) -> dict:
        """Sync wrapper that mirrors ``LLMClient.submit_task_sync``.

        The remote molizhishu API has no concept of brand / aliases — the
        prompt itself carries them — so we accept the kwargs for interface
        parity with :class:`LLMClient` and quietly ignore them.
        """
        return asyncio.run(self.submit_task(payload))

    async def get_task_status(self, task_id: str) -> dict:
        """``GET /task/status/{taskId}`` — main task + per-sub-task status.

        Returns the ``data`` block: ``taskId`` + ``status`` + total /
        completed / failed counts + a ``subTaskList`` with status-only fields
        (no ``answerContent``). Used by the polling sync to advance a row
        from ``processing`` toward ``completed`` / ``partial_completed``.
        """
        url = f"{self.base_url}/task/status/{task_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=self._auth_headers())
        return _unwrap(response)

    async def get_task_result(self, task_id: str) -> dict:
        """``GET /task/result/{taskId}`` — full subTaskList with ``answerContent``.

        Same shape as :meth:`get_task_status` but every ``subTaskList``
        item carries the heavy fields (``answerContent`` /
        ``referenceList`` / ``citationList`` / ``reasoningProcess`` /
        ``recommendedQuestions`` / ``mediaContent`` / ``pageScreenshot`` /
        ``errorMessage`` / ``proxyIp`` / ``time`). The polling sync calls
        this only after a terminal status has been observed so we don't
        pay the bandwidth cost on every tick.
        """
        url = f"{self.base_url}/task/result/{task_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=self._auth_headers())
        return _unwrap(response)

    # ---- sync wrappers for the APScheduler sync loop ----
    # ``sync_pending_tasks`` runs on the APScheduler default executor
    # (a sync thread), so it can't ``await`` directly. These wrappers
    # mirror :meth:`submit_task_sync` — minimal surface, no logging here
    # because the sync loop already knows ``source`` and writes its own
    # structured lines per docs/api/errors.md §日志建议.

    def get_task_status_sync(self, task_id: str) -> dict:
        """Sync wrapper around :meth:`get_task_status`."""
        return asyncio.run(self.get_task_status(task_id))

    def get_task_result_sync(self, task_id: str) -> dict:
        """Sync wrapper around :meth:`get_task_result`."""
        return asyncio.run(self.get_task_result(task_id))