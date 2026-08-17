"""Smoke test for llm_tools.web_search / web_fetch.

Run with:
    cd backend && .venv/bin/python -m tests._smoke_llm_tools

Exits non-zero if either tool errors out. Output is truncated so the
log stays readable.
"""
from __future__ import annotations

import sys
from textwrap import shorten

from app.services.llm_tools import (
    ALL_TOOL_SPECS,
    ToolDispatcher,
    WEB_FETCH_SPEC,
    WEB_SEARCH_SPEC,
    web_fetch,
    web_search,
)


def _hr(title: str) -> None:
    print()
    print("=" * 12, title, "=" * 12)


def main() -> int:
    failures: list[str] = []

    # ------------------------------------------------------------------
    # 1. Tool schemas
    # ------------------------------------------------------------------
    _hr("tool specs")
    print("registered tools:", [s.name for s in ALL_TOOL_SPECS])
    print("dispatcher payload keys:", list(ToolDispatcher.tool_specs()[0].keys()))
    print("WEB_SEARCH_SPEC.required:", WEB_SEARCH_SPEC.input_schema["required"])
    print("WEB_FETCH_SPEC.required:", WEB_FETCH_SPEC.input_schema["required"])

    # ------------------------------------------------------------------
    # 2. web_search
    # ------------------------------------------------------------------
    _hr("web_search: Python programming language")
    try:
        out = web_search("Python programming language", top_k=3)
        print(shorten(out, width=600, placeholder="…"))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"web_search(query) raised: {exc!r}")
        print("FAILED:", exc)

    _hr("web_search: Chinese query (糖尿病 监测仪)")
    try:
        out = web_search("糖尿病 监测仪", top_k=3)
        print(shorten(out, width=600, placeholder="…"))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"web_search(zh) raised: {exc!r}")
        print("FAILED:", exc)

    _hr("web_search: with top_k=1 (verify limit respected)")
    try:
        out = web_search("Python programming language", top_k=1)
        lines = [l for l in out.splitlines() if l.startswith(("1.", "2.", "3."))]
        if len(lines) != 1:
            failures.append(f"top_k=1 returned {len(lines)} numbered lines")
        print("numbered lines:", len(lines))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"web_search(top_k=1) raised: {exc!r}")

    _hr("web_search: empty query (should error gracefully)")
    err_text = ToolDispatcher().dispatch("web_search", {"query": ""})
    print("dispatcher response:", err_text)
    if "tool error" not in err_text:
        failures.append("web_search('') did not return a tool-error envelope")

    _hr("web_search: unknown tool (dispatcher fallback)")
    err_text = ToolDispatcher().dispatch("nuke_internet", {})
    print("dispatcher response:", err_text)
    if "未知工具" not in err_text:
        failures.append("unknown tool did not return Chinese 未知工具 message")

    # ------------------------------------------------------------------
    # 3. web_fetch
    # ------------------------------------------------------------------
    _hr("web_fetch: example.com (small static page)")
    try:
        out = web_fetch("https://example.com/", max_chars=1000)
        print(shorten(out, width=600, placeholder="…"))
    except Exception as exc:  # noqa: BLE001
        failures.append(f"web_fetch(example.com) raised: {exc!r}")
        print("FAILED:", exc)

    _hr("web_fetch: bad scheme")
    err_text = ToolDispatcher().dispatch("web_fetch", {"url": "ftp://example.com"})
    print("dispatcher response:", err_text)
    if "tool error" not in err_text:
        failures.append("web_fetch(bad scheme) did not return a tool-error envelope")

    _hr("web_fetch: nonexistent host")
    err_text = ToolDispatcher().dispatch(
        "web_fetch", {"url": "https://this-host-should-not-exist.invalid/"}
    )
    print("dispatcher response:", shorten(err_text, width=200))

    _hr("web_fetch: max_chars clamping")
    try:
        out = web_fetch("https://example.com/", max_chars=200)
        print("len(out):", len(out), "preview:", out[:120])
    except Exception as exc:  # noqa: BLE001
        failures.append(f"web_fetch(max_chars=200) raised: {exc!r}")

    _hr("web_fetch: dispatcher max_chars clamping against ceiling")
    # Ask for 10MB; the dispatcher should clamp to the configured ceiling.
    big_request = ToolDispatcher(fetch_max_bytes=4000).dispatch(
        "web_fetch", {"url": "https://example.com/", "max_chars": 10_000_000}
    )
    print("len:", len(big_request), "(should be < 4000/4 = 1000 + truncation marker)")
    if len(big_request) > 1100:
        failures.append("dispatcher did not clamp max_chars to ceiling")

    # ------------------------------------------------------------------
    # 4. Result
    # ------------------------------------------------------------------
    _hr("summary")
    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("all smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())