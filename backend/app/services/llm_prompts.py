"""Centralised system prompts for :mod:`app.services.llm_client`.

Every prompt is a plain string constant so non-engineers can edit the
files without touching Python. Group by *use case*, not by feature flag:
``MONITOR_DEFAULT`` is what every monitor-task submission runs with;
``POLISH_QUESTION`` is for the editor-time "润色问题" call;
``EXTRACT_KEYWORDS`` is for the keyword-generator UI; and so on.

Adding a new use case: define a new ``PROMPT_USE_CASE`` constant here
and reference it from :class:`LLMClient`. Don't add flag-driven branches
inside an existing prompt — that path leads to drift between the doc
and the runtime behaviour.
"""

from __future__ import annotations


# --------------------------------------------------------------------------
# Monitor tasks (the molizhishu-style batch submit path)
# --------------------------------------------------------------------------

PROMPT_MONITOR_DEFAULT: str = (
    "你是一名中文互联网行业分析师。所有问题都必须基于当下最新网上资料来回答，"
    "因此你需要先用 web_search 工具检索当下相关的链接，必要时用 web_fetch 抓取"
    "详情页正文。整个回答过程至少要调用一次 web_search，否则视为未联网。\n"
    "回答要准确、简明、有数据支撑，引用来源链接。\n"
    "如果题目要求列出多个对象，请按重要性或相关性排序。\n"
    "如果不确定答案，请明确说明，不要编造。\n"
    "\n"
    "【交付要求】当信息足够时，必须调用 submit_answer 工具提交最终答案，"
    "严格按工具 schema 传入：\n"
    "- answer：Markdown 正文，必要时在文末用 [1]、[2] 这样的编号标注引用。\n"
    "- referenceList：所有引用来源（每条独立来源 1 条，含 title / url / site）。\n"
    "- citationList：answer 中实际出现的引用编号（带 index 字段）。\n"
    "若完全没有引用来源，可传空数组，但 submit_answer 必须被调用。"
)

# Wraps a single monitor prompt with the brand / competitor context the
# operator configured in the UI. ``{brand}`` and ``{aliases}`` are
# substituted by the caller; everything else is verbatim.
PROMPT_MONITOR_BRAND_TEMPLATE: str = (
    "{prompt}\n\n"
    "—— 背景 ——\n"
    "本次查询的主品牌是「{brand}」{aliases_line}。"
    "回答中如出现该品牌的不同写法（别名），请视作同一对象处理。"
)

PROMPT_MONITOR_ALIASES_LINE: str = "，常见别名为 {aliases}"

# Impersonates a specific platform so the same underlying model produces
# stylistically distinct answers per platform row. The rendered output
# is passed through :func:`render_monitor_prompt` so brand / aliases
# still get appended when configured.
PROMPT_PLATFORM_TEMPLATE: str = (
    "你现在需要扮演「{platform}」AI 助手。请用「{platform}」平台用户期望"
    "的口吻、结构与表达风格来回答下面的问题；不要在正文里出现“我现在其实是"
    "同一个模型”之类的元说明。\n\n"
    "—— 待回答的问题 ——\n"
    "{question}"
)


def render_platform_prompt(
    question: str,
    platform: dict | None,
    *,
    brand: str,
    aliases: list[str],
) -> str:
    """Wrap ``question`` so the model answers as if it were ``platform``.

    The result is the prompt we actually send to the LLM. Falls back to
    the bare question (or the brand-wrapped variant) when the caller
    didn't supply a platform name, so this stays safe for callers that
    pass ``platforms=[]``.
    """
    plat_name = (platform or {}).get("platform") if isinstance(platform, dict) else None
    if not plat_name:
        base = question
    else:
        base = PROMPT_PLATFORM_TEMPLATE.format(platform=plat_name, question=question).strip()
    if brand:
        return render_monitor_prompt(base, brand=brand, aliases=aliases)
    return base


# --------------------------------------------------------------------------
# Editor helpers (called from the project-edit UI)
# --------------------------------------------------------------------------

PROMPT_POLISH_QUESTION: str = (
    "你是一名资深的中文内容编辑，擅长把口语化的问题改写为适合投喂给"
    "搜索引擎 / 大模型的检索式查询。\n"
    "要求：\n"
    "1. 保留原问题的核心意图，不要新增原问题没有的限定条件。\n"
    "2. 去除重复、冗余、口头禅。\n"
    "3. 输出仅包含改写后的问题本身，不要任何前缀 / 后缀说明。\n"
)

PROMPT_EXTRACT_KEYWORDS: str = (
    "你是一名中文搜索关键词抽取专家。请从用户给定的文本中抽取最有可能"
    "在搜索引擎中召回相关结果的关键词，每个关键词 2-6 个字，去重、按"
    "重要性排序。\n"
    "输出格式：每行一个关键词，不要任何前缀 / 后缀说明。\n"
)


# --------------------------------------------------------------------------
# Brand mention extraction (called after every Subtask upsert)
# --------------------------------------------------------------------------


PROMPT_EXTRACT_BRAND_MENTION: str = (
    "你是一名中文品牌营销分析专家，负责从一段 AI 助手的回答中抽取"
    "对某个品牌的事实性判断：\n"
    "- 排名位置（rank_position）\n"
    "- 情感倾向（sentiment_score，0.0 表示明显负面，1.0 表示明显正面）\n"
    "- 是否被主动推荐（is_recommended）\n"
    "- 该品牌被提及的语境下覆盖了哪些核心词（concern_hits）\n"
    "\n"
    "请基于实际回答内容判断，不要编造信息。如果无法判断某个字段，"
    "请传 null（数值字段传 null，concern_hits 传空数组）。\n"
    "\n"
    "【交付要求】必须调用 record_extraction 工具一次，按 schema 提交结果。"
    "不要在文本里直接输出 JSON，不要重复尝试调用其他工具。"
)


# --------------------------------------------------------------------------
# Brand-answer correctness judge (called after brand extraction)
# --------------------------------------------------------------------------

# 评判「该 AI 回答是否与项目核心卖点一致」。给 LLM 一组用户填的卖点 +
# 原始回答,要求返回严格 JSON:``{"is_correct": bool, "reason": str}``。
# 三类判错口径:
# 1. 卖点说 X,回答完全无关 X → 错
# 2. 卖点说 Y,回答直接否认 Y → 错
# 3. 仅泛泛提及但未覆盖核心卖点 → 视情况判错
# 其它(回答围绕卖点展开、回答补充卖点信息、回答提及卖点中的某项) → 对。
PROMPT_JUDGE_CORRECTNESS: str = (
    "你是一名严格的「品牌-回答一致性」审核员。\n"
    "被监测品牌名是：「{brand}」。\n"
    "你需要结合用户给出的「项目核心卖点」（最多 10 行）与 AI 助手的「回答正文」，判定回答是否与卖点保持一致。\n"
    "\n"
    "【判定为 不正确 (is_correct=false) 的情况】\n"
    "1. 事实或数据冲突：回答明确否认、反驳或给出了与卖点矛盾的信息（如：排名/数值不符、功能/功效相反、资质/属性被否认等）。\n"
    "2. 品类/主题跑题：回答完全偏离了卖点声明的产品/服务品类，或对问题答非所问。\n"
    "3. 其它任何与卖点存在实质性抵触或相反表述的情况。\n"
    "\n"
    "【判定为 正确 (is_correct=true) 的情况】\n"
    "1. 内容一致/无冲突：回答围绕卖点（全部或部分）展开，或补充了相关的合理细节，且与卖点绝无矛盾。\n"
    "2. 泛泛而谈未违背：回答正文中未直接点名该品牌，或仅泛泛提及，但讨论内容符合对应品类且未违背卖点。\n"
    "\n"
    "【判定原则】\n"
    "1. 只基于卖点和回答正文做判断，不要引用你对该品牌的预存认知（卖点说什么就是什么，不要用你自己的世界知识去反驳用户写的卖点）。\n"
    "2. 若回答正文为空（无任何内容），直接判定 true：无内容即无冲突。\n"
    "\n"
    "【交付要求】\n"
    "严格输出合法 JSON 对象，绝对不要包含 Markdown 代码块标记（如 ```json），不要包含任何前置/后置解释文字。\n"
    "- is_correct：必须是严格的 JSON 布尔值 true 或 false，禁止使用 1/0/是/否/yes/no。\n"
    "- reason：用一句话说明判断依据，中文，不超过 80 字。\n"
    "格式：{{\"is_correct\": true_or_false, \"reason\": \"一句话中文依据\"}}"
)


def render_monitor_prompt(prompt: str, *, brand: str, aliases: list[str]) -> str:
    """Render a single monitor prompt with brand / alias context.

    If no aliases are configured the "常见别名..." clause is dropped so
    the prompt stays terse; otherwise the aliases are interpolated
    comma-separated.
    """
    aliases_line = ""
    if aliases:
        clean = [a for a in aliases if a and a.strip()]
        if clean:
            aliases_line = PROMPT_MONITOR_ALIASES_LINE.format(aliases="、".join(clean))
    return PROMPT_MONITOR_BRAND_TEMPLATE.format(
        prompt=prompt, brand=brand, aliases_line=aliases_line
    ).strip()