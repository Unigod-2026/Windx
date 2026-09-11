"""Anthropic-compatible LLM backend that simulates the molizhishu remote.

The system supports two LLM modes selected by ``Settings.llm_mode``:

- ``molizhishu`` — call the real remote API through
  :class:`app.services.molizhishu_client.MolizhishuClient`. The remote
  is slow (5–60 minutes per batch) and owns the real ``answerContent``
  / ``referenceList`` / ``citationList`` data.
- ``llm`` — route the batch through this class, which talks to the
  configured Anthropic-compatible endpoint (default: minimax) with the
  ``web_search`` / ``web_fetch`` / ``submit_answer`` tools. The LLM
  finishes in seconds, and ``submit_answer`` forces the model to emit
  the same referenceList / citationList shape the remote would, so
  downstream storage code is identical between the two modes.

This class is only used for ``llm`` mode. The dispatch happens in
``app.services.scheduler.run_project`` which picks the right client
based on ``Settings.llm_mode``.

Public methods:

- :meth:`submit_task` — the molizhishu-shaped batch submit the
  scheduler calls.
- :meth:`polish_question` — used by the project-edit UI "润色问题"
  button.
- :meth:`extract_keywords` — used by the keyword-generator UI.
- :meth:`ask` — low-level escape hatch for ad-hoc callers (and the
  one the three above are built on top of).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import secrets
import time
import uuid
from datetime import datetime
from typing import Any, Iterable

from anthropic import AsyncAnthropic

from app.services.llm_prompts import (
    PROMPT_EXTRACT_KEYWORDS,
    PROMPT_JUDGE_CORRECTNESS,
    PROMPT_MONITOR_DEFAULT,
    PROMPT_POLISH_QUESTION,
    render_monitor_prompt,
    render_platform_prompt,
)
from app.services.llm_tools import ToolDispatcher, tool_result_block


logger = logging.getLogger("app.llm")


class LLMError(Exception):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _parse_correctness_verdict(raw: str) -> tuple[bool | None, str | None]:
    """Extract ``(is_correct, reason)`` from the LLM's free-text reply.

    The prompt insists on strict JSON ``{"is_correct": bool, "reason": str}``,
    but real model output occasionally wraps it in a ```json fence or adds
    a trailing sentence. We try:

    1. ``json.loads`` on the whole reply.
    2. ``json.loads`` on the substring between the first ``{`` and the
       last ``}`` (drops a leading ``Here is the JSON: `` prefix or a
       trailing ``Let me know if...`` sentence).
    3. Bareword fallback: look for ``"true"`` / ``"false"`` token after
       the ``is_correct`` key — last resort, so we still count a chatty
       reply that omitted the JSON braces.

    Returns ``(None, None)`` if all three attempts fail.
    """
    import json

    text = (raw or "").strip()
    if not text:
        return (None, None)

    # Drop ```json ... ``` fences if the model wrapped its reply.
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    for candidate in (text, _slice_first_json_object(text)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            verdict = obj.get("is_correct")
            reason = obj.get("reason")
            if isinstance(verdict, bool):
                if not isinstance(reason, str):
                    reason = None
                return (verdict, reason)
            if isinstance(verdict, str) and verdict.lower() in ("true", "false"):
                return (verdict.lower() == "true", reason if isinstance(reason, str) else None)

    return _bareword_verdict(text)


def _slice_first_json_object(text: str) -> str:
    """Return the substring from the first ``{`` to the matching last ``}``.

    Handles single-level nesting (sufficient for our one-key payload).
    Returns ``""`` if no balanced pair is found.
    """
    start = text.find("{")
    if start < 0:
        return ""
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return ""


def _bareword_verdict(text: str) -> tuple[bool | None, str | None]:
    """Last-resort substring scan for ``"is_correct": true|false``."""
    lowered = text.lower()
    marker = "is_correct"
    idx = lowered.find(marker)
    if idx < 0:
        return (None, None)
    tail = lowered[idx + len(marker): idx + len(marker) + 40]
    if "true" in tail and "false" not in tail:
        return (True, None)
    if "false" in tail:
        return (False, None)
    return (None, None)


def _new_subtask_id() -> str:
    return uuid.uuid4().hex


def _now_task_id() -> str:
    return "llm-" + datetime.now().strftime("%Y%m%d%H%M%S") + "-" + secrets.token_hex(4)


def _content_fingerprint(prompt: str, answer: str) -> str:
    return hashlib.sha256((prompt + "\x00" + answer).encode("utf-8")).hexdigest()


def _normalise_text(text: str | None) -> str:
    if not text:
        return ""
    return "".join(text).strip()


# --------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------


class LLMClient:
    """Anthropic-compatible LLM client used for ``LLM_MODE=llm``.

    Routes every prompt through the configured Anthropic-compatible
    endpoint (default: minimax) with the ``web_search`` / ``web_fetch``
    / ``submit_answer`` tools, and emits a molizhishu-shaped envelope so
    the rest of the system can keep consuming the same contract as
    :class:`MolizhishuClient`.

    For ``LLM_MODE=molizhishu`` the scheduler reaches for
    :class:`MolizhishuClient` directly; this class is unused for that
    mode.
    """

    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str = "",
        model: str = "MiniMax-M3",
        timeout: int = 120,
        max_tool_rounds: int = 10,
        web_fetch_max_bytes: int = 200_000,
        max_concurrency: int = 8,
    ):
        if not api_key:
            raise LLMError("LLM_API_KEY is not configured")
        self.base_url = base_url.rstrip("/") if base_url else ""
        self.model = model
        self.timeout = timeout
        self.max_tool_rounds = max_tool_rounds
        self.max_concurrency = max(1, max_concurrency)
        self._dispatcher = ToolDispatcher(fetch_max_bytes=web_fetch_max_bytes)
        self._client = AsyncAnthropic(
            base_url=self.base_url,
            api_key=api_key,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Core call (one round + tool loop)
    # ------------------------------------------------------------------

    async def _messages_create(
        self,
        *,
        system: str,
        user_prompt: str,
        tools: list[dict[str, Any]] | None,
        max_tokens: int,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
        """Call Anthropic with an optional tool loop.

        Two phases:

        1. **Research** — the model is free to use ``web_search`` /
           ``web_fetch`` / ``submit_answer`` for up to
           ``max_tool_rounds`` rounds. We honour ``submit_answer``
           immediately when it appears so we never spend rounds we
           don't need to.
        2. **Wrap-up** — if phase 1 ends without ``submit_answer``
           (model talked its way to a stop, hit the round cap, or
           never picked up the tool), we run one more round with
           *only* ``submit_answer`` available and a user nudge that
           says "call it now". The system prompt requires
           ``submit_answer`` to be called; this phase enforces that
           contract instead of silently accepting whatever bare text
           the model said (which is how we used to get rows like
           "让我尝试直接抓取 OpenRouter 排行榜的详细数据页面。").

        Returns ``(final_text, transcript, structured)``. ``structured``
        is the input dict from the ``submit_answer`` tool call when
        one was emitted (otherwise ``None``); it carries ``answer``,
        ``referenceList`` and ``citationList`` per the tool schema.
        """
        assert self._client is not None  # only invoked in real mode
        submit_tool = next(
            (t for t in (tools or []) if t.get("name") == "submit_answer"),
            None,
        )
        messages: list[dict[str, Any]] = [{"role": "user", "content": user_prompt}]
        transcript: list[dict[str, Any]] = []
        text = ""

        # ---- Phase 1: research loop ----
        for _round in range(self.max_tool_rounds):
            kwargs: dict[str, Any] = dict(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
            )
            if tools:
                kwargs["tools"] = tools
            resp = await self._client.messages.create(**kwargs)

            content = [b.model_dump() if hasattr(b, "model_dump") else b for b in resp.content]
            tool_uses = [b for b in content if b.get("type") == "tool_use"]
            text_blocks = [b.get("text", "") for b in content if b.get("type") == "text"]
            text = _normalise_text(text_blocks)

            # Fast exit on submit_answer.
            submit_call = next(
                (tu for tu in tool_uses if tu.get("name") == "submit_answer"),
                None,
            )
            if submit_call is not None:
                structured = submit_call.get("input") or {}
                final_text = str(structured.get("answer") or text)
                transcript.append({"name": "submit_answer", "input": structured})
                return final_text, transcript, structured

            if not tool_uses:
                # Model finished without submit_answer; append the
                # assistant turn so phase 2 has the context, then
                # break into the wrap-up phase.
                messages.append({"role": "assistant", "content": content})
                break

            messages.append({"role": "assistant", "content": content})
            tool_results: list[dict[str, Any]] = []
            for tu in tool_uses:
                name = tu.get("name") or ""
                input_data = tu.get("input") or {}
                tool_id = tu.get("id") or ""
                transcript.append({"name": name, "input": input_data})
                result_text = self._dispatcher.dispatch(name, input_data)
                tool_results.append(tool_result_block(tool_id, result_text))
            messages.append({"role": "user", "content": tool_results})

        # ---- Phase 2: force submit_answer ----
        if submit_tool:
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "研究阶段已结束。请立即调用 submit_answer 工具"
                                "提交最终答案：answer 用 Markdown 正文,referenceList"
                                " / citationList 按你掌握的引用整理(没有可传空数组)。"
                                "submit_answer 必须被调用,不要只输出文本。"
                            ),
                        }
                    ],
                }
            )
            try:
                resp = await self._client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=messages,
                    tools=[submit_tool],
                )
                content = [
                    b.model_dump() if hasattr(b, "model_dump") else b for b in resp.content
                ]
                tool_uses = [b for b in content if b.get("type") == "tool_use"]
                text_blocks = [b.get("text", "") for b in content if b.get("type") == "text"]
                text = _normalise_text(text_blocks)
                submit_call = next(
                    (tu for tu in tool_uses if tu.get("name") == "submit_answer"),
                    None,
                )
                if submit_call is not None:
                    structured = submit_call.get("input") or {}
                    final_text = str(structured.get("answer") or text)
                    transcript.append({"name": "submit_answer", "input": structured})
                    return final_text, transcript, structured
            except Exception as exc:  # noqa: BLE001 - last-chance wrap
                # Fall through to the text-only fallback below.
                transcript.append({"name": "submit_answer_forced_error", "input": {"error": str(exc)}})

        return text, transcript, None

    async def ask(
        self,
        *,
        system: str,
        user_prompt: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 1024,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
        """One user prompt, optional tool access, return ``(text, transcript, structured)``.

        Editor helpers (:meth:`polish_question`, :meth:`extract_keywords`)
        build on this with their own prompts / tool off-switch, and the
        ``submit_task`` path captures ``structured`` to populate
        ``referenceList`` / ``citationList`` on the sub_task row.
        """
        try:
            return await self._messages_create(
                system=system,
                user_prompt=user_prompt,
                tools=tools,
                max_tokens=max_tokens,
            )
        except Exception as exc:  # noqa: BLE001 - SDK raises a wide tree
            raise LLMError(f"llm call failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API: monitor submit (molizhishu-shaped)
    # ------------------------------------------------------------------

    async def submit_task(
        self,
        payload: dict,
        *,
        brand: str | None = None,
        aliases: Iterable[str] | None = None,
    ) -> dict:
        """Run every (prompt, platform) pair in parallel and return the
        molizhishu-shaped envelope the scheduler already destructures.

        ``payload`` keys we read: ``prompts`` (list[str]) and
        ``platforms`` (list[dict] with at least ``platform`` /
        ``mode``). Each (prompt, platform) pair is rendered with the
        platform-impersonation prompt (so the same underlying model
        produces stylistically distinct answers per row), then sent
        through :meth:`ask` so :meth:`_messages_create` can run its
        research + forced-submit loop.

        All calls are dispatched concurrently through
        :func:`asyncio.gather` with a ``Semaphore`` of
        ``self.max_concurrency`` so a large N×M batch can't melt the
        upstream LLM endpoint's rate limit. Wall-clock latency is
        effectively ``max(call_latency)`` instead of
        ``sum(call_latency)`` — for N prompts × M platforms at
        30s/call each, the old code took ``N*M*30s``; this version
        takes ``30s`` (modulo the concurrency cap).

        ``brand`` / ``aliases`` come from the project's monitor
        config so the rendered prompt can name the brand and its
        aliases for better recall.
        """
        prompts: list[str] = list(payload.get("prompts") or [])
        if not prompts:
            raise LLMError("payload is missing 'prompts'")
        platforms: list[dict] = list(payload.get("platforms") or [])
        # Fall back to a single synthetic platform row when the caller
        # forgot to send any — keeps the contract "at least one
        # subtask per prompt" rather than emitting zero rows.
        if not platforms:
            platforms = [{"platform": None, "mode": None}]

        brand = brand or ""
        alias_list = list(aliases or [])

        sem = asyncio.Semaphore(self.max_concurrency)

        async def call_one(prompt: str, plat: dict) -> dict:
            async with sem:
                rendered = render_platform_prompt(
                    prompt, plat, brand=brand, aliases=alias_list
                )
                time_ms = str(int(datetime.now().timestamp() * 1000))
                try:
                    answer, _transcript, structured = await self.ask(
                        system=PROMPT_MONITOR_DEFAULT,
                        user_prompt=rendered,
                        tools=self._dispatcher.tool_specs(),
                        max_tokens=2048,
                    )
                    if structured:
                        reference_list = list(structured.get("referenceList") or [])
                        citation_list = list(structured.get("citationList") or [])
                        # Prefer the model's structured answer over any
                        # bare text it emitted alongside the tool call.
                        answer = str(structured.get("answer") or answer)
                        return {
                            "subTaskId": _new_subtask_id(),
                            "platform": plat.get("platform"),
                            "mode": plat.get("mode"),
                            "prompt": prompt,
                            "status": "completed",
                            "answerContent": answer,
                            "referenceList": reference_list,
                            "citationList": citation_list,
                            "errorMessage": None,
                            "time": time_ms,
                        }
                    # Phase 2 already nudged, model still didn't call
                    # submit_answer — keep the text but mark the row
                    # failed so the UI can flag it instead of silently
                    # showing a half-formed answer.
                    return {
                        "subTaskId": _new_subtask_id(),
                        "platform": plat.get("platform"),
                        "mode": plat.get("mode"),
                        "prompt": prompt,
                        "status": "failed",
                        "answerContent": answer or "",
                        "referenceList": [],
                        "citationList": [],
                        "errorMessage": "model did not call submit_answer",
                        "time": time_ms,
                    }
                except LLMError as exc:
                    return {
                        "subTaskId": _new_subtask_id(),
                        "platform": plat.get("platform"),
                        "mode": plat.get("mode"),
                        "prompt": prompt,
                        "status": "failed",
                        "answerContent": "",
                        "referenceList": [],
                        "citationList": [],
                        "errorMessage": exc.message,
                        "time": time_ms,
                    }

        work_items = [(p, plat) for p in prompts for plat in platforms]
        sub_tasks = await asyncio.gather(*(call_one(p, plat) for p, plat in work_items))

        statuses = {st["status"] for st in sub_tasks}
        if statuses == {"completed"}:
            task_status = "completed"
        elif statuses == {"failed"}:
            task_status = "failed"
        else:
            task_status = "partial_completed"

        return {
            "taskId": _now_task_id(),
            "status": task_status,
            "totalTask": len(sub_tasks),
            "subTaskList": list(sub_tasks),
        }

    def submit_task_sync(
        self,
        payload: dict,
        *,
        brand: str | None = None,
        aliases: Iterable[str] | None = None,
    ) -> dict:
        """Sync wrapper used by ``run_project`` (mirrors ``MolizhishuClient``)."""
        return asyncio.run(
            self.submit_task(payload, brand=brand, aliases=aliases)
        )

    # ------------------------------------------------------------------
    # Public API: editor helpers (no tools)
    # ------------------------------------------------------------------

    async def polish_question(self, raw: str) -> str:
        """Rewrite a draft question into a search-ready query.

        Called from the project-edit UI's "润色问题" button. Returns
        the polished question verbatim — callers shouldn't try to parse
        a list / structure out of the answer.
        """
        raw = (raw or "").strip()
        if not raw:
            return raw
        answer, _ = await self.ask(
            system=PROMPT_POLISH_QUESTION,
            user_prompt=raw,
            tools=None,
            max_tokens=512,
        )
        return answer.strip() or raw

    async def extract_keywords(self, text: str) -> list[str]:
        """Extract search keywords from ``text`` (one per line in the model
        output). Returns an empty list when the model can't help."""
        text = (text or "").strip()
        if not text:
            return []
        answer, _ = await self.ask(
            system=PROMPT_EXTRACT_KEYWORDS,
            user_prompt=text,
            tools=None,
            max_tokens=512,
        )
        cleaned: list[str] = []
        for line in answer.splitlines():
            line = line.strip().lstrip("-•·").strip()
            # Strip numeric prefix "1. xxx" / "1) xxx" the model emits.
            if len(line) > 3 and line[0].isdigit() and line[1] in {".", ")"}:
                line = line[2:].strip()
            if line:
                cleaned.append(line)
        return cleaned

    # ------------------------------------------------------------------
    # Public API: correctness judge (extraction pipeline)
    # ------------------------------------------------------------------

    async def judge_brand_correctness(
        self,
        *,
        selling_points: list[str],
        brand: str,
        answer: str,
    ) -> tuple[bool | None, str | None]:
        """Ask the LLM whether ``answer`` agrees with the brand's selling points.

        Returns ``(is_correct, reason)``:
        - ``(True, "...")``   judge says answer is consistent
        - ``(False, "...")``  judge says answer contradicts selling points
        - ``(None, "<error>")`` on any failure (network / JSON parse / empty
          response); the extraction pipeline maps this to
          ``geo_brand_mentions.is_correct = None``.

        The prompt (``PROMPT_JUDGE_CORRECTNESS``) instructs the model to
        return strict JSON ``{"is_correct": bool, "reason": str}`` — we
        parse defensively (strip code fences, fall back to substring
        match for ``true`` / ``false``) so a slightly chatty response
        still counts.
        """
        bullets = "\n".join(f"- {sp}" for sp in selling_points if sp and sp.strip())
        user_prompt = (
            f"【监控品牌】{brand}\n\n"
            f"【核心卖点】\n{bullets or '(空)'}\n\n"
            f"【LLM 回答正文】\n{(answer or '').strip() or '(空)'}"
        )
        try:
            raw_answer, _, _ = await self.ask(
                system=PROMPT_JUDGE_CORRECTNESS,
                user_prompt=user_prompt,
                tools=None,
                max_tokens=256,
            )
        except Exception as exc:  # noqa: BLE001 - propagate as None to caller
            return (None, f"llm call failed: {exc}")

        verdict, reason = _parse_correctness_verdict(raw_answer)
        if verdict is None:
            return (None, f"unparseable verdict: {raw_answer[:120]!r}")
        return (verdict, reason)

    def judge_brand_correctness_sync(
        self,
        *,
        selling_points: list[str],
        brand: str,
        answer: str,
    ) -> tuple[bool | None, str | None]:
        """Sync wrapper with retry: 5s, 10s. Returns ``(None, msg)`` on
        three failed attempts.

        Used by :mod:`app.services.extraction` — ``extract_brand_mentions``
        is sync so the LLM call has to be wrapped. Each subtask only fires
        one judge call (covers every self row at once), so the retry
        budget doesn't multiply per row.
        """
        delays = (5, 10)
        last: tuple[bool | None, str | None] = (None, "no attempt")
        for attempt in range(1 + len(delays) + 1):  # 1 first try + 2 retries
            try:
                last = asyncio.run(
                    self.judge_brand_correctness(
                        selling_points=selling_points,
                        brand=brand,
                        answer=answer,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - asyncio.run can re-raise
                last = (None, f"llm call raised: {exc}")
            verdict, reason = last
            if verdict is not None:
                return (verdict, reason)
            if attempt < 1 + len(delays):
                wait = delays[attempt - 1]
                logger.warning(
                    "judge_brand_correctness_sync attempt %d failed (%s), retry in %ds",
                    attempt + 1,
                    reason,
                    wait,
                )
                time.sleep(wait)
        return last


def build_client_from_settings() -> LLMClient:
    """Construct an :class:`LLMClient` from the current Settings.

    Called from FastAPI dependencies and from the scheduler so the
    constructor argument list lives in one place.
    """
    from app.config import get_settings

    s = get_settings()
    return LLMClient(
        base_url=s.llm_base_url,
        api_key=s.llm_api_key,
        model=s.llm_model,
        timeout=s.llm_timeout_seconds,
        max_tool_rounds=s.llm_max_tool_rounds,
        web_fetch_max_bytes=s.llm_web_fetch_max_bytes,
        max_concurrency=s.llm_max_concurrency or 8,
    )