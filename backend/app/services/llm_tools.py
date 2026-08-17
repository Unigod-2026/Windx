"""Local tool implementations exposed to the LLM as ``web_search`` /
``web_fetch``.

The Anthropic-compatible endpoint we route through doesn't ship its own
web tool, so we declare both tools in ``tools=[...]`` on every
``messages.create`` call and dispatch ``tool_use`` blocks to the local
implementations below.

Why local rather than calling a remote tool service:

- The user already pays the LLM API quota; piggy-backing on a separate
  search SaaS would double the latency and add a vendor.
- The result formats we care about (raw HTML for ``web_fetch``,
  ranked titles + snippets for ``web_search``) are small enough that
  a plain ``httpx`` call is faster than any hosted alternative.
- Both tools are pure I/O so they're trivial to swap for a hosted
  implementation later — keep the schema stable, change the body.

Tool dispatch lives in :class:`ToolDispatcher`. :class:`LLMClient`
holds one of these and feeds the loop's ``tool_use`` blocks into
:meth:`ToolDispatcher.dispatch`.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

import httpx


class ToolError(Exception):
    """Raised by a tool when it can't fulfil the call. The dispatcher
    surfaces the message back to the LLM as a ``tool_result`` so the
    model can retry / adapt — never propagate to the outer loop."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class ToolSpec:
    """JSON-Schema-style description the Anthropic SDK consumes.

    Kept as a plain dataclass so the LLMClient builds the ``tools=[]``
    payload without pulling pydantic into the schema layer.
    """

    name: str
    description: str
    input_schema: dict[str, Any]


WEB_SEARCH_SPEC = ToolSpec(
    name="web_search",
    description=(
        "在公开互联网上检索给定查询，返回前若干条结果的标题、链接和"
        "摘要。适用于需要最新事实、行情、新闻等问题的场景。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "要检索的关键词或问题。",
            },
            "top_k": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "返回结果数量上限，默认 5。",
            },
        },
        "required": ["query"],
    },
)


WEB_FETCH_SPEC = ToolSpec(
    name="web_fetch",
    description=(
        "抓取指定 URL 的正文内容（HTML 已剥离为纯文本），用于在已知"
        "链接上获取详细资料。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要抓取的 URL（http / https）。",
            },
            "max_chars": {
                "type": "integer",
                "minimum": 200,
                "maximum": 100_000,
                "description": "返回正文最大字符数，默认 8000。",
            },
        },
        "required": ["url"],
    },
)


SUBMIT_ANSWER_SPEC = ToolSpec(
    name="submit_answer",
    description=(
        "【必须最后调用】提交最终的结构化答案。answer 是 Markdown 正文，"
        "referenceList 列出回答中引用的全部来源（每个引用一条，含 title、url、"
        "site），citationList 列出 answer 中实际标注的引用编号（带 index 字段）。"
        "任何回答都必须通过此工具提交，否则视为未完成。"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "answer": {
                "type": "string",
                "description": "最终回答的 Markdown 正文，必要时在文末用 [1] [2] 这种编号标注引用。",
            },
            "referenceList": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "site": {"type": "string"},
                        "icon": {
                            "type": "string",
                            "nullable": True,
                            "description": "站点图标 URL，可为空。",
                        },
                    },
                    "required": ["title", "url"],
                },
                "description": "回答引用的来源列表（每个独立来源 1 条）。",
            },
            "citationList": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "与 answer 中的 [index] 编号对应。",
                        },
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "site": {"type": "string"},
                    },
                    "required": ["index"],
                },
                "description": "answer 中实际出现的引用编号列表。",
            },
        },
        "required": ["answer", "referenceList", "citationList"],
    },
)


ALL_TOOL_SPECS: tuple[ToolSpec, ...] = (
    WEB_SEARCH_SPEC,
    WEB_FETCH_SPEC,
    SUBMIT_ANSWER_SPEC,
)


# --------------------------------------------------------------------------
# Implementations
# --------------------------------------------------------------------------


def web_search(query: str, *, top_k: int = 5, timeout: int = 15) -> str:
    """Search the web for ``query`` and return a Markdown bullet list.

    Implementation strategy: hit Bing's HTML search endpoint because it
    doesn't require an API key and the markup is plain enough to parse
    with a few regexes. Each result lives inside a
    ``<li class="b_algo">`` block with a nested ``<h2><a>`` title and
    ``<p>`` snippet.

    Why Bing over DuckDuckGo: in mainland network tests DuckDuckGo's
    HTML endpoint resolves but the connection never completes. Bing's
    ``cn.bing.com`` mirror is reachable from the same networks and
    serves the same document shape.

    If the upstream layout ever changes, the test suite should catch
    it via the snapshot fixture in ``tests/test_llm_tools.py``.
    """
    if not query.strip():
        raise ToolError("query 不能为空")

    url = "https://cn.bing.com/search"
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(
                url,
                params={"q": query, "setlang": "zh-Hans"},
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                },
            )
    except httpx.HTTPError as exc:
        raise ToolError(f"web_search 网络失败: {exc}") from exc

    if resp.status_code // 100 != 2:
        raise ToolError(f"web_search 返回 HTTP {resp.status_code}")

    # Bing result block: <li class="b_algo"> ... <h2><a href="...">title</a></h2>
    # ... <p class="b_lineclamp...">snippet</p> ... </li>
    blocks = re.findall(
        r'<li[^>]*class="b_algo"[^>]*>(.*?)</li>',
        resp.text,
        flags=re.S,
    )

    if not blocks:
        return f"未检索到与「{query}」相关的结果。"

    lines: list[str] = []
    for idx, block in enumerate(blocks[:top_k], start=1):
        # Title lives in the first <h2><a> pair; href lives in the same <a>.
        title_match = re.search(
            r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>\s*</h2>',
            block,
            flags=re.S,
        )
        if not title_match:
            # Try the slightly different shape (no <h2>, just <a>).
            title_match = re.search(
                r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                block,
                flags=re.S,
            )
        if not title_match:
            continue
        href = title_match.group(1)
        if not href.startswith(("http://", "https://")):
            continue
        title = _strip_tags(title_match.group(2))

        # Snippet is the first <p> with class containing "b_lineclamp" or
        # any <p> inside the block; prefer the class-bearing one.
        snip_match = re.search(
            r'<p[^>]*class="[^"]*b_(?:lineclamp|paractl)[^"]*"[^>]*>(.*?)</p>',
            block,
            flags=re.S,
        ) or re.search(r"<p[^>]*>(.*?)</p>", block, flags=re.S)
        snippet_text = _strip_tags(snip_match.group(1)) if snip_match else ""

        lines.append(f"{idx}. [{title}]({href})")
        if snippet_text:
            lines.append(f"   {snippet_text}")
    if not lines:
        return f"未检索到与「{query}」相关的结果。"
    return "\n".join(lines)


def web_fetch(url: str, *, max_chars: int = 8000, timeout: int = 20) -> str:
    """Fetch ``url`` and return its body as plain text, truncated.

    Strips ``<script>``/``<style>`` blocks first (they're never useful
    body content) and collapses consecutive whitespace so the LLM sees a
    single coherent block.
    """
    if not url.startswith(("http://", "https://")):
        raise ToolError("url 必须以 http:// 或 https:// 开头")

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "windx-llm-tools/1.0"},
            )
    except httpx.HTTPError as exc:
        raise ToolError(f"web_fetch 网络失败: {exc}") from exc

    if resp.status_code // 100 != 2:
        raise ToolError(f"web_fetch 返回 HTTP {resp.status_code}")

    text = resp.text
    # Strip script / style blocks entirely (their content is never
    # user-facing body).
    text = re.sub(r"<script\b[^>]*>.*?</script>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<style\b[^>]*>.*?</style>", " ", text, flags=re.S | re.I)
    # Drop every other tag but keep their text content.
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars] + "…（已截断）"
    return text


def _strip_tags(fragment: str) -> str:
    """Best-effort tag stripper for one result entry.

    The Bing snippet markup occasionally contains nested ``<b>`` /
    ``<span>``; the inline regex below matches the common shapes
    without pulling in BeautifulSoup just for this hot path.
    """
    no_tags = re.sub(r"<[^>]+>", "", fragment)
    return html.unescape(no_tags).strip()


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------


class ToolDispatcher:
    """Routes Anthropic ``tool_use`` blocks to the right local function.

    Anthropic SDK returns each tool call as a dict with at least
    ``{"type": "tool_use", "name": str, "input": dict}``; the dispatcher
    forwards ``input`` to the matching :data:`ALL_TOOL_SPECS` handler
    and wraps the result in the ``tool_result`` envelope the SDK
    expects on the next round.
    """

    def __init__(self, *, fetch_max_bytes: int = 200_000):
        self._fetch_max_bytes = fetch_max_bytes

    def dispatch(self, name: str, input_data: dict[str, Any]) -> str:
        """Run the named tool. Returns a string (rendered for the LLM).

        Errors are caught and re-formatted as plain text so the model
        sees the failure and can adapt, instead of the loop raising.
        """
        try:
            if name == "web_search":
                return web_search(
                    query=input_data["query"],
                    top_k=int(input_data.get("top_k") or 5),
                )
            if name == "web_fetch":
                # The per-call ``max_chars`` clamps to the configured
                # ceiling so a prompt asking for ``max_chars=10_000_000``
                # doesn't blow context.
                requested = int(input_data.get("max_chars") or 8000)
                ceiling_chars = self._fetch_max_bytes // 4  # ~chars/byte
                max_chars = max(200, min(requested, ceiling_chars))
                return web_fetch(url=input_data["url"], max_chars=max_chars)
            raise ToolError(f"未知工具: {name!r}")
        except ToolError as exc:
            return f"[tool error] {exc.message}"
        except (KeyError, ValueError, TypeError) as exc:
            return f"[tool error] 参数非法: {exc}"

    @staticmethod
    def tool_specs() -> list[dict[str, Any]]:
        """Render :data:`ALL_TOOL_SPECS` as the SDK's ``tools=`` payload."""
        return [
            {
                "name": spec.name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in ALL_TOOL_SPECS
        ]


def tool_result_block(tool_use_id: str, content: str) -> dict[str, Any]:
    """Build a ``tool_result`` content block for the next SDK round.

    Kept here (rather than inlined in the LLMClient loop) so the
    envelope shape is reviewable in one place.
    """
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": False,
    }


__all__ = [
    "ALL_TOOL_SPECS",
    "SUBMIT_ANSWER_SPEC",
    "ToolDispatcher",
    "ToolError",
    "ToolSpec",
    "WEB_FETCH_SPEC",
    "WEB_SEARCH_SPEC",
    "render_tool_specs",
    "tool_result_block",
]


def render_tool_specs() -> list[dict[str, Any]]:
    """Module-level shortcut for callers that don't want a dispatcher."""
    return ToolDispatcher.tool_specs()