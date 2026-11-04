"""外部监控数据 xlsx 导入 —— 解析 / 校验 / 落库三段。

设计要点见 docs/superpowers/specs/2026-11-04-data-import-design.md。

铁律（改动本模块前务必先读 spec）：
1. 导入只写事实数据（tasks / subtasks / brand_mentions / runs），
   **绝不写** prompts / keywords / platforms / competitors —— 那是用户
   事先建好的项目配置。
2. 落库时 prompt 写**项目配置的原文**，不是文件里的文本 —— 平台按
   prompt 文本做问题筛选，写错会让筛选一条都选不中。
3. 时间戳回填到监控日期 —— 所有分析窗口都按 created_at 过滤。
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field

import openpyxl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.media_dictionary import MediaDictionary
from app.models.project import (
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.schemas.import_data import (
    ImportErrorGroup,
    ImportErrorSample,
    ImportPreviewOut,
    ImportTotals,
    ImportWarning,
    MappingRow,
    SheetPreview,
)

SHEET_KEYS: tuple[str, ...] = ("answers", "competitors", "citations")

#: 中文模型名 -> (web 的 platform_code, mobile 的 platform_code)。
#: 注意「通义千问」在前端向导里叫「千问」；「百度文心」的 mobile 代码是
#: ``baidu_mobile``（后缀不统一），所以不能靠「去掉后缀」推导，必须查表。
MODEL_ALIASES: dict[str, tuple[str, str]] = {
    "豆包": ("doubao", "doubao_mobile"),
    "元宝": ("yuanbao", "yuanbao_mobile"),
    "通义千问": ("qianwen", "qianwen_mobile"),
    "千问": ("qianwen", "qianwen_mobile"),
    "Kimi": ("kimi", "kimi_mobile"),
    "DeepSeek": ("deepseek", "deepseek_mobile"),
    "百度文心": ("baiduai", "baidu_mobile"),
    "文心": ("baiduai", "baidu_mobile"),
}

#: 模型标签后缀 -> delivery_mode
DELIVERY_BY_SUFFIX: dict[str, str] = {"网页版": "web", "手机版": "mobile"}
#: 「竞品分析」的「网页版/移动版」列 -> delivery_mode（用「移动版」，与标签的「手机版」同义）
DELIVERY_BY_COLUMN: dict[str, str] = {"网页版": "web", "移动版": "mobile"}
#: 「模式」列 -> thinking_mode
MODE_THINKING: dict[str, bool] = {"快速": False, "思考": True}

#: 按表头列名签名定位 sheet —— 不依赖 sheet 名或顺序。
#: 签名里的列是**必需**列（缺了就不是这张 sheet）；其余列全部建索引，
#: 解析时用 ``_opt()`` 取（缺列降级为空串，不 KeyError）。
_SHEET_SIGNATURES: dict[str, set[str]] = {
    "answers": {"监控日期", "AI大模型", "品牌名称", "监控问题", "回答内容"},
    "competitors": {"监控日期", "品牌类型", "品牌名称", "监控问题", "模型名称", "提及次数"},
    "citations": {"引用日期", "模型", "监控问题", "内容链接", "媒体名称"},
}

_PROMPT_PREFIX_RE = re.compile(r"^\s*\d+[.、)）]\s*")
_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})")


@dataclass(frozen=True)
class AnswerRow:
    row: int
    date: str
    model_label: str
    platform_code: str
    delivery_mode: str
    thinking_mode: bool
    brand: str
    keyword: str
    prompt_raw: str
    answer_content: str
    screenshot: str


@dataclass(frozen=True)
class CompetitorRow:
    row: int
    date: str
    brand_type: str
    brand: str
    prompt_raw: str
    keyword: str
    model_label: str
    platform_code: str
    delivery_mode: str
    thinking_mode: bool
    delivery_column: str
    ask_count: int
    mention_count: int
    avg_rank: int | None
    sentiment: str | None


@dataclass(frozen=True)
class CitationRow:
    row: int
    date: str
    model_label: str
    platform_code: str
    delivery_mode: str
    thinking_mode: bool
    prompt_raw: str
    title: str
    url: str
    media_name: str
    media_host: str


@dataclass(frozen=True)
class ParsedWorkbook:
    answers: list[AnswerRow] = field(default_factory=list)
    competitors: list[CompetitorRow] = field(default_factory=list)
    citations: list[CitationRow] = field(default_factory=list)
    found_sheets: frozenset[str] = frozenset()


def normalize_date(value) -> str:
    """datetime 或 ``2026-10-1`` / ``2026-10-01`` 字符串 -> ``YYYY-MM-DD``。

    源文件同一列里混用补零与不补零的写法（问题问答是字符串、竞品分析是
    datetime），不归一化会让跨表引用对不上。
    """
    if value is None:
        return ""
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    m = _DATE_RE.match(str(value).strip())
    if not m:
        return ""
    return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"


def normalize_prompt(text: str) -> str:
    """去行首编号前缀 + 去全部空白 —— 只用于**匹配**，落库另用项目原文。"""
    stripped = _PROMPT_PREFIX_RE.sub("", str(text or "").strip())
    return re.sub(r"\s+", "", stripped)


def parse_model_label(label: str) -> tuple[str, str] | None:
    """``'豆包-网页版'`` -> ``('doubao', 'web')``；未知模型/未知终端返回 None。"""
    name, sep, term = str(label or "").partition("-")
    if not sep:
        return None
    delivery = DELIVERY_BY_SUFFIX.get(term.strip())
    if delivery is None:
        return None
    codes = MODEL_ALIASES.get(name.strip())
    if codes is None:
        return None
    return (codes[1] if delivery == "mobile" else codes[0], delivery)


def derive_sentiment(positive: str, neutral: str, negative: str) -> str | None:
    """正面/中性/负面 三列百分比 -> 单标签。

    三列全 ``-`` -> None（未被提及，无情感信号）；否则取数值最大者；
    并列时取 ``neutral``（最保守，不夸大倾向）。
    """
    scores: dict[str, float] = {}
    for label, raw in (
        ("positive", positive),
        ("neutral", neutral),
        ("negative", negative),
    ):
        text = str(raw if raw is not None else "").strip()
        if text in ("", "-"):
            continue
        try:
            scores[label] = float(text)
        except ValueError:
            continue
    if not scores:
        return None
    best = max(scores.values())
    winners = [k for k, v in scores.items() if v == best]
    if len(winners) > 1:
        return "neutral"
    return winners[0]


def _cell(row, idx: int) -> str:
    """取值并 strip —— 用于键值类字段。idx 为 -1（列不存在）时返回空串。"""
    if idx < 0 or idx >= len(row):
        return ""
    v = row[idx]
    if v is None:
        return ""
    return str(v).strip()


def _raw_cell(row, idx: int) -> str:
    """取值不 strip —— 用于正文/链接类字段（回答内容要原样存）。"""
    if idx < 0 or idx >= len(row):
        return ""
    v = row[idx]
    if v is None:
        return ""
    return str(v)


def _opt(index: dict[str, int], name: str) -> int:
    """可选列的列号；该列不存在时返回 -1，_cell / _raw_cell 会取到空串。"""
    return index.get(name, -1)


def _locate_sheets(wb) -> dict[str, tuple[object, dict[str, int]]]:
    """按表头列名签名定位三张 sheet，返回 ``{key: (行迭代器, 列名->列号)}``。

    签名列只用来**识别**这张 sheet；识别成功后把表头里所有列都建上索引，
    这样「核心词」「模式」「回答截图」这类可选列缺了也只是取到空串，
    而不是 KeyError。
    """
    located: dict[str, tuple[object, dict[str, int]]] = {}
    for key, required in _SHEET_SIGNATURES.items():
        if key in located:
            continue
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            header = next(rows, None)
            if header is None:
                continue
            index: dict[str, int] = {}
            missing = False
            for name in required:
                hits = [
                    i
                    for i, h in enumerate(header)
                    if h is not None and str(h).strip() == name
                ]
                if not hits:
                    missing = True
                    break
                index[name] = hits[0]
            if missing:
                continue
            for i, h in enumerate(header):
                if h is None:
                    continue
                name = str(h).strip()
                if name and name not in index:
                    index[name] = i
            located[key] = (rows, index)
            break
    return located


def _parse_answers(rows, index: dict[str, int]) -> list[AnswerRow]:
    out: list[AnswerRow] = []
    for row_no, row in enumerate(rows, start=2):
        label = _cell(row, index["AI大模型"])
        parsed = parse_model_label(label)
        out.append(
            AnswerRow(
                row=row_no,
                date=normalize_date(row[index["监控日期"]]),
                model_label=label,
                platform_code=parsed[0] if parsed else "",
                delivery_mode=parsed[1] if parsed else "",
                thinking_mode=bool(MODE_THINKING.get(_cell(row, _opt(index, "模式")), False)),
                brand=_cell(row, index["品牌名称"]),
                keyword=_cell(row, _opt(index, "核心词")),
                prompt_raw=_cell(row, index["监控问题"]),
                answer_content=_raw_cell(row, index["回答内容"]),
                screenshot=_cell(row, _opt(index, "回答截图")),
            )
        )
    return out


def _parse_competitors(rows, index: dict[str, int]) -> list[CompetitorRow]:
    out: list[CompetitorRow] = []
    for row_no, row in enumerate(rows, start=2):
        label = _cell(row, index["模型名称"])
        parsed = parse_model_label(label)
        out.append(
            CompetitorRow(
                row=row_no,
                date=normalize_date(row[index["监控日期"]]),
                brand_type=_cell(row, index["品牌类型"]),
                brand=_cell(row, index["品牌名称"]),
                prompt_raw=_cell(row, index["监控问题"]),
                keyword=_cell(row, _opt(index, "核心词")),
                model_label=label,
                platform_code=parsed[0] if parsed else "",
                delivery_mode=parsed[1] if parsed else "",
                thinking_mode=bool(MODE_THINKING.get(_cell(row, _opt(index, "模式")), False)),
                delivery_column=_cell(row, _opt(index, "网页版/移动版")),
                ask_count=_int_cell(row, _opt(index, "提问次数")) or 0,
                mention_count=_int_cell(row, index["提及次数"]) or 0,
                avg_rank=_int_cell(row, _opt(index, "平均排名")),
                sentiment=derive_sentiment(
                    _cell(row, _opt(index, "正面")),
                    _cell(row, _opt(index, "中性")),
                    _cell(row, _opt(index, "负面")),
                ),
            )
        )
    return out


def _parse_citations(rows, index: dict[str, int]) -> list[CitationRow]:
    out: list[CitationRow] = []
    for row_no, row in enumerate(rows, start=2):
        label = _cell(row, index["模型"])
        parsed = parse_model_label(label)
        out.append(
            CitationRow(
                row=row_no,
                date=normalize_date(row[index["引用日期"]]),
                model_label=label,
                platform_code=parsed[0] if parsed else "",
                delivery_mode=parsed[1] if parsed else "",
                thinking_mode=bool(MODE_THINKING.get(_cell(row, _opt(index, "模式")), False)),
                prompt_raw=_cell(row, index["监控问题"]),
                title=_raw_cell(row, _opt(index, "内容标题")),
                url=_raw_cell(row, index["内容链接"]),
                media_name=_cell(row, index["媒体名称"]),
                media_host=_cell(row, _opt(index, "媒体url")),
            )
        )
    return out


def _int_cell(row, idx: int) -> int | None:
    text = _cell(row, idx)
    if text in ("", "-"):
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_workbook(content: bytes) -> ParsedWorkbook:
    """解析 xlsx -> 三张 sheet 的结构化行。

    找不到某张 sheet 不报错，对应列表为空，``found_sheets`` 里记实际找到的；
    但**一张都认不出来**时必须报错 —— 静默返回 0 行会让用户以为导入成功。
    """
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    try:
        located = _locate_sheets(wb)
        if not located:
            raise ValueError(
                "没有找到任何可识别的 sheet —— 文件需包含「问题问答」「竞品分析」"
                "「引用媒体」三张表之一（按表头列名识别，不看 sheet 名）"
            )
        answers = _parse_answers(*located["answers"]) if "answers" in located else []
        competitors = (
            _parse_competitors(*located["competitors"]) if "competitors" in located else []
        )
        citations = _parse_citations(*located["citations"]) if "citations" in located else []
        return ParsedWorkbook(
            answers=answers,
            competitors=competitors,
            citations=citations,
            found_sheets=frozenset(located.keys()),
        )
    finally:
        wb.close()


# --------------------------------------------------------------------------
# 项目配置快照与六维校验
# --------------------------------------------------------------------------


class ImportConfigError(Exception):
    """项目不存在或配置读不出来 —— endpoint 层转 404 / 400。"""


@dataclass(frozen=True)
class ProjectConfig:
    brand: str
    #: 归一化问题 -> 项目里的 prompt 原文列表（>1 说明归一化后有歧义）
    prompt_texts: dict[str, list[str]]
    keywords: frozenset[str]
    #: (platform_code, delivery_mode, thinking_mode)
    platform_keys: frozenset[tuple[str, str, bool]]
    competitor_names: frozenset[str]


@dataclass(frozen=True)
class RowIssue:
    sheet: str
    row: int
    code: str
    message: str
    context: dict[str, str]


@dataclass(frozen=True)
class ValidationOutcome:
    answers: list[AnswerRow]
    competitors: list[CompetitorRow]
    citations: list[CitationRow]
    issues: list[RowIssue]
    warnings: list[str]
    #: 归一化问题 -> 项目里的 prompt 原文（只含无歧义的）
    resolved_prompts: dict[str, str]
    #: subtask_key -> subtask_id
    subtask_index: dict[tuple, str]


def subtask_key(date: str, platform_code: str, delivery_mode: str,
                thinking_mode: bool, prompt_norm: str) -> tuple:
    """跨表主键 —— 日期 × 平台 × 终端 × 思考 × 归一化问题。"""
    return (date, platform_code, delivery_mode, thinking_mode, prompt_norm)


def make_subtask_id(project_id: int, key: tuple) -> str:
    """确定性 subtask_id（列宽 64）。哈希取**归一化后**的问题，
    文件里问题文本微调不会造出重复 subtask。"""
    date, platform_code, delivery_mode, thinking_mode, prompt_norm = key
    digest = hashlib.sha1(prompt_norm.encode("utf-8")).hexdigest()[:10]
    return (
        f"imp_{project_id}_{date.replace('-', '')}_{platform_code}"
        f"_{delivery_mode}_{'T' if thinking_mode else 'F'}_{digest}"
    )


def load_project_config(db: Session, project_id: int) -> ProjectConfig:
    """读项目的配置快照 —— 校验的唯一真源。"""
    project = db.get(Project, project_id)
    if project is None:
        raise ImportConfigError(f"project {project_id} not found")

    prompt_texts: dict[str, list[str]] = {}
    for prompt in db.execute(
        select(ProjectPrompt).where(ProjectPrompt.project_id == project_id)
    ).scalars():
        prompt_texts.setdefault(normalize_prompt(prompt.prompt), []).append(prompt.prompt)

    keywords = frozenset(
        row.keyword
        for row in db.execute(
            select(ProjectKeyword).where(ProjectKeyword.project_id == project_id)
        ).scalars()
    )

    platform_keys = frozenset(
        (row.platform_code, row.delivery_mode.value, bool(row.thinking_mode))
        for row in db.execute(
            select(ProjectPlatform).where(ProjectPlatform.project_id == project_id)
        ).scalars()
    )

    competitor_names = frozenset(
        row.name
        for row in db.execute(
            select(ProjectCompetitor).where(ProjectCompetitor.project_id == project_id)
        ).scalars()
    )

    return ProjectConfig(
        brand=(project.brand or "").strip(),
        prompt_texts=prompt_texts,
        keywords=keywords,
        platform_keys=platform_keys,
        competitor_names=competitor_names,
    )


def _issue(sheet: str, row: int, code: str, message: str, **context) -> RowIssue:
    return RowIssue(
        sheet=sheet, row=row, code=code, message=message,
        context={k: v for k, v in context.items() if v},
    )


def _common_issues(sheet: str, row_no: int, date: str, platform_code: str,
                   delivery_mode: str, thinking_mode: bool, prompt_raw: str,
                   keyword: str, config: ProjectConfig) -> list[RowIssue]:
    """与品牌无关的五个维度：日期 / 问题 / 平台 / 核心词 / 归一化歧义。"""
    issues: list[RowIssue] = []
    if not date:
        issues.append(_issue(sheet, row_no, "date_missing", "监控日期缺失或无法解析"))
    prompt_norm = normalize_prompt(prompt_raw)
    texts = config.prompt_texts.get(prompt_norm)
    if not texts:
        issues.append(_issue(
            sheet, row_no, "prompt_unregistered",
            "监控问题不在当前项目的问题配置里，请先在「监控问题」Tab 添加",
            监控问题=prompt_raw,
        ))
    elif len(texts) > 1:
        issues.append(_issue(
            sheet, row_no, "prompt_ambiguous",
            "该问题在项目配置里有多个候选，无法确定对应哪一条",
            监控问题=prompt_raw,
        ))
    if (platform_code, delivery_mode, thinking_mode) not in config.platform_keys:
        issues.append(_issue(
            sheet, row_no, "platform_unregistered",
            "该模型 / 终端组合不在当前项目的模型配置里，请先在「AI 模型」Tab 添加",
            AI大模型=platform_code,
        ))
    if config.keywords and keyword not in config.keywords:
        issues.append(_issue(
            sheet, row_no, "keyword_unregistered",
            "核心词不在当前项目的核心词配置里",
            核心词=keyword,
        ))
    return issues


def validate_rows(db: Session, project_id: int, parsed: ParsedWorkbook,
                  selected_sheets=None) -> ValidationOutcome:
    """六维逐行校验 —— 通过的行进 outcome，不通过的进 issues。"""
    config = load_project_config(db, project_id)
    selected = set(selected_sheets) if selected_sheets else set(SHEET_KEYS)
    issues: list[RowIssue] = []
    warnings: list[str] = []
    resolved_prompts = {
        norm: texts[0] for norm, texts in config.prompt_texts.items() if len(texts) == 1
    }

    # --- 问题问答 ---
    ok_answers: list[AnswerRow] = []
    for row in parsed.answers:
        if "answers" not in selected:
            continue
        row_issues = _common_issues(
            "问题问答", row.row, row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, row.prompt_raw, row.keyword, config,
        )
        if config.brand and row.brand != config.brand:
            row_issues.append(_issue(
                "问题问答", row.row, "brand_mismatch",
                "品牌名称与当前项目的监控品牌不一致",
                品牌名称=row.brand,
            ))
        if row_issues:
            issues.extend(row_issues)
            continue
        ok_answers.append(row)
        project_text = resolved_prompts[normalize_prompt(row.prompt_raw)]
        if project_text != row.prompt_raw:
            warnings.append(
                f"监控问题「{row.prompt_raw}」与项目配置里的「{project_text}」"
                "不完全一致，已按归一化匹配"
            )

    subtask_index: dict[tuple, str] = {}
    for row in ok_answers:
        key = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        )
        subtask_index[key] = make_subtask_id(project_id, key)

    # --- 竞品分析 ---
    ok_competitors: list[CompetitorRow] = []
    for row in parsed.competitors:
        if "competitors" not in selected:
            continue
        row_issues = _common_issues(
            "竞品分析", row.row, row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, row.prompt_raw, row.keyword, config,
        )
        if row.brand_type == "监控品牌":
            if config.brand and row.brand != config.brand:
                row_issues.append(_issue(
                    "竞品分析", row.row, "brand_mismatch",
                    "监控品牌与当前项目的监控品牌不一致",
                    品牌名称=row.brand,
                ))
        elif row.brand not in config.competitor_names:
            row_issues.append(_issue(
                "竞品分析", row.row, "competitor_unregistered",
                "该品牌不在当前项目的竞品列表里，请先在「竞品信息」Tab 添加",
                品牌名称=row.brand,
            ))
        key = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        )
        if key not in subtask_index:
            row_issues.append(_issue(
                "竞品分析", row.row, "subtask_not_found",
                "找不到对应的回答记录（日期 / 模型 / 问题组合在「问题问答」里不存在）",
                监控日期=row.date, AI大模型=row.model_label, 监控问题=row.prompt_raw,
            ))
        if row_issues:
            issues.extend(row_issues)
            continue
        ok_competitors.append(row)
        column_delivery = DELIVERY_BY_COLUMN.get(row.delivery_column)
        if column_delivery and column_delivery != row.delivery_mode:
            warnings.append(
                f"第 {row.row} 行的「网页版/移动版」列与模型标签后缀不一致，"
                "已按模型标签为准"
            )

    # --- 引用媒体 ---
    ok_citations: list[CitationRow] = []
    for row in parsed.citations:
        if "citations" not in selected:
            continue
        row_issues = _common_issues(
            "引用媒体", row.row, row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, row.prompt_raw, "", config,
        )
        if not row.media_name:
            row_issues.append(_issue(
                "引用媒体", row.row, "media_name_blank",
                "媒体名称为空，无法归类信源",
                内容链接=row.url,
            ))
        key = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        )
        if key not in subtask_index:
            row_issues.append(_issue(
                "引用媒体", row.row, "subtask_not_found",
                "找不到对应的回答记录（日期 / 模型 / 问题组合在「问题问答」里不存在）",
                监控日期=row.date, AI大模型=row.model_label, 监控问题=row.prompt_raw,
            ))
        if row_issues:
            issues.extend(row_issues)
            continue
        ok_citations.append(row)

    # 汇总去重后的 warning
    unique_warnings = list(dict.fromkeys(warnings))
    return ValidationOutcome(
        answers=ok_answers,
        competitors=ok_competitors,
        citations=ok_citations,
        issues=issues,
        warnings=unique_warnings,
        resolved_prompts=resolved_prompts,
        subtask_index=subtask_index,
    )


# --------------------------------------------------------------------------
# 预览聚合
# --------------------------------------------------------------------------

_SHEET_TITLES = {
    "answers": "问题问答",
    "competitors": "竞品分析",
    "citations": "引用媒体",
}

#: 对账条内容 —— 外部列 -> 平台内部字段。
_MAPPING_ROWS: list[MappingRow] = [
    MappingRow(source="监控日期", target="Task.triggered_at · Run.triggered_at",
               note="按日期分组，一个日期一个任务"),
    MappingRow(source="AI大模型「豆包-网页版」",
               target="platform=doubao · delivery=web · thinking=否",
               note="中文名查别名表，后缀拆终端"),
    MappingRow(source="模式「快速」/「思考」", target="thinking_mode = 否 / 是", note=""),
    MappingRow(source="监控问题", target="Subtask.prompt（项目配置原文）",
               note="归一化后匹配，落库存项目原文"),
    MappingRow(source="回答内容", target="Subtask.answer_content", note="原样存 Markdown"),
    MappingRow(source="回答截图", target="Subtask.page_screenshot", note=""),
    MappingRow(source="品牌类型「监控品牌」", target="BrandMention.is_self = 1",
               note="品牌名须等于项目 brand"),
    MappingRow(source="品牌类型「竞品品牌」", target="BrandMention.is_self = 0",
               note="品牌名须在项目竞品列表"),
    MappingRow(source="提及次数 · 平均排名", target="is_mention · rank_position",
               note="is_recommended 由 rank ≤ 5 派生"),
    MappingRow(source="正面 · 中性 · 负面", target="sentiment",
               note="取占比最高者，并列取中性"),
    MappingRow(source="内容链接 · 媒体名称 · 内容标题", target="url · site · title",
               note="site 存中文媒体名，host 从 url 提取"),
]

_MAX_DISTINCT = 500
_MAX_SAMPLES = 20


def _group_issues(issues: list[RowIssue]) -> list[ImportErrorGroup]:
    """按 (sheet, code) 聚合错误 —— 2190 行同因错误只带 20 条样本。"""
    buckets: dict[tuple[str, str], list[RowIssue]] = {}
    for issue in issues:
        buckets.setdefault((issue.sheet, issue.code), []).append(issue)
    groups: list[ImportErrorGroup] = []
    for (sheet, code), items in buckets.items():
        distinct = sorted({
            value
            for item in items
            for value in item.context.values()
            if value
        })
        groups.append(ImportErrorGroup(
            sheet=sheet,
            code=code,
            message=items[0].message,
            row_count=len(items),
            distinct=distinct[:_MAX_DISTINCT],
            samples=[
                ImportErrorSample(row=item.row, context=item.context)
                for item in items[:_MAX_SAMPLES]
            ],
        ))
    groups.sort(key=lambda g: (-g.row_count, g.sheet, g.code))
    return groups


def _blocked_row_count(issues: list[RowIssue]) -> int:
    """被阻断的**行数**（不是错误条数）—— 一行可能命中多个维度。"""
    return len({(issue.sheet, issue.row) for issue in issues})


def _truncate(text: str, limit: int = 60) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _sample_answers(rows, limit: int = 10) -> list[dict[str, str]]:
    return [
        {
            "监控日期": r.date,
            "AI大模型": r.model_label,
            "监控问题": _truncate(r.prompt_raw, 40),
            "回答内容": _truncate(r.answer_content),
        }
        for r in rows[:limit]
    ]


def _sample_competitors(rows, limit: int = 10) -> list[dict[str, str]]:
    return [
        {
            "监控日期": r.date,
            "品牌类型": r.brand_type,
            "品牌名称": r.brand,
            "模型": r.model_label,
            "提及次数": str(r.mention_count),
            "平均排名": "-" if r.avg_rank is None else str(r.avg_rank),
        }
        for r in rows[:limit]
    ]


def _sample_citations(rows, limit: int = 10) -> list[dict[str, str]]:
    return [
        {
            "引用日期": r.date,
            "模型": r.model_label,
            "媒体名称": r.media_name,
            "内容标题": _truncate(r.title, 40),
        }
        for r in rows[:limit]
    ]


def _missing_media_hosts(db: Session, citations) -> list[str]:
    """文件里出现、但官方媒体词典里没有的域名（按 host 小写比对）。"""
    hosts = {
        row.media_host.strip().lower()
        for row in citations
        if row.media_host and row.media_host.strip()
    }
    if not hosts:
        return []
    known = {
        item.host.lower() for item in db.execute(select(MediaDictionary)).scalars()
    }
    return sorted(hosts - known)


def preview_import(db: Session, project_id: int, content: bytes,
                   selected_sheets=None) -> ImportPreviewOut:
    """解析 + 校验 + 聚合，**不写库**。"""
    parsed = parse_workbook(content)
    outcome = validate_rows(db, project_id, parsed, selected_sheets)
    project = db.get(Project, project_id)
    if project is None:
        raise ImportConfigError(f"project {project_id} not found")

    blocked = _blocked_row_count(outcome.issues)
    sources = {
        "answers": parsed.answers,
        "competitors": parsed.competitors,
        "citations": parsed.citations,
    }
    accepted = {
        "answers": outcome.answers,
        "competitors": outcome.competitors,
        "citations": outcome.citations,
    }
    samplers = {
        "answers": _sample_answers,
        "competitors": _sample_competitors,
        "citations": _sample_citations,
    }
    sheets: list[SheetPreview] = []
    for key in SHEET_KEYS:
        source = sources[key]
        ok = accepted[key]
        sheets.append(SheetPreview(
            key=key,
            title=_SHEET_TITLES[key],
            total_rows=len(source),
            importable_rows=len(ok),
            blocked_rows=len(source) - len(ok),
            subtasks=len({
                subtask_key(r.date, r.platform_code, r.delivery_mode,
                            r.thinking_mode, normalize_prompt(r.prompt_raw))
                for r in ok
            }),
            sample=samplers[key](source),
        ))

    # 媒体词典覆盖检查：文件里出现但词典没有的域名，其引用在信源偏好里
    # 会落「其他」分类。字典的 category 是非空必填而 xlsx 没有该字段，
    # 所以**不自动补字典**，只在提示里列出缺失清单。
    warnings = list(outcome.warnings)
    missing_hosts = _missing_media_hosts(db, outcome.citations)
    if missing_hosts:
        shown = "、".join(missing_hosts[:10])
        more = " 等" if len(missing_hosts) > 10 else ""
        warnings.append(
            f"文件里有 {len(missing_hosts)} 个域名不在官方媒体词典中，"
            f"这些引用的信源分类会落「其他」：{shown}{more}"
        )

    return ImportPreviewOut(
        project_id=project_id,
        project_name=project.name or "",
        project_brand=(project.brand or "").strip(),
        file_name="",
        sheets=sheets,
        warnings=[ImportWarning(code="normalized", message=w) for w in warnings],
        mapping=list(_MAPPING_ROWS),
        errors=_group_issues(outcome.issues),
        totals=ImportTotals(
            total_rows=len(parsed.answers) + len(parsed.competitors) + len(parsed.citations),
            importable_rows=(
                len(outcome.answers) + len(outcome.competitors) + len(outcome.citations)
            ),
            blocked_rows=blocked,
            tasks=len({r.date for r in outcome.answers}),
            subtasks=len(outcome.subtask_index),
            brand_mentions=len(outcome.competitors),
            citations=len(outcome.citations),
        ),
        missing_sheets=[
            _SHEET_TITLES[key] for key in SHEET_KEYS if key not in parsed.found_sheets
        ],
    )
