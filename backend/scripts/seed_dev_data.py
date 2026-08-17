"""Dev-only seed: pump one month of mock data into project ``AI发展`` (id=3).

Run with::

    cd backend && uv run python -m scripts.seed_dev_data

What it does
------------
- Adds the 10 prompts (project 3 may already have the first two) and a
  small set of 核心词 (keywords) so the LLM extraction pass has them.
- Adds three synthetic competitors (通义千问 / 智谱清言 / 文心一言) so
  the Top1 率 ranking chart shows five-six bars instead of three.
- For each of the past 30 days, generates ONE batch ``Task`` with all
  10 prompts × all 3 platforms = 30 ``Subtask`` rows (~900 total).
- Writes a generated Markdown ``answer_content`` per subtask that
  mentions the monitored brand (``deepseek``) and 1-2 competitors with
  realistic frequency, plus a short reference list.
- Counts ``mention_count`` as a binary 1 (the production pipeline only
  creates a row when the brand appears at least once — see
  ``app/services/extraction.py`` for the rationale).
- Fills LLM-derived fields (``rank_position``, ``sentiment_score``,
  ``is_recommended``, ``concern_hits_json``) so the KPIs (Top1, Top3,
  较上一周期 delta) get realistic deltas instead of all PENDING.

Deterministic for the same ``--seed``; numbers stay stable run-to-run so
the dashboard chart shape is reproducible.
"""

from __future__ import annotations

import argparse
import random
import re
import secrets
import sys
from datetime import datetime, timedelta

from sqlalchemy import delete, select

from app.db import get_session_factory
from app.models.enums import (
    CompetitorStatus,
    DeliveryMode,
    ExtractStatus,
    PromptStatus,
)
from app.models.project import (
    BrandMention,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.models.task import Subtask, Task


PROJECT_ID = 3  # AI 发展
SELF_BRAND = "deepseek"
SELF_ALIASES = ["DEEPSEEK", "DeepSeek"]
DAYS = 30
DEFAULT_SEED = 20260814
SEED_MARKER_KEY = "__seed_dev_data__"


def _seed_marker_value() -> str:
    return "dev-seed-v2"


PROMPTS: list[dict] = [
    {"prompt": "现在调用最多的大模型是哪个", "category": "引流感"},
    {"prompt": "哪个大模型最好用", "category": "引流感"},
    {"prompt": "国产大模型哪个最强", "category": "引流感"},
    {"prompt": "中文大模型排行", "category": "引流感"},
    {"prompt": "写代码用什么大模型最合适", "category": "场景类"},
    {"prompt": "免费好用的AI大模型推荐", "category": "引流感"},
    {"prompt": "国内大模型对比", "category": "引流感"},
    {"prompt": "企业级大模型哪家强", "category": "场景类"},
    {"prompt": "大模型API性价比排行", "category": "场景类"},
    {"prompt": "开源大模型哪个最强", "category": "场景类"},
]

KEYWORDS: list[str] = [
    "智能水平",
    "价格",
    "速度",
    "上下文长度",
    "中文能力",
    "代码能力",
    "推理深度",
    "开源生态",
]

EXTRA_COMPETITORS: list[dict] = [
    {"name": "通义千问", "aliases": ["千问", "通义", "qwen"], "note": "阿里"},
    {"name": "智谱清言", "aliases": ["智谱", "GLM", "ChatGLM"], "note": "清华系"},
    {"name": "文心一言", "aliases": ["文心", "ERNIE", "百度文心"], "note": "百度"},
    {"name": "腾讯混元", "aliases": ["混元", "Tencent"], "note": "腾讯"},
]

# Platforms (project_id=3) the seed must mirror in ``geo_project_platforms``
# and use when generating per-platform subtasks. Order matches the
# project's ``ProjectPlatform.sort`` after seeding.
EXTRA_PLATFORMS: list[dict] = [
    {"platform": "qianwen", "note": "通义千问"},
    {"platform": "wenxinyiyan", "note": "百度文心"},
    {"platform": "hunyuan", "note": "腾讯混元"},
]


# --------------------------------------------------------------------------
# Answer templates — one per prompt category. Each template uses
# {title} / {lead} / {self} / {c1} / {c2} / {c3} placeholders that the
# seeder fills in per (prompt, platform) draw. Templates deliberately
# mention at least the self brand so the regex pass picks it up.
# --------------------------------------------------------------------------

ANSWER_TEMPLATES: list[str] = [
    # 0 — most common: full structure, mentions self + 4 competitors
    (
        "## {title}\n\n"
        "{lead}\n\n"
        "### 主流参考榜单\n\n"
        "目前业内最常引用的「权威口径」有几条线：**OpenRouter 周榜**"
        "(真实 API 调用量，按 token 计)、**LMArena / Chatbot Arena**"
        "(盲测投票)、**Artificial Analysis Intelligence Index**"
        "(综合能力指数)。这三份榜单共同指向 **{self}** 作为当下"
        "中文及代码场景下的第一梯队 [1][2]。\n\n"
        "### Top 候选\n\n"
        "1. **{self}** —— 代码、长文本与开源生态三个维度均处第一梯队"
        "，调用成本约为同梯队闭源模型的 1/10，2026 年周榜持续前三 [3]。\n"
        "2. **{c1}** —— 中文场景下体验稳定，企业级部署成熟。\n"
        "3. **{c2}** —— 价格略高，胜在响应速度快、长上下文。\n"
        "4. **{c3}** —— 政企客户里占比最高，金融、医疗两个行业稳坐前二。\n"
        "5. **{c4}** —— 长文本与多模态见长，工业级稳定性好。\n\n"
        "### 一句话结论\n\n"
        "如果今天就要选，**{self}** 是综合性价比最高的选择；"
        "在 2025 年底到 2026 年这段时间里，OpenRouter / LMArena / "
        "Artificial Analysis 三份榜单都在把 {self} 排到第一"
        "[1][2][3]。\n"
    ),
    # 1 — competitor-leaning, mentions self + 5 competitors
    (
        "## {title}\n\n"
        "{lead}\n\n"
        "不少同事最近也在问我同样的问题。先把结论放出来："
        "*没有「绝对最强」，只有「场景最合适」*。下面按场景给一份参考：\n\n"
        "- **代码 / 推理 / 长上下文**：**{self}**（开源 + 价格低 + "
        "技术报告完整），同时 **{c1}** 也长期位居 OpenRouter Top 5。\n"
        "- **企业级 SLA / 国产化合规**：**{c3}** 在政企客户里占比最高，"
        "**{c5}** 在金融、医疗两个行业稳坐前二。\n"
        "- **极速响应 / 短问答**：**{c2}** 与豆包系列在速度榜 "
        "通常领先 200-400 ms。\n"
        "- **长文本 / 多模态**：**{c4}** 的 256K 上下文是当前第一梯队 "
        "唯一打通视频 + 文档的方案。\n\n"
        "如果你只选一个，我会优先 **{self}** —— 综合维度最均衡，"
        "而且是少有的「中文 + 代码 + 开源」三项全能。\n"
    ),
    # 2 — opinionated, mentions self + 2 competitors
    (
        "## {title}\n\n"
        "{lead}\n\n"
        "直接说答案：**{self}**。\n\n"
        "理由有三：\n\n"
        "1. **价格**：每千 token 的 API 价格只有 **{c1}** 同档的 1/8"
        "，对调用量大的场景非常友好。\n"
        "2. **能力**：在 HumanEval、GPQA、SWE-bench 三项上 "
        "{self} 都位列开源 SOTA。\n"
        "3. **生态**：MIT 协议、可自部署，社区里 LoRA / 微调 / "
        "蒸馏方案齐全。\n\n"
        "如果你的场景侧重中文写作、企业知识库，**{c1}** 与 **{c3}** 也是"
        "不错选择；但综合下来 2026 年我会把 **{self}** 排在"
        "第一位 [1]。\n"
    ),
    # 3 — broad survey table, mentions all 6 brands
    (
        "## {title}\n\n"
        "{lead}\n\n"
        "把 2026 年 7-8 月的几份横向榜单对比下来，第一梯队基本定型为：\n\n"
        "| 排名 | 模型 | 强项 | 适合场景 |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | **{self}** | 开源 / 代码 / 价格 | 通用 + 工程 |\n"
        "| 2 | **{c1}** | 中文写作 / 企业 | 内容生产 |\n"
        "| 3 | **{c2}** | 响应速度 / 长文本 | 实时问答 |\n"
        "| 4 | **{c3}** | 中文场景 / 企业 SLA | 政企合规 |\n"
        "| 5 | **{c4}** | 长上下文 / 多模态 | 视频 + 文档 |\n"
        "| 6 | **{c5}** | GLM 系列 / 学术 | 学术研究 |\n\n"
        "**一句话**：想省钱 + 写代码 + 中文都想要，**{self}** "
        "目前看是 2026 年性价比最高的方案 [1][2]。\n"
    ),
    # 4 — focused, mentions self only
    (
        "## {title}\n\n"
        "{lead}\n\n"
        "如果只挑一个，2026 年的答案是 **{self}**。\n\n"
        "理由：\n\n"
        "- API 价格只有头部闭源模型的 1/10；\n"
        "- 中文能力第一梯队，代码能力开源 SOTA；\n"
        "- MIT 协议支持自部署与商用；\n"
        "- 2026 年 OpenRouter 周榜持续前三。\n\n"
        "综上，**{self}** 在绝大多数场景下都是「最稳妥的第一个"
        "选择」。\n"
    ),
]

LEADS = [
    "这个问题最近被反复问到，先把参考答案放出来，再讲理据。",
    "「哪个大模型最好用」其实并不存在一个统一答案，但有参考答案。",
    "我们综合 OpenRouter、LMArena、Artificial Analysis 三份榜单整理。",
    "先说结论，再展开 2026 年的几个判断维度。",
    "在 2026 年这个时点上，主流答案已经基本收敛。",
]

TITLES = [
    "现在调用最多的大模型是哪个",
    "哪个大模型最好用？一份 2026 年选型参考",
    "2026 年国产大模型排行：综合能力 × 价格 × 速度",
    "中文大模型榜单：哪个最值得选",
    "写代码用什么大模型最合适",
    "免费好用的 AI 大模型推荐",
    "国内大模型横向对比",
    "企业级大模型哪家强",
    "大模型 API 性价比排行",
    "开源大模型哪个最强",
]

REFERENCES = [
    {
        "url": "https://openrouter.ai/rankings",
        "site": "openrouter.ai",
        "title": "OpenRouter LLM Rankings — Top Models Weekly",
    },
    {
        "url": "https://lmarena.ai/leaderboard",
        "site": "lmarena.ai",
        "title": "LMArena（Chatbot Arena）官方排行榜",
    },
    {
        "url": "https://artificialanalysis.ai/leaderboards/models",
        "site": "artificialanalysis.ai",
        "title": "Artificial Analysis LLM Leaderboard",
    },
    {
        "url": "https://www.deepseek.com/",
        "site": "deepseek.com",
        "title": "DeepSeek | 深度求索 官方网站",
    },
    {
        "url": "https://platform.deepseek.com/",
        "site": "platform.deepseek.com",
        "title": "DeepSeek Platform — API 定价",
    },
    {
        "url": "https://qwen.ai/",
        "site": "qwen.ai",
        "title": "通义千问 Qwen 官方网站",
    },
    {
        "url": "https://www.toolcenter.ai/zh/llm-leaderboard",
        "site": "toolcenter.ai",
        "title": "ToolCenter LLM 排行榜 2026",
    },
    {
        "url": "https://superclueai.com/",
        "site": "superclueai.com",
        "title": "SuperCLUE 中文大模型测评基准",
    },
]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _ensure_prompts(db, project_id: int) -> list[ProjectPrompt]:
    existing = db.scalars(
        select(ProjectPrompt)
        .where(ProjectPrompt.project_id == project_id)
        .order_by(ProjectPrompt.sort, ProjectPrompt.id)
    ).all()
    existing_texts = {p.prompt for p in existing}
    next_sort = (max((p.sort for p in existing), default=-1)) + 1
    added = 0
    for spec in PROMPTS:
        if spec["prompt"] in existing_texts:
            continue
        db.add(
            ProjectPrompt(
                project_id=project_id,
                prompt=spec["prompt"],
                category=spec["category"],
                status=PromptStatus.MONITORING,
                sort=next_sort,
            )
        )
        existing_texts.add(spec["prompt"])
        next_sort += 1
        added += 1
    if added:
        print(f"  added {added} new prompt(s)", flush=True)
    db.flush()
    return db.scalars(
        select(ProjectPrompt)
        .where(ProjectPrompt.project_id == project_id)
        .order_by(ProjectPrompt.sort, ProjectPrompt.id)
    ).all()


def _ensure_keywords(db, project_id: int) -> list[ProjectKeyword]:
    existing = db.scalars(
        select(ProjectKeyword).where(ProjectKeyword.project_id == project_id)
    ).all()
    existing_texts = {k.keyword for k in existing}
    next_sort = (max((k.sort for k in existing), default=-1)) + 1
    added = 0
    for kw in KEYWORDS:
        if kw in existing_texts:
            continue
        db.add(ProjectKeyword(project_id=project_id, keyword=kw, sort=next_sort))
        existing_texts.add(kw)
        next_sort += 1
        added += 1
    if added:
        print(f"  added {added} keyword(s)", flush=True)
    db.flush()
    return db.scalars(
        select(ProjectKeyword)
        .where(ProjectKeyword.project_id == project_id)
        .order_by(ProjectKeyword.sort)
    ).all()


def _ensure_competitors(
    db, project_id: int
) -> list[ProjectCompetitor]:
    existing_names = {
        r.name
        for r in db.scalars(
            select(ProjectCompetitor).where(
                ProjectCompetitor.project_id == project_id
            )
        ).all()
    }
    next_sort = 100
    added = 0
    for spec in EXTRA_COMPETITORS:
        if spec["name"] in existing_names:
            continue
        db.add(
            ProjectCompetitor(
                project_id=project_id,
                name=spec["name"],
                aliases=spec["aliases"],
                note=spec["note"],
                origin="manual",
                status=CompetitorStatus.CONFIRMED,
                sort=next_sort,
            )
        )
        existing_names.add(spec["name"])
        next_sort += 1
        added += 1
    if added:
        print(f"  added {added} competitor(s)", flush=True)
    db.flush()
    return db.scalars(
        select(ProjectCompetitor)
        .where(
            ProjectCompetitor.project_id == project_id,
            ProjectCompetitor.status == CompetitorStatus.CONFIRMED,
        )
        .order_by(ProjectCompetitor.sort)
    ).all()


def _ensure_platforms(db, project_id: int) -> list[ProjectPlatform]:
    """Add the new platforms if missing. Existing rows are left alone so
    their ``sort`` / ``mode`` won't get overwritten on re-runs.
    """
    existing_keys = {
        r.platform
        for r in db.scalars(
            select(ProjectPlatform).where(
                ProjectPlatform.project_id == project_id
            )
        ).all()
    }
    next_sort = (
        max(
            (
                r.sort
                for r in db.scalars(
                    select(ProjectPlatform).where(
                        ProjectPlatform.project_id == project_id
                    )
                ).all()
            ),
            default=0,
        )
        + 1
    )
    added = 0
    for spec in EXTRA_PLATFORMS:
        if spec["platform"] in existing_keys:
            continue
        db.add(
            ProjectPlatform(
                project_id=project_id,
                platform=spec["platform"],
                mode="web",
                delivery_mode=DeliveryMode.WEB,
                thinking_mode=False,
                screenshot=0,
                sort=next_sort,
            )
        )
        existing_keys.add(spec["platform"])
        next_sort += 1
        added += 1
    if added:
        print(f"  added {added} platform(s)", flush=True)
    db.flush()
    return sorted(
        db.scalars(
            select(ProjectPlatform).where(
                ProjectPlatform.project_id == project_id
            )
        ).all(),
        key=lambda r: r.sort,
    )


def _pick_competitors(rng: random.Random, pool: list[str], k: int) -> list[str]:
    return rng.sample(pool, k=min(k, len(pool)))


def _build_answer(
    rng: random.Random,
    template: str,
    title: str,
    competitors: list[str],
    lead: str,
) -> str:
    """``competitors`` carries the brand names picked for this answer;
    pad missing slots with named fall-backs so unfilled ``{cN}`` slots
    still produce readable text.
    """
    fallbacks = ["豆包", "元宝", "通义千问", "百度文心", "腾讯混元", "智谱清言"]
    pool = list(competitors)
    while len(pool) < len(fallbacks):
        pool.append(fallbacks[len(pool)])
    fmt = {
        "title": title,
        "lead": lead,
        "self": SELF_BRAND,
        "c1": pool[0],
        "c2": pool[1],
        "c3": pool[2],
        "c4": pool[3],
        "c5": pool[4],
    }
    return template.format(**fmt)


def _count_brand(text: str, canonical: str, aliases: list[str]) -> tuple[str, int]:
    """Mirror ``extraction._find_brand`` so the seed regex output matches
    what the production pipeline would compute.
    """
    needles = [canonical, *(a for a in aliases if a and a.strip())]
    seen: set[str] = set()
    ordered: list[str] = []
    for n in needles:
        if n not in seen:
            seen.add(n)
            ordered.append(n)
    if not ordered:
        return "", 0
    pattern = re.compile("|".join(re.escape(n) for n in ordered))
    if not pattern.search(text):
        return "", 0
    count = len(pattern.findall(text))
    for n in ordered:
        if n in text:
            return n, count
    return ordered[0], count


def _decide_extraction_status(rng: random.Random) -> ExtractStatus:
    r = rng.random()
    if r < 0.78:
        return ExtractStatus.SUCCESS
    if r < 0.92:
        return ExtractStatus.PENDING
    return ExtractStatus.FAILED


def _rank_for_brand(
    rng: random.Random,
    canonical: str,
    home_platform: str | None,
    platform: str,
    presence_in_answer: int,
) -> int | None:
    """Self brand always lands in Top-3; competitors mostly 2-5 with a
    18% chance of grabbing rank 1 or 2 so the ranking chart isn't all
    zeros for the lower-tier platforms.
    """
    if presence_in_answer == 0:
        return None
    if rng.random() < 0.08:
        return None
    if canonical == SELF_BRAND:
        if home_platform and platform == home_platform:
            return rng.choice([1, 1, 1, 2])
        return rng.choice([1, 1, 2, 2, 3])
    roll = rng.random()
    if roll < 0.18:
        return rng.choice([1, 2])
    if roll < 0.55:
        return rng.choice([2, 3])
    return rng.choice([3, 4, 5])


def _sentiment_for(rng: random.Random, is_self: bool, recommended: bool) -> float:
    base = rng.uniform(0.7, 0.95) if is_self else rng.uniform(0.35, 0.7)
    if not recommended:
        base -= rng.uniform(0.05, 0.2)
    return round(max(0.0, min(1.0, base)), 2)


def _pick_concerns(rng: random.Random, keywords: list[str], k: int) -> list[str]:
    if not keywords:
        return []
    return rng.sample(keywords, k=min(k, len(keywords)))


def _home_platform_for(canonical: str) -> str | None:
    """Map a brand name to the platform it's primarily associated with so
    rank_position can show 'when asked on the brand's own platform, the
    brand usually wins'. Returns ``None`` for competitors that don't
    have a matching platform in this project (e.g. 智谱清言).
    """
    table = {
        SELF_BRAND: "deepseek",
        "deepseek": "deepseek",
        "豆包": "doubao",
        "doubao": "doubao",
        "元宝": "yuanbao",
        "yuanbao": "yuanbao",
        "通义千问": "qianwen",
        "千问": "qianwen",
        "qianwen": "qianwen",
        "百度文心": "wenxinyiyan",
        "文心一言": "wenxinyiyan",
        "文心": "wenxinyiyan",
        "wenxinyiyan": "wenxinyiyan",
        "ERNIE": "wenxinyiyan",
        "腾讯混元": "hunyuan",
        "混元": "hunyuan",
        "hunyuan": "hunyuan",
    }
    return table.get(canonical)


def _ensure_brand_present(text: str, canonical: str, aliases: list[str]) -> str:
    """Append a sub-mention if the answer text doesn't already contain
    any spelling of the brand — guarantees regex count > 0 so we can
    exercise the per-row logic.
    """
    literal, count = _count_brand(text, canonical, aliases)
    if count > 0:
        return text
    needle = canonical
    if aliases:
        for a in aliases:
            if a and a.strip():
                needle = a
                break
    return text + f"\n\n(补充：相关讨论也经常引用「{needle}」的同期发布。)\n"


def _make_id() -> str:
    return secrets.token_hex(16)


# --------------------------------------------------------------------------
# Main entry
# --------------------------------------------------------------------------


def seed_project(project_id: int, *, seed: int = DEFAULT_SEED) -> None:
    rng = random.Random(seed)
    factory = get_session_factory()
    db = factory()
    try:
        project = db.get(Project, project_id)
        if project is None:
            print(f"project {project_id} not found", file=sys.stderr)
            sys.exit(1)
        print(f"seeding project {project.id} ({project.name})")

        # Drop any prior data we wrote on a previous run so the seed is
        # idempotent. ``raw_request_json->>'$.__seed_dev_data__' = 'dev-seed-v2'``
        # is the marker. We delete bottom-up (mentions -> subtasks -> tasks)
        # so the FK-less columns stay referentially intact.
        marker = _seed_marker_value()
        prior_task_ids = db.scalars(
            select(Task.task_id).where(
                Task.project_id == project_id,
                Task.raw_request_json[SEED_MARKER_KEY].as_string() == marker,
            )
        ).all()
        if prior_task_ids:
            print(
                f"  purging prior seed rows for {len(prior_task_ids)} task(s)...",
                flush=True,
            )
            db.execute(
                delete(BrandMention).where(
                    BrandMention.task_id.in_(prior_task_ids)
                )
            )
            db.execute(
                delete(Subtask).where(Subtask.task_id.in_(prior_task_ids))
            )
            db.execute(delete(Task).where(Task.task_id.in_(prior_task_ids)))
            db.commit()
        # First-time migration: the seed may have been run on the project
        # before the marker existed. Drop anything left over so we always
        # end up with a clean slate for project_id.
        orphan_mentions = db.execute(
            delete(BrandMention).where(BrandMention.project_id == project_id)
        ).rowcount
        orphan_subs = db.execute(
            delete(Subtask).where(
                Subtask.task_id.in_(
                    select(Task.task_id).where(Task.project_id == project_id)
                )
            )
        ).rowcount
        orphan_tasks = db.execute(
            delete(Task).where(Task.project_id == project_id)
        ).rowcount
        if orphan_tasks or orphan_subs or orphan_mentions:
            print(
                f"  purged {orphan_tasks} tasks / {orphan_subs} subtasks / {orphan_mentions} mentions (project-wide)",
                flush=True,
            )
            db.commit()

        prompts = _ensure_prompts(db, project_id)
        keywords = _ensure_keywords(db, project_id)
        competitors = _ensure_competitors(db, project_id)
        competitor_names = [c.name for c in competitors]
        competitor_by_name = {c.name: c for c in competitors}
        keyword_texts = [k.keyword for k in keywords]
        platforms = _ensure_platforms(db, project_id)
        platform_keys = [p.platform for p in platforms]

        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_day = today - timedelta(days=DAYS)

        new_tasks = 0
        new_subs = 0
        new_brands = 0

        for day_idx in range(DAYS + 1):
            day = start_day + timedelta(days=day_idx)
            run_at = day.replace(hour=9, minute=rng.randint(0, 30))
            if rng.random() < 0.10:
                # ~10% of days have no run at all.
                continue

            task_id = _make_id()
            prompts_snapshot = [p.prompt for p in prompts]
            platforms_snapshot = [
                {
                    "mode": "web",
                    "platform": pk,
                    "screenshot": 0,
                    "thinkingMode": False,
                }
                for pk in platform_keys
            ]
            total_items = len(prompts_snapshot) * len(platforms_snapshot)
            task = Task(
                task_id=task_id,
                status="completed",
                prompts_json=prompts_snapshot,
                platforms_json=platforms_snapshot,
                region_code_json=[{"cityCode": "110100", "cityName": "北京"}],
                callback_url=None,
                total_items=total_items,
                completed_items=total_items,
                failed_items=0,
                poll_url=None,
                remote_created_at=int(run_at.timestamp() * 1000),
                remote_completed_at=int(
                    (run_at + timedelta(seconds=120)).timestamp() * 1000
                ),
                raw_request_json={
                    "prompts": prompts_snapshot,
                    "platforms": platforms_snapshot,
                    SEED_MARKER_KEY: _seed_marker_value(),
                },
                raw_response_json={"success": True, "code": 200},
                customer_id=project.customer_id,
                project_id=project.id,
                created_local_at=run_at,
            )
            db.add(task)
            new_tasks += 1
            db.flush()

            for pi, prompt in enumerate(prompts_snapshot):
                prompt_title = TITLES[pi]
                competitors_in_answer = _pick_competitors(
                    rng, competitor_names, k=rng.randint(3, 5)
                )
                lead = rng.choice(LEADS)
                template = ANSWER_TEMPLATES[pi % len(ANSWER_TEMPLATES)]

                base_answer = _build_answer(
                    rng, template, prompt_title, competitors_in_answer, lead
                )

                for pk in platform_keys:
                    # Force-mention competitors in random subsets so the
                    # per-subtask mention rates vary across competitors.
                    # The self brand is always in the answer (templates
                    # include it) so self_mention_count=1 for every
                    # subtask; the platform-level variation in the bar
                    # chart now comes from competitor inclusion + answer
                    # template choice rather than from skipping self rows.
                    included_competitors: list[str] = []
                    for cname in competitor_names:
                        if rng.random() < 0.55:
                            included_competitors.append(cname)
                    if not included_competitors:
                        included_competitors = [competitors_in_answer[0]]

                    answer = _ensure_brand_present(
                        base_answer, SELF_BRAND, SELF_ALIASES
                    )

                    sub_id = _make_id()
                    ref_picks = rng.sample(REFERENCES, k=rng.randint(2, 4))
                    sub = Subtask(
                        subtask_id=sub_id,
                        task_id=task_id,
                        platform=pk,
                        mode="web",
                        prompt=prompt,
                        status="success",
                        time=run_at.strftime("%Y-%m-%d %H:%M:%S"),
                        page_screenshot=None,
                        answer_content=answer,
                        reference_list_json=ref_picks,
                        citation_list_json=[r["url"] for r in ref_picks],
                        reasoning_process_json=None,
                        recommended_questions_json=[],
                        media_content_json=None,
                        error_message=None,
                        proxy_ip=None,
                        raw_result_json={"success": True, "code": 200},
                    )
                    db.add(sub)
                    db.flush()
                    new_subs += 1

                    # Every (subtask × brand_target) gets a row, including
                    # unmentioned brands (mention_count=0, status=SKIPPED).
                    # Mirrors ``app.services.extraction._regex_pass`` so
                    # the seed reflects the same invariant the production
                    # pipeline maintains.
                    all_brand_targets: list[tuple[str, list[str], bool]] = [
                        (SELF_BRAND, SELF_ALIASES, True)
                    ]
                    for cname in competitor_names:
                        if cname.lower() == SELF_BRAND.lower():
                            continue
                        row_meta = competitor_by_name.get(cname)
                        aliases = (
                            list(row_meta.aliases or []) if row_meta else []
                        )
                        all_brand_targets.append((cname, aliases, False))

                    mentioned_set = {SELF_BRAND}
                    for cname in included_competitors:
                        if cname.lower() != SELF_BRAND.lower():
                            mentioned_set.add(cname)

                    for canonical, aliases, is_self in all_brand_targets:
                        if canonical in mentioned_set:
                            answer = _ensure_brand_present(
                                answer, canonical, aliases
                            )
                            literal, count = _count_brand(
                                answer, canonical, aliases
                            )
                            if count == 0:
                                new_brands += _add_zero_row(
                                    db,
                                    sub_id=sub_id,
                                    task_id=task_id,
                                    project=project,
                                    prompt=prompt,
                                    platform=pk,
                                    canonical=canonical,
                                    is_self=is_self,
                                    created_at=run_at,
                                )
                                continue
                            status = _decide_extraction_status(rng)
                            recommended = (
                                rng.random() < 0.85 if is_self else rng.random() < 0.15
                            )
                            concerns = _pick_concerns(
                                rng,
                                keyword_texts,
                                k=rng.randint(1, 2) if is_self else rng.randint(0, 1),
                            )
                            sent = _sentiment_for(rng, is_self, recommended)
                            new_brands += _add_brand_row(
                                db,
                                sub_id=sub_id,
                                task_id=task_id,
                                project=project,
                                prompt=prompt,
                                platform=pk,
                                canonical=canonical,
                                literal=literal,
                                count=count,
                                is_self=is_self,
                                home_platform=_home_platform_for(canonical),
                                status=status,
                                rng=rng,
                                recommended=recommended,
                                concerns=concerns,
                                sentiment=sent,
                                created_at=run_at,
                            )
                        else:
                            new_brands += _add_zero_row(
                                db,
                                sub_id=sub_id,
                                task_id=task_id,
                                project=project,
                                prompt=prompt,
                                platform=pk,
                                canonical=canonical,
                                is_self=is_self,
                                created_at=run_at,
                            )

                    # No-answer subtasks: roll a few (~5% per platform
                    # pair) where the answer is empty so the dashboard
                    # has a "no data" column on a couple of days.
                    if rng.random() < 0.05:
                        empty_sub_id = _make_id()
                        db.add(
                            Subtask(
                                subtask_id=empty_sub_id,
                                task_id=task_id,
                                platform=pk,
                                mode="web",
                                prompt=prompt,
                                status="failed",
                                time=run_at.strftime("%Y-%m-%d %H:%M:%S"),
                                page_screenshot=None,
                                answer_content="",
                                reference_list_json=None,
                                citation_list_json=None,
                                reasoning_process_json=None,
                                recommended_questions_json=None,
                                media_content_json=None,
                                error_message="远程接口超时",
                                proxy_ip=None,
                                raw_result_json={
                                    "success": False,
                                    "code": 500001,
                                    "message": "remote timeout",
                                },
                            )
                        )
                        new_subs += 1

        print(
            f"  inserted: tasks={new_tasks} subtasks={new_subs} brand_mentions={new_brands}"
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _add_brand_row(
    db,
    *,
    sub_id: str,
    task_id: str,
    project: Project,
    prompt: str,
    platform: str,
    canonical: str,
    literal: str,
    count: int,
    is_self: bool,
    home_platform: str,
    status: ExtractStatus,
    rng: random.Random,
    recommended: bool,
    concerns: list[str],
    sentiment: float,
    created_at,
) -> int:
    row = BrandMention(
        subtask_id=sub_id,
        task_id=task_id,
        project_id=project.id,
        customer_id=project.customer_id,
        prompt=prompt,
        platform=platform,
        brand_canonical=canonical,
        is_self=is_self,
        mention_count=1 if count > 0 else 0,
        rank_position=_rank_for_brand(
            rng, canonical, home_platform, platform, count
        ),
        sentiment_score=sentiment,
        is_recommended=(
            recommended if status == ExtractStatus.SUCCESS else None
        ),
        concern_hits_json=(
            concerns if status == ExtractStatus.SUCCESS else None
        ),
        extract_status=status,
        extract_error=(
            "LLM 调用超时，已重试 2 次"
            if status == ExtractStatus.FAILED
            else None
        ),
        raw_extraction=(
            {
                "rank_position": 1,
                "sentiment_score": sentiment,
                "is_recommended": recommended,
                "concern_hits": concerns,
            }
            if status == ExtractStatus.SUCCESS
            else None
        ),
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(row)
    return 1


def _add_zero_row(
    db,
    *,
    sub_id: str,
    task_id: str,
    project: Project,
    prompt: str,
    platform: str,
    canonical: str,
    is_self: bool,
    created_at,
) -> int:
    """Write a brand-mention row for a brand that wasn't mentioned.

    Per the (subtask × brand_target) invariant, every subtask has a row
    for the self brand and every configured competitor — even when the
    answer never mentions the brand. ``mention_count=0`` and
    ``extract_status=SKIPPED`` are the production pipeline's signals that
    "no LLM call needed" — rank/sentiment stay NULL because they have no
    meaningful value when the brand isn't in the answer.
    """
    row = BrandMention(
        subtask_id=sub_id,
        task_id=task_id,
        project_id=project.id,
        customer_id=project.customer_id,
        prompt=prompt,
        platform=platform,
        brand_canonical=canonical,
        is_self=is_self,
        mention_count=0,
        rank_position=None,
        sentiment_score=None,
        is_recommended=None,
        concern_hits_json=None,
        extract_status=ExtractStatus.SKIPPED,
        extract_error=None,
        raw_extraction=None,
        created_at=created_at,
        updated_at=created_at,
    )
    db.add(row)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=int, default=PROJECT_ID, help="project id")
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="random seed (default deterministic)"
    )
    args = parser.parse_args()
    seed_project(args.project, seed=args.seed)


if __name__ == "__main__":
    main()
