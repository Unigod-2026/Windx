"""Render a report into a self-contained HTML document.

Two entry points, in order of preference:

1. :func:`_render_admin_html_via_browser` — **the source of truth**.
   用 headless Chromium 打开 admin 路由 ``/reports/:id``,等 React 渲染完成,
   把所有 stylesheet 内联成 ``<style>`` 块后取 outerHTML。
   跟运营在 admin 里看到的一字不差,React 改了什么公网就看到什么,不再
   drift。public URL 直接 serve 这份 HTML 文件即可。

2. :func:`render_html` — **legacy**,纯 Python 模板,已严重过时。
   保留仅为了不让 imports 断;新的 publish / generate 路径都走 helper 1。

两个函数都返回 ``<html>...</html>`` 完整文档,可以直接写盘 + 公网 serve。
"""

from __future__ import annotations

import html
import os
from datetime import date
from typing import Any

from app.deps import create_access_token

# --------------------------------------------------------------------- #
# Style
# --------------------------------------------------------------------- #

_CSS = """
* { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
    "Source Han Sans SC", "Microsoft YaHei", sans-serif;
  margin: 40px auto;
  max-width: 980px;
  color: #1F1F1F;
  line-height: 1.6;
  padding: 0 24px;
  background: #FFFFFF;
}
h1 {
  font-size: 26px;
  font-weight: 600;
  margin: 0 0 4px 0;
  letter-spacing: 0.5px;
}
h2 {
  font-size: 18px;
  font-weight: 600;
  margin: 36px 0 14px 0;
  padding-bottom: 6px;
  border-bottom: 1px solid #E5E5E5;
}
h3 {
  font-size: 15px;
  font-weight: 600;
  margin: 18px 0 8px 0;
}
.meta { color: #666666; font-size: 12px; margin-bottom: 24px; }
.meta-sep { color: #BFBFBF; margin: 0 6px; }

.kpi-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.kpi {
  border: 1px solid #E5E5E5;
  border-radius: 4px;
  padding: 14px 16px;
  background: linear-gradient(135deg, #F0F5FF 0%, #FFFFFF 100%);
}
.kpi-label { color: #666666; font-size: 12px; margin-bottom: 4px; }
.kpi-value { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
.kpi-value.up   { color: #CF1322; }
.kpi-value.down { color: #3F8600; }
.kpi-value.flat { color: #8E8E86; }

.chart {
  width: 100%;
  height: 200px;
  border: 1px solid #E5E5E5;
  border-radius: 4px;
  background: #FFFFFF;
  margin-top: 8px;
}
.chart svg { width: 100%; height: 100%; display: block; }

table {
  border-collapse: collapse;
  width: 100%;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
th, td {
  border-bottom: 1px solid #E5E5E5;
  padding: 8px 10px;
  text-align: left;
  vertical-align: middle;
}
th {
  background: #FAFAFA;
  color: #374151;
  font-weight: 500;
}
td.num { text-align: right; }
td.mark-yes { color: #3F8600; font-weight: 600; text-align: center; }
td.mark-no  { color: #BFBFBF; text-align: center; }

.summary-list {
  list-style: none;
  padding: 0;
  margin: 0;
}
.summary-list li {
  border-bottom: 1px dashed #E5E5E5;
  padding: 8px 0;
  font-size: 13px;
}
.summary-list li:last-child { border-bottom: none; }

.empty-placeholder {
  border: 1px dashed #BFBFBF;
  border-radius: 4px;
  padding: 24px;
  text-align: center;
  color: #BFBFBF;
  font-size: 13px;
  margin: 8px 0;
}

footer {
  margin-top: 48px;
  padding-top: 16px;
  border-top: 1px dashed #E5E5E5;
  color: #BFBFBF;
  font-size: 11px;
  text-align: center;
}

@media print {
  body { margin: 16mm; max-width: none; }
  .kpi, table, .summary-list { break-inside: avoid; }
  h2 { break-after: avoid; }
}
"""


def _esc(s: Any) -> str:
    return html.escape(str(s), quote=True)


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _pct_or_none(rate) -> str:
    if rate is None:
        return "未配置"
    return f"{rate * 100:.2f}%"


def _pp_or_none(delta) -> str:
    if delta is None:
        return "—"
    v = delta * 100
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.1f}pp"


def _delta_class(delta) -> str:
    if delta is None:
        return "flat"
    if delta > 0.0005:
        return "up"
    if delta < -0.0005:
        return "down"
    return "flat"


def _label_for_platform(code: str) -> str:
    """Inline display label for a raw ``Subtask.platform`` value.

    Duplicated from ``app.services.platform_labels`` so the HTML
    renderer doesn't import from another service module. Keep in sync.
    """
    table = {
        "doubao": "豆包", "doubao_mobile": "豆包",
        "yuanbao": "元宝", "yuanbao_mobile": "元宝",
        "qianwen": "千问", "qianwen_mobile": "千问",
        "kimi": "Kimi",
        "deepseek": "DeepSeek", "deepseek_mobile": "DeepSeek",
        "baiduai": "文心", "baidu": "文心", "baidu_mobile": "文心",
        "antafu": "蚂蚁阿福",
        "chatgpt": "ChatGPT",
    }
    return table.get(code, code)


def _sparkline_svg(
    points: list[dict],
    *,
    width: int = 1024,
    height: int = 200,
    pad_x: int = 24,
    pad_y: int = 16,
) -> str:
    if not points:
        return '<div class="legend">无数据</div>'
    max_rate = max(0.001, max(p["rate"] for p in points))
    step_x = (width - pad_x * 2) / max(1, len(points) - 1)
    coords = []
    for i, p in enumerate(points):
        x = pad_x + i * step_x
        y = height - pad_y - (p["rate"] / max_rate) * (height - pad_y * 2)
        coords.append((x, y, p))
    line = " ".join(
        f"{('M' if i == 0 else 'L')} {x:.1f} {y:.1f}"
        for i, (x, y, _) in enumerate(coords)
    )
    circles = "".join(
        f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="#2E5BFF">'
        f"<title>{_esc(p['date'])} {_pct_or_none(p['rate'])}</title></circle>"
        for x, y, p in coords
    )
    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="none">'
        f'<path d="{line}" fill="none" stroke="#2E5BFF" stroke-width="2"/>'
        f"{circles}"
        f"</svg>"
    )


def _kpi(label: str, value: str, cls: str = "") -> str:
    val_cls = f' class="{cls}"' if cls else ""
    return (
        f'<div class="kpi">'
        f'<div class="kpi-label">{_esc(label)}</div>'
        f'<div class="kpi-value"{val_cls}>{_esc(value)}</div>'
        f"</div>"
    )


def _empty_section(title: str, message: str) -> str:
    return f"""<section>
  <h2>{_esc(title)}</h2>
  <div class="empty-placeholder">{_esc(message)}</div>
</section>"""


def _empty_block(message: str) -> str:
    return f'<div class="empty-placeholder">{_esc(message)}</div>'


def _platform_table(rows: list[dict]) -> str:
    sorted_rows = sorted(rows, key=lambda r: r.get("current_rate", 0), reverse=True)
    body = "".join(
        "<tr>"
        f"<td>{_esc(r.get('platform_label', r.get('platform_code', '')))}</td>"
        f'<td class="num">{_pct_or_none(r.get("current_rate"))} ({r.get("current_mentioned", 0)}/{r.get("current_total", 0)})</td>'
        f'<td class="num">{_pct_or_none(r.get("previous_rate"))} ({r.get("previous_mentioned", 0)}/{r.get("previous_total", 0)})</td>'
        f'<td class="num {_delta_class(r.get("delta_pp", 0))}">{_pp_or_none(r.get("delta_pp", 0))}</td>'
        "</tr>"
        for r in sorted_rows
    )
    return (
        "<table>"
        "<thead><tr><th>平台</th><th>本期</th><th>上期</th><th>周环比</th></tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
    )


def _truncate(s: str, n: int) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def _matrix_table(matrix: list[dict]) -> str:
    if not matrix:
        return _empty_block("暂无数数据")
    platforms: list[str] = []
    seen: set[str] = set()
    for row in matrix:
        for pc in row.get("per_platform", {}):
            if pc not in seen:
                platforms.append(pc)
                seen.add(pc)
    th_cells = "".join(f"<th>{_esc(_label_for_platform(pc))}</th>" for pc in platforms)
    thead = f"<thead><tr><th>问题</th>{th_cells}</tr></thead>"
    rows_html = ""
    for row in matrix:
        per = row.get("per_platform", {})
        cells = "".join(
            f'<td class="mark-{"yes" if per.get(pc) else "no"}">'
            f'{"✓" if per.get(pc) else "—"}</td>'
            for pc in platforms
        )
        rows_html += (
            f"<tr><td>{_esc(_truncate(row.get('prompt_text', ''), 32))}</td>{cells}</tr>"
        )
    return f"<table>{thead}<tbody>{rows_html}</tbody></table>"


def _changes_block(changes: dict) -> str:
    sections: list[tuple[str, list[dict]]] = [
        ("新增突破 (0 → ≥1)", changes.get("new_mentions") or []),
        ("上升 (覆盖平台数 +1)", changes.get("increased") or []),
        ("回落 (覆盖平台数 -1)", changes.get("decreased") or []),
        ("失守 (≥1 → 0)", changes.get("lost_mentions") or []),
    ]
    items: list[str] = []
    for title, rows in sections:
        if not rows:
            continue
        items.append(f"<li><strong>{_esc(title)}</strong>: {len(rows)} 个问题</li>")
    return (
        f'<ul class="summary-list">{"".join(items)}</ul>'
        if items
        else _empty_block("暂无数数据")
    )


# --------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------- #


def render_html(*, snapshot: dict, template_id: str) -> str:
    """Render a snapshot dict into a self-contained HTML document.

    Each chapter is its own ``<section>``. Missing snapshot fields
    (e.g. ``content_ops`` always-null this iteration) render as a
    placeholder block — the chapter heading is preserved so future
    data ingestion requires zero template work.
    """
    project_name = _esc(snapshot["project"]["name"])
    period = snapshot.get("period", {})
    baseline = snapshot.get("baseline") or {}
    title = _esc(snapshot.get("title", "GEO 周报"))
    generated_at = _esc(snapshot.get("generated_at", ""))
    generated_by = _esc(snapshot.get("generated_by", ""))
    page_t = page_title(snapshot.get("title", "GEO 周报"))

    sections_html = "\n".join(
        [
            _render_section_head_meta(snapshot),
            _render_section_one_overall(snapshot),
            _render_section_two_summary(snapshot),
            _render_section_three_breakdown(snapshot),
            _render_section_four_content_ops(snapshot),
            _render_section_five_weekly_changes(snapshot),
            _render_section_attribution(snapshot),
        ]
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{_esc(snapshot['project']['name'])} · {_esc(page_t)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>{project_name} · GEO 周报</h1>
<div class="meta">
  报告周期 {_esc(period.get('start', ''))} 至 {_esc(period.get('end', ''))}
  <span class="meta-sep">·</span>
  {_esc(generated_by)}
  <span class="meta-sep">·</span>
  生成时间 {generated_at}
  <span class="meta-sep">·</span>
  模板 {template_id}
</div>
{sections_html}
<footer>
  报告由风球科技 GEO 监控平台生成
  ｜ 口径:成功提及品牌数 ÷ (平台 × 问题) 总数
  ｜ 模板 {template_id}
</footer>
</body>
</html>
"""


def page_title(snapshot_title: str) -> str:
    """Strip the redundant ``<name> · GEO 周报 · `` prefix for the
    ``<title>`` element so the browser tab doesn't repeat the project
    name twice (the ``<title>`` is already prefixed with the project
    name by the page template).
    """
    if " · GEO 周报 · " in snapshot_title:
        return snapshot_title.split(" · GEO 周报 · ", 1)[1]
    return snapshot_title


def default_title(
    project_name: str, period_start: date, period_end: date
) -> str:
    return f"{project_name} · GEO 周报 · {period_start} ~ {period_end}"


# --------------------------------------------------------------------- #
# Chapter renderers
# --------------------------------------------------------------------- #


def _render_section_head_meta(snapshot: dict) -> str:
    baseline = snapshot.get("baseline") or {}
    parts: list[str] = []
    if baseline.get("date"):
        parts.append(
            f"基线 {_esc(baseline['date'])} {_pct_or_none(baseline.get('rate'))}"
        )
    if not parts:
        return ""
    sep_html = '<span class="meta-sep">·</span>'
    return (
        f'<div class="meta" style="margin-bottom: 16px;">'
        f"{sep_html.join(parts)}</div>"
    )


def _render_section_one_overall(snapshot: dict) -> str:
    daily = snapshot.get("daily_mention_rate") or []
    if not daily:
        return _empty_section("一、整体提及率走势", "暂无数数据")

    last = daily[-1]
    prev = daily[-2] if len(daily) >= 2 else None
    current = last.get("rate", 0)
    previous = (prev or {}).get("rate", 0)
    wow = current - previous
    baseline = (snapshot.get("baseline") or {}).get("rate")
    baseline_delta = (current - baseline) if baseline is not None else None

    sparkline = _sparkline_svg(daily)
    return f"""<section>
  <h2>一、整体提及率走势</h2>
  <div class="kpi-grid">
    {_kpi("当前周期提及率", _pct_or_none(current))}
    {_kpi("周环比", _pp_or_none(wow), _delta_class(wow))}
    {_kpi(
        f"基线 ({_esc((snapshot.get('baseline') or {}).get('date') or '-')})",
        _pct_or_none(baseline) if baseline is not None else "未配置基线",
        "flat",
    )}
  </div>
  <div class="chart">{sparkline}</div>
</section>"""


def _render_section_two_summary(snapshot: dict) -> str:
    """二、本周总结 — four operator-written blocks.

    Mirrors ``PublicSectionTwo`` in the SPA. Blocks the operator left
    empty are omitted; if all four are empty the section falls back to
    the placeholder.
    """
    block = snapshot.get("weekly_summary") or {}
    labels = [
        ("core_finding", "本周核心结论"),
        ("platform_dynamic", "平台动态"),
        ("content_result", "内容成效"),
        ("scene_coverage", "场景覆盖"),
    ]
    items = "".join(
        f"<li><strong>{_esc(label)}：</strong>{_esc(block.get(key))}</li>"
        for key, label in labels
        if block.get(key)
    )
    if not items:
        return _empty_section("二、本周总结", "暂无数数据")
    return f"""<section>
  <h2>二、本周总结</h2>
  <ul class="summary-list">{items}</ul>
</section>"""


def _render_section_three_breakdown(snapshot: dict) -> str:
    breakdown = snapshot.get("platform_breakdown") or []
    matrix = snapshot.get("prompt_platform_matrix") or []
    summary = snapshot.get("platform_summary") or []

    parts: list[str] = [
        "<section>",
        "<h2>三、分平台周环比变化与问题级提及率明细</h2>",
    ]

    parts.append("<h3>3.1 平台周环比</h3>")
    if not breakdown:
        parts.append(_empty_block("暂无数数据"))
    else:
        parts.append(_platform_table(breakdown))

    if summary:
        parts.append("<h3>3.2 平台简评</h3>")
        items = "".join(
            f"<li>{_esc(item.get('note', ''))}</li>" for item in summary
        )
        parts.append(f'<ul class="summary-list">{items}</ul>')

    if matrix:
        parts.append("<h3>3.3 问题×平台 矩阵</h3>")
        parts.append(_matrix_table(matrix))

    parts.append("</section>")
    return "\n".join(parts)


def _render_section_four_content_ops(snapshot: dict) -> str:
    ops = snapshot.get("content_ops")
    if not ops:
        return _empty_section("四、本周内容运营", "暂无数数据")
    summary_text = (
        ops.get("summary", "") if isinstance(ops, dict) else str(ops)
    )
    return f"""<section>
  <h2>四、本周内容运营</h2>
  <p>{_esc(summary_text)}</p>
</section>"""


def _render_section_five_weekly_changes(snapshot: dict) -> str:
    changes = snapshot.get("weekly_changes") or {}
    zero = snapshot.get("zero_mention_prompts") or []
    has_changes = any(
        (changes.get(k) or [])
        for k in ("new_mentions", "increased", "decreased", "lost_mentions")
    )
    has_zero = len(zero) > 0
    if not has_changes and not has_zero:
        return _empty_section("五、待突破问题与本周边际变化", "暂无数数据")

    parts: list[str] = [
        "<section>",
        "<h2>五、待突破问题与本周边际变化</h2>",
    ]
    if has_zero:
        items = "".join(
            f"<li>{_esc(p['prompt_text'])}</li>" for p in zero
        )
        parts.append(
            f"<h3>5.1 持续未提及问题</h3>"
            f'<ul class="summary-list">{items}</ul>'
        )
    if has_changes:
        parts.append("<h3>5.2 本周边际变化</h3>")
        parts.append(_changes_block(changes))
    parts.append("</section>")
    return "\n".join(parts)


def _render_section_attribution(snapshot: dict) -> str:
    text = snapshot.get("attribution")
    if not text:
        return _empty_section("5.3 核心归因", "暂无数数据")
    return f"""<section>
  <h2>5.3 核心归因</h2>
  <p style="white-space: pre-wrap;">{_esc(text)}</p>
</section>"""


# --------------------------------------------------------------------- #
# Headless browser rendering — single source of truth for public HTML
# --------------------------------------------------------------------- #


def _system_admin_jwt() -> str:
    """找一个 super_admin 账号签发一个长过期 JWT,供 headless browser 用。

    publish 在 backend 进程里跑,没有「用户登录」环节;headless browser
    拿这个 token 注入 localStorage,绕过 admin 路由的 RequireAuth。

    优先选 super_admin(customer_admin 跨过项目 tenant 校验);如果没有
    super_admin 就回落到第一个 active admin(任意账号都能访问任意项目)。
    """
    from app.db import SessionLocal
    from app.models.customer import AdminUser, AdminRole, AdminStatus
    with SessionLocal() as db:
        admin = (
            db.query(AdminUser)
            .filter(
                AdminUser.role == AdminRole.SUPER_ADMIN.value,
                AdminUser.status == AdminStatus.ACTIVE.value,
            )
            .first()
        )
        if admin is None:
            admin = (
                db.query(AdminUser)
                .filter(AdminUser.status == AdminStatus.ACTIVE.value)
                .first()
            )
        if admin is None:
            raise RuntimeError("no active admin user — cannot render report")
    return create_access_token(admin.id)


def _render_admin_html_via_browser(
    report_id: int,
    *,
    base_url: str | None = None,
) -> str:
    """用 headless Chromium 打开 admin 路由 ``/reports/:id``,等 React 渲染
    完成后取整页 outerHTML,把 stylesheet 内联成 ``<style>`` 块,返回可独立
    serve 的完整 HTML 文档。

    这是 publish / generate 路径的**唯一渲染源**。它跟 admin 编辑视图
    一字不差(因为就是同一个 React 组件树渲染出来的),React 改了什么公网
    就看到什么 —— 解决 Python 渲染层跟 React drift 的根本问题。

    性能:headless Chromium 启动 + 渲染大约 3-5s。publish 接受这个延迟。

    Args:
        report_id: ``geo_reports.id``。
        base_url: 前端 SPA 默认 / 部署 URL。开发默认 ``http://localhost:5173``,
            生产从环境变量 ``PUBLIC_FRONTEND_URL`` 取。

    Returns:
        ``<!doctype html>...</html>`` 完整字符串,含内联 CSS,
        写到 ``backend/data/reports/{project_id}/{report_id}.html`` 后
        任何环境(本地 / 静态托管)都能直接 serve。
    """
    from playwright.sync_api import sync_playwright

    base_url = (
        base_url
        or os.environ.get("PUBLIC_FRONTEND_URL")
        or "http://localhost:5173"
    )
    jwt = _system_admin_jwt()
    # ``mode=public`` 让 React 树以只读 + 无工具栏形态渲染。少了它,渲染发生在
    # ``is_published`` 提交之前,组件会认为这是草稿(canEdit=True),把「发布」
    # 按钮和一堆点了没反应的「编辑」链接一起烤进公网 HTML。
    target = f"{base_url.rstrip('/')}/reports/{report_id}?mode=public"

    # Chrome 可执行路径优先级:
    #   1. REPORT_RENDER_CHROME 环境变量(生产部署显式指定)
    #   2. /usr/bin/google-chrome 存在就用它(本机 Ubuntu 装了 system chrome)
    #   3. 都没有 → 交给 playwright 找它自带的 chromium
    # 部署时至少要满足 2 或 3 之一,否则 publish 会抛「Executable doesn't exist」。
    chrome_path = os.environ.get("REPORT_RENDER_CHROME") or None
    if chrome_path is None and os.path.exists("/usr/bin/google-chrome"):
        chrome_path = "/usr/bin/google-chrome"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            executable_path=chrome_path,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 1800}
            )
            ctx.add_init_script(
                f"window.localStorage.setItem('token', '{jwt}');"
            )
            page = ctx.new_page()
            page.goto(target, wait_until="networkidle", timeout=60000)

            # 等 React 真的把章节渲染出来 —— 「报告周期」元信息行是
            # AdminReportPreview 第一个稳定渲染的标志,等它出现即可。
            page.wait_for_selector(".report-preview-meta", timeout=30000)
            # 给 echarts sparkline 多一点时间完成 draw
            page.wait_for_timeout(800)

            html = page.evaluate(
                """() => {
                    let cssText = '';
                    for (const sheet of document.styleSheets) {
                        try {
                            for (const rule of sheet.cssRules || []) {
                                cssText += rule.cssText + '\\n';
                            }
                        } catch (e) { /* cross-origin sheet, skip */ }
                    }
                    document.querySelectorAll('link[rel="stylesheet"]').forEach(
                        (l) => l.remove()
                    );
                    const inline = document.createElement('style');
                    inline.setAttribute('data-ssr-injected', 'true');
                    inline.textContent = cssText;
                    document.head.appendChild(inline);
                    // 去掉 React 在 dev 模式注入的 hot-reload 脚本 + Vite client,
                    // 它们在静态 serve 时会 404 / 报错。
                    document.querySelectorAll('script[type="module"]').forEach((s) => {
                        const src = s.getAttribute('src') || '';
                        if (src.includes('/@vite') || src.includes('/@react-refresh')
                            || src.includes('/src/main.tsx')) {
                            s.remove();
                        }
                    });
                    return '<!doctype html>\\n' + document.documentElement.outerHTML;
                }"""
            )
            return html
        finally:
            browser.close()
