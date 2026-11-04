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
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time

import openpyxl
from openpyxl.utils.exceptions import InvalidFileException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.enums import ExtractStatus, RunStatus, RunTrigger
from app.models.import_batch import ImportBatch
from app.models.media_dictionary import MediaDictionary
from app.models.project import (
    BrandMention,
    Project,
    ProjectCompetitor,
    ProjectKeyword,
    ProjectPlatform,
    ProjectPrompt,
)
from app.models.schedule import ScheduleRun
from app.models.task import Subtask, Task
from app.schemas.import_data import (
    DeleteImpact,
    ImportErrorGroup,
    ImportErrorSample,
    ImportPreviewOut,
    ImportResultOut,
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
    # 这两个在向导里没有手机版（wizardConfig.ts: hasMobile: false），
    # mobile 映射回自身 —— 项目里若没有对应的 mobile 行，会被
    # platform_unregistered 挡下。
    "ChatGPT": ("chatgpt", "chatgpt"),
    "chatgpt": ("chatgpt", "chatgpt"),
    "蚂蚁阿福": ("antafu", "antafu"),
    "antafu": ("antafu", "antafu"),
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
    try:
        wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except (zipfile.BadZipFile, InvalidFileException) as exc:
        # .csv / 老式 .xls 改名成 .xlsx 就会走到这里 —— 说人话，别让用户看 500
        raise ValueError(
            "文件不是有效的 xlsx（可能是 csv 或旧版 xls 改了后缀），"
            "请用服务商导出的原始 xlsx 文件"
        ) from exc
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


class ImportBatchCollision(ImportConfigError):
    """批次 id 撞上了别的项目的批次 —— endpoint 层转 409。

    正常情况下算不出来（批次 id 的哈希里含 project_id），只有哈希截断
    碰撞或手工插库才会遇到。绝不能静默复用别人的批次 —— 那会让撤销
    删错数据。
    """


@dataclass(frozen=True)
class ProjectConfig:
    brand: str
    #: 品牌别名（项目 4：brand=伊速达 / alias=玛舒拉沙韦）
    aliases: frozenset[str]
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


BATCH_ID_LEN = 16


def file_hash_for(content: bytes) -> str:
    """文件**内容**的 sha256 —— 同一份数据换个文件名重传仍是同一批次。"""
    return hashlib.sha256(content).hexdigest()


def batch_id_for(project_id: int, file_hash: str) -> str:
    """批次 id = sha256(project_id:file_hash)[:16] —— 内容与项目共同决定。"""
    return hashlib.sha256(
        f"{project_id}:{file_hash}".encode()
    ).hexdigest()[:BATCH_ID_LEN]


def make_task_id(project_id: int, batch_id: str, date_str: str) -> str:
    """导入的 task id —— 批次号编进去，每个批次的数据自成一体。"""
    return f"imp_task_{project_id}_{batch_id}_{date_str.replace('-', '')}"


def subtask_key(date: str, platform_code: str, delivery_mode: str,
                thinking_mode: bool, prompt_norm: str) -> tuple:
    """跨表主键 —— 日期 × 平台 × 终端 × 思考 × 归一化问题。"""
    return (date, platform_code, delivery_mode, thinking_mode, prompt_norm)


def make_subtask_id(project_id: int, batch_id: str, key: tuple) -> str:
    """导入的 subtask id。

    批次号编进去，两个批次覆盖同一日期也不会撞主键。hash 里**必须包含
    delivery_mode** —— chatgpt / 蚂蚁阿福 没有 mobile 变体，
    (chatgpt, web) 与 (chatgpt, mobile) 的 platform_code 相同，
    只有 hash 能区分。
    """
    date, platform_code, delivery_mode, thinking_mode, prompt_norm = key
    digest = hashlib.sha1(
        f"{date}|{platform_code}|{delivery_mode}|{int(thinking_mode)}|{prompt_norm}".encode()
    ).hexdigest()[:8]
    return (
        f"imp_{project_id}_{batch_id}_{date.replace('-', '')}_{platform_code}"
        f"_{'T' if thinking_mode else 'F'}_{digest}"
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
        aliases=frozenset(a for a in (project.aliases or []) if a),
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


def _keyword_allowed(config: ProjectConfig) -> frozenset[str]:
    """文件「核心词」列的合法取值。

    那一列存的是**被监控的产品词**，不等于项目的核心词表 —— 真实样本里
    是「玛舒拉沙韦」（品牌），而项目 4 的 brand 是「伊速达」、核心词才是
    「玛舒拉沙韦」。所以合法集 = 项目核心词 ∪ 品牌名 ∪ 品牌别名。
    """
    allowed = set(config.keywords)
    if config.brand:
        allowed.add(config.brand)
    allowed |= set(config.aliases)
    return frozenset(allowed)


def _common_issues(sheet: str, row_no: int, date: str, platform_code: str,
                   delivery_mode: str, thinking_mode: bool, prompt_raw: str,
                   keyword: str, model_label: str,
                   config: ProjectConfig) -> list[RowIssue]:
    """与品牌无关的五个维度：日期 / 问题 / 平台 / 核心词 / 归一化歧义。"""
    issues: list[RowIssue] = []
    if not date:
        issues.append(_issue(sheet, row_no, "date_missing", "监控日期缺失或无法解析"))
    prompt_norm = normalize_prompt(prompt_raw)
    texts = config.prompt_texts.get(prompt_norm)
    if not texts:
        issues.append(_issue(
            sheet, row_no, "prompt_unregistered",
            "监控问题不在当前项目的问题配置里，"
            "请到项目「编辑」里的『监控问题』补充",
            监控问题=prompt_raw,
        ))
    elif len(texts) > 1:
        issues.append(_issue(
            sheet, row_no, "prompt_ambiguous",
            "该问题在项目配置里有多个候选，无法确定对应哪一条",
            监控问题=prompt_raw,
        ))
    if not platform_code:
        # 模型名根本认不出来 —— 指路「去项目里补」是错的，加了也没用
        issues.append(_issue(
            sheet, row_no, "unknown_model",
            "认不出这个模型名（不在已知模型列表里），请确认文件里的模型名称",
            AI大模型=model_label,
        ))
    elif (platform_code, delivery_mode, thinking_mode) not in config.platform_keys:
        issues.append(_issue(
            sheet, row_no, "platform_unregistered",
            "该模型 / 终端组合不在当前项目的模型配置里，"
            "请到项目「编辑」里的『监控模型』补充",
            AI大模型=model_label or platform_code,
        ))
    # 核心词维度：项目没配核心词就整体跳过；该 sheet 没有「核心词」列
    # （引用媒体）时 keyword 为空串，同样跳过 —— 否则会把整张引用表挡掉。
    if keyword and config.keywords and keyword not in _keyword_allowed(config):
        issues.append(_issue(
            sheet, row_no, "keyword_unregistered",
            "核心词与当前项目的核心词 / 品牌 / 品牌别名都不一致",
            核心词=keyword,
        ))
    return issues


def validate_rows(db: Session, project_id: int, parsed: ParsedWorkbook,
                  selected_sheets=None, batch_id: str = "") -> ValidationOutcome:
    """六维逐行校验 —— 通过的行进 outcome，不通过的进 issues。"""
    config = load_project_config(db, project_id)
    # None = 三张全导（默认）；空列表 = 一张都不导（不能 fallback 成全导）
    selected = set(SHEET_KEYS) if selected_sheets is None else set(selected_sheets)
    issues: list[RowIssue] = []
    warnings: list[str] = []
    resolved_prompts = {
        norm: texts[0] for norm, texts in config.prompt_texts.items() if len(texts) == 1
    }

    # 没勾「问题问答」时，竞品分析 / 引用媒体的行没有可挂载的子任务 ——
    # 错误要说清是「没勾那张 sheet」，而不是「回答记录不存在」。
    answers_selected = "answers" in selected

    # --- 问题问答 ---
    ok_answers: list[AnswerRow] = []
    for row in parsed.answers:
        if "answers" not in selected:
            continue
        row_issues = _common_issues(
            "问题问答", row.row, row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, row.prompt_raw, row.keyword, row.model_label, config,
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

    # 同一 (日期, 模型, 问题) 在文件里出现多次 —— 它们会落到同一个
    # subtask_id，重复插入会撞 UNIQUE 主键、整批 500。每组只留第一条，
    # 并提示用户有几组被折叠了。
    deduped: list[AnswerRow] = []
    seen_keys: set[tuple] = set()
    collapsed = 0
    for row in ok_answers:
        key = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        )
        if key in seen_keys:
            collapsed += 1
            continue
        seen_keys.add(key)
        deduped.append(row)
    if collapsed:
        warnings.append(
            f"文件里有 {collapsed} 行的（日期 / 模型 / 问题）与其它行重复，"
            "导入时每组只保留第一条"
        )
    ok_answers = deduped

    subtask_index: dict[tuple, str] = {}
    for row in ok_answers:
        key = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        )
        subtask_index[key] = make_subtask_id(project_id, batch_id, key)

    # --- 竞品分析 ---
    ok_competitors: list[CompetitorRow] = []
    for row in parsed.competitors:
        if "competitors" not in selected:
            continue
        row_issues = _common_issues(
            "竞品分析", row.row, row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, row.prompt_raw, row.keyword, row.model_label, config,
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
                "该品牌不在当前项目的竞品列表里，"
                "请到项目「编辑」里的『竞品』补充",
                品牌名称=row.brand,
            ))
        key = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        )
        if key not in subtask_index:
            row_issues.append(_issue(
                "竞品分析", row.row,
                "subtask_not_found" if answers_selected else "answers_not_selected",
                "找不到对应的回答记录（日期 / 模型 / 问题组合在「问题问答」里不存在）"
                if answers_selected else
                "需要同时导入「问题问答」—— 竞品分析的数据要挂在对应的回答记录上",
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

    # 竞品分析按 (日期/模型/问题, 品牌) 去重。
    # 落库时 BrandMention 的 (subtask_id, brand) 是 UNIQUE，而生产 session
    # factory 是 autoflush=False —— 同一事务里刚 add 的行下一次 SELECT 查不到，
    # 重复行会 add 两次 → IntegrityError → 整批 500。
    # 同一品牌同时被文件标成「监控品牌」和「竞品品牌」时也走这里折叠，
    # 保留「监控品牌」那条（is_self 语义更准）。
    kept_competitors: list[CompetitorRow] = []
    competitor_index: dict[tuple, int] = {}
    collapsed_competitors = 0
    for row in ok_competitors:
        ckey = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        ) + (row.brand,)
        at = competitor_index.get(ckey)
        if at is None:
            competitor_index[ckey] = len(kept_competitors)
            kept_competitors.append(row)
            continue
        collapsed_competitors += 1
        kept = kept_competitors[at]
        if row.brand_type == "监控品牌" and kept.brand_type != "监控品牌":
            kept_competitors[at] = row
    if collapsed_competitors:
        warnings.append(
            f"文件里有 {collapsed_competitors} 行的（日期 / 模型 / 问题 / 品牌）"
            "与其它行重复，导入时每组只保留第一条"
        )
    ok_competitors = kept_competitors

    # --- 引用媒体 ---
    ok_citations: list[CitationRow] = []
    for row in parsed.citations:
        if "citations" not in selected:
            continue
        row_issues = _common_issues(
            "引用媒体", row.row, row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, row.prompt_raw, "", row.model_label, config,
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
                "引用媒体", row.row,
                "subtask_not_found" if answers_selected else "answers_not_selected",
                "找不到对应的回答记录（日期 / 模型 / 问题组合在「问题问答」里不存在）"
                if answers_selected else
                "需要同时导入「问题问答」—— 引用媒体要挂在对应的回答记录上",
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
    MappingRow(source="监控日期", target="Task.created_local_at · Run.triggered_at",
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

_MAX_DISTINCT = 5000
_MAX_SAMPLES = 20

#: 每种错误码的「代表性取值」字段 —— distinct 列表只取这一个键的值，
#: 否则 subtask_not_found 的日期 / 模型名 / 问题会混在同一个列表里。
_DISTINCT_KEY: dict[str, str] = {
    "brand_mismatch": "品牌名称",
    "competitor_unregistered": "品牌名称",
    "prompt_unregistered": "监控问题",
    "prompt_ambiguous": "监控问题",
    "platform_unregistered": "AI大模型",
    "unknown_model": "AI大模型",
    "keyword_unregistered": "核心词",
    "media_name_blank": "内容链接",
    "subtask_not_found": "监控问题",
    "answers_not_selected": "监控问题",
}


def _group_issues(issues: list[RowIssue]) -> list[ImportErrorGroup]:
    """按 (sheet, code) 聚合错误 —— 2190 行同因错误只带 20 条样本。"""
    buckets: dict[tuple[str, str], list[RowIssue]] = {}
    for issue in issues:
        buckets.setdefault((issue.sheet, issue.code), []).append(issue)
    groups: list[ImportErrorGroup] = []
    for (sheet, code), items in buckets.items():
        primary = _DISTINCT_KEY.get(code)
        distinct = sorted({
            item.context.get(primary, "")
            for item in items
            if item.context.get(primary, "")
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
    file_hash = file_hash_for(content)
    batch_id = batch_id_for(project_id, file_hash)
    outcome = validate_rows(db, project_id, parsed, selected_sheets, batch_id)
    project = db.get(Project, project_id)
    if project is None:
        raise ImportConfigError(f"project {project_id} not found")

    blocked = _blocked_row_count(outcome.issues)
    # 每张 sheet 的阻断行数也从 issues 统计 —— 「被折叠的重复行」不是阻断，
    # 否则同一屏上「2 行 · 可导入 1 · 阻断 1」和绿色的「通过」互相打架。
    blocked_pairs = {(i.sheet, i.row) for i in outcome.issues}
    blocked_by_sheet: dict[str, int] = {}
    for sheet_name, _row_no in blocked_pairs:
        blocked_by_sheet[sheet_name] = blocked_by_sheet.get(sheet_name, 0) + 1
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
    chosen = set(SHEET_KEYS) if selected_sheets is None else set(selected_sheets)
    sheets: list[SheetPreview] = []
    for key in SHEET_KEYS:
        source = sources[key]
        ok = accepted[key]
        is_selected = key in chosen
        sheets.append(SheetPreview(
            key=key,
            title=_SHEET_TITLES[key],
            total_rows=len(source),
            importable_rows=len(ok),
            # 未勾选的 sheet 没参与校验 —— 「没选」不是「不匹配」，
            # 别把它算成阻断行。已勾选的 sheet 阻断数按 issues 去重统计
            # （同一行命中多个维度只算一行）。
            blocked_rows=blocked_by_sheet.get(_SHEET_TITLES[key], 0) if is_selected else 0,
            selected=is_selected,
            subtasks=len({
                subtask_key(r.date, r.platform_code, r.delivery_mode,
                            r.thinking_mode, normalize_prompt(r.prompt_raw))
                for r in ok
            }),
            sample=samplers[key](source),
        ))

    warnings = list(outcome.warnings)

    # 与其它导入批次的数据重叠：新旧两个批次覆盖同一批日期 → 数据会有两份。
    # 查的是**实际落库的 task**（import_batch_id 非空），不是批次的 dates ——
    # 后者记的是「解析到的日期」，一个 0 行写入的批次会让这里误报重叠。
    imported_dates = {r.date for r in outcome.answers}
    if imported_dates:
        existing_import_days = db.execute(
            select(Task.created_local_at).where(
                Task.project_id == project_id,
                Task.import_batch_id.isnot(None),
                Task.import_batch_id != batch_id,
            )
        ).scalars().all()
        overlap = sorted({
            d.strftime("%Y-%m-%d")
            for d in existing_import_days
            if isinstance(d, datetime) and d.strftime("%Y-%m-%d") in imported_dates
        })
        if overlap:
            warnings.append(
                f"这些日期已有其它导入批次的数据（{overlap[0]} ~ {overlap[-1]}，"
                f"共 {len(overlap)} 天）：导入后同一批数据会有两份，"
                "可在「导入历史」里撤销其中一次"
            )

    # 与平台自身调度数据重叠：导入会为同一日期建一套平行的
    # Task/Subtask/BrandMention，统计会翻倍 —— 明确告诉用户。
    imported_dates = {r.date for r in outcome.answers}
    if imported_dates:
        existing = db.execute(
            select(Task.created_local_at).where(
                Task.project_id == project_id,
                Task.import_batch_id.is_(None),
            )
        ).scalars().all()
        overlap = sorted({
            d.strftime("%Y-%m-%d")
            for d in existing
            if isinstance(d, datetime) and d.strftime("%Y-%m-%d") in imported_dates
        })
        if overlap:
            warnings.append(
                f"这些日期平台已有监控数据（{overlap[0]} ~ {overlap[-1]}，"
                f"共 {len(overlap)} 天）：导入后问题提及分析等页面的统计会包含两份数据"
            )

    # 媒体词典覆盖检查：文件里出现但词典没有的域名，其引用在信源偏好里
    # 会落「其他」分类。字典的 category 是非空必填而 xlsx 没有该字段，
    # 所以**不自动补字典**，只在提示里列出缺失清单。
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


# --------------------------------------------------------------------------
# 落库
# --------------------------------------------------------------------------


def _compute_totals(parsed: ParsedWorkbook, outcome: ValidationOutcome) -> dict:
    """批次的行数统计 —— 与 ImportTotals 同结构。"""
    return {
        "total_rows": len(parsed.answers) + len(parsed.competitors) + len(parsed.citations),
        "importable_rows": (
            len(outcome.answers) + len(outcome.competitors) + len(outcome.citations)
        ),
        "blocked_rows": _blocked_row_count(outcome.issues),
        "tasks": len({r.date for r in outcome.answers}),
        "subtasks": len(outcome.subtask_index),
        "brand_mentions": len(outcome.competitors),
        "citations": len(outcome.citations),
    }


def _batch_status(totals: dict) -> str:
    """success / partial / failed。"""
    if not totals.get("importable_rows"):
        return "failed"
    if totals.get("blocked_rows"):
        return "partial"
    return "success"


def _upsert_batch(db: Session, *, batch_id: str, project_id: int, customer_id: int,
                  file_name: str, file_hash: str, file_size: int,
                  selected_sheets: list[str], totals: dict, errors: list[dict],
                  warnings: list[str], dates: list[str], created_by: str) -> ImportBatch:
    """取或建批次行。同一批次重复导入 → attempts +1，其余字段刷新。"""
    batch = db.get(ImportBatch, batch_id)
    if batch is not None and batch.project_id != project_id:
        # 批次 id 碰撞（不同项目算出同一个 id）—— 绝不能静默复用别人的批次
        raise ImportBatchCollision(
            f"batch {batch_id} belongs to another project"
        )
    if batch is None:
        batch = ImportBatch(
            id=batch_id,
            project_id=project_id,
            customer_id=customer_id,
            file_name=file_name or "未命名.xlsx",
            file_hash=file_hash,
            file_size=file_size,
            status="failed",
            selected_sheets=list(selected_sheets),
            totals={},
            errors=[],
            warnings=[],
            dates=[],
            attempts=0,
            created_by=created_by,
        )
        db.add(batch)
    batch.attempts += 1
    batch.file_name = file_name or batch.file_name
    batch.file_size = file_size
    batch.selected_sheets = list(selected_sheets)
    batch.totals = dict(totals)
    batch.errors = list(errors)
    batch.warnings = list(warnings)
    batch.dates = list(dates)
    batch.status = _batch_status(totals)
    db.flush()
    return batch


def _day_start(date_str: str) -> datetime:
    """监控日期 00:00:00 —— 平台所有分析窗口都按 created_at 过滤，
    历史数据必须回填到它自己的监控日，否则全堆在导入当天。"""
    return datetime.combine(date.fromisoformat(date_str), time.min)


def apply_import(db: Session, project_id: int, content: bytes,
                 selected_sheets=None, file_name: str = "",
                 created_by: str = "") -> ImportResultOut:
    """解析 + 校验 + 落库（单事务），并记录 / 更新导入批次。

    批次 = 「一份文件内容」×「一个项目」：同一份文件重复导入命中同一批次，
    upsert 同一批行（不产生重复数据），批次的 status / totals / errors /
    attempts / updated_at 刷新。

    与 ``extraction.py`` 的「SUCCESS sticky」契约**不同** —— 这里以文件
    为权威源，重传修正版文件必须能改写已填的重字段。
    """
    parsed = parse_workbook(content)
    file_hash = file_hash_for(content)
    batch_id = batch_id_for(project_id, file_hash)
    outcome = validate_rows(db, project_id, parsed, selected_sheets, batch_id)
    project = db.get(Project, project_id)
    if project is None:
        raise ImportConfigError(f"project {project_id} not found")

    try:
        stats = _write_rows(db, project_id, project, outcome, batch_id)
        _upsert_batch(
            db,
            batch_id=batch_id,
            project_id=project_id,
            customer_id=project.customer_id,
            file_name=file_name,
            file_hash=file_hash,
            file_size=len(content),
            selected_sheets=(
                sorted(selected_sheets)
                if selected_sheets is not None
                else list(SHEET_KEYS)
            ),
            totals=_compute_totals(parsed, outcome),
            errors=[g.model_dump() for g in _group_issues(outcome.issues)],
            warnings=list(outcome.warnings),
            dates=sorted({r.date for r in parsed.answers}),
            created_by=created_by,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    return ImportResultOut(
        batch_id=batch_id,
        tasks_created=stats["tasks_created"],
        tasks_updated=stats["tasks_updated"],
        subtasks_created=stats["subtasks_created"],
        subtasks_updated=stats["subtasks_updated"],
        brand_mentions_written=stats["brand_mentions_written"],
        brand_mentions_updated=stats["brand_mentions_updated"],
        citations_written=stats["citations_written"],
        runs_written=stats["runs_written"],
        skipped_rows=_blocked_row_count(outcome.issues),
        errors=_group_issues(outcome.issues),
    )


def _write_rows(db: Session, project_id: int, project, outcome,
                batch_id: str) -> dict[str, int]:
    # 项目填了核心卖点 → is_correct 要靠 LLM 判断，导入不跑（留 NULL）；
    # 没填 → 按抽取流水线的短路规则置 True。
    semantic = project.semantic_json if isinstance(project.semantic_json, dict) else {}
    raw_points = semantic.get("selling_points")
    selling_points = [p for p in raw_points if str(p).strip()] if isinstance(raw_points, list) else []
    stats = {
        "tasks_created": 0, "tasks_updated": 0,
        "subtasks_created": 0, "subtasks_updated": 0,
        "brand_mentions_written": 0, "brand_mentions_updated": 0,
        "citations_written": 0, "runs_written": 0,
    }

    by_date: dict[str, list] = defaultdict(list)
    for row in outcome.answers:
        by_date[row.date].append(row)

    # --- run 行先建 ---
    # Task 要回填 schedule_run_id（信源偏好按它把引用归到执行期），
    # 所以 run 必须先落库拿到 id。
    runs: dict[str, ScheduleRun] = {}
    for day in sorted(by_date):
        cooldown = f"import:{project_id}:{batch_id}:{day}"
        run = db.scalar(
            select(ScheduleRun).where(ScheduleRun.cooldown_key == cooldown)
        )
        modes = {"think" if r.thinking_mode else "fast" for r in by_date[day]}
        mode = modes.pop() if len(modes) == 1 else ""
        if run is None:
            run = ScheduleRun(
                project_id=project_id,
                slot_index=0,
                trigger_type=RunTrigger.MANUAL,
                mode=mode,
                cooldown_key=cooldown,
                status=RunStatus.SUCCESS,
                triggered_at=_day_start(day),
                started_at=_day_start(day),
                finished_at=_day_start(day),
            )
            db.add(run)
            stats["runs_written"] += 1
        run.task_id = make_task_id(project_id, batch_id, day)
        run.status = RunStatus.SUCCESS
        runs[day] = run
    db.flush()

    # --- task + subtask ---
    for day in sorted(by_date):
        rows = by_date[day]
        task_id = make_task_id(project_id, batch_id, day)
        task = db.get(Task, task_id)
        if task is None:
            task = Task(
                task_id=task_id,
                status="completed",
                project_id=project_id,
                customer_id=project.customer_id,
                created_local_at=_day_start(day),
            )
            db.add(task)
            stats["tasks_created"] += 1
        else:
            stats["tasks_updated"] += 1
        platforms: dict[tuple[str, bool], None] = {}
        for row in rows:
            platforms[(row.platform_code, row.thinking_mode)] = None
        # 用**项目配置里的 prompt 原文**，跟 subtask.prompt 保持一致
        # （文件里的原文带 / 不带编号前缀，跟项目配置不一定一样）。
        task.prompts_json = sorted({
            outcome.resolved_prompts[normalize_prompt(r.prompt_raw)] for r in rows
        })
        task.platforms_json = [
            {
                "platform": code,
                "mode": "reasoning_search" if thinking else "search",
                "screenshot": False,
                "thinkingMode": thinking,
            }
            for (code, thinking) in sorted(platforms)
        ]
        task.total_items = len(rows)
        task.completed_items = len(rows)
        task.failed_items = 0
        task.schedule_run_id = runs[day].id
        task.import_batch_id = batch_id
        db.flush()

        for row in rows:
            key = subtask_key(
                row.date, row.platform_code, row.delivery_mode,
                row.thinking_mode, normalize_prompt(row.prompt_raw),
            )
            subtask_id = outcome.subtask_index[key]
            subtask = db.get(Subtask, subtask_id)
            if subtask is None:
                subtask = Subtask(subtask_id=subtask_id, task_id=task_id)
                db.add(subtask)
                stats["subtasks_created"] += 1
            else:
                stats["subtasks_updated"] += 1
            subtask.platform = row.platform_code
            subtask.mode = "reasoning_search" if row.thinking_mode else "search"
            subtask.prompt = outcome.resolved_prompts[normalize_prompt(row.prompt_raw)]
            subtask.status = "completed"
            subtask.time = day
            subtask.answer_content = row.answer_content
            subtask.page_screenshot = row.screenshot or None
            # geo_subtasks 没有 created_at 列；信源偏好的时间窗口走
            # Task.created_local_at（source_preferences.py join Task 后过滤）。
            # updated_at 不回填 —— 该列带 onupdate=now_local，任何 UPDATE 都会
            # 盖成当前时刻，它的语义本来就是「最后写入时间」。

    db.flush()

    # --- brand_mentions ---
    for row in outcome.competitors:
        key = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        )
        subtask_id = outcome.subtask_index[key]
        subtask = db.get(Subtask, subtask_id)
        if subtask is None:
            continue
        mention = db.scalar(
            select(BrandMention).where(
                BrandMention.subtask_id == subtask_id,
                BrandMention.brand == row.brand,
            )
        )
        if mention is None:
            mention = BrandMention(
                subtask_id=subtask_id,
                task_id=subtask.task_id,
                project_id=project_id,
                customer_id=project.customer_id,
                prompt=outcome.resolved_prompts[normalize_prompt(row.prompt_raw)],
                platform=row.platform_code,
                brand=row.brand,
                is_self=(row.brand_type == "监控品牌"),
                thinking_mode=row.thinking_mode,
                delivery_mode=row.delivery_mode,
                created_at=_day_start(row.date),
            )
            db.add(mention)
            stats["brand_mentions_written"] += 1
        else:
            stats["brand_mentions_updated"] += 1
        # is_correct 对齐 extraction.py 的短路规则：项目没填核心卖点时，
        # 「没有基准就谈不上错」→ True。留 NULL 会进 KPI 分母不進分子，
        # 把工作台的正确率摊薄。
        if not selling_points:
            mention.is_correct = True
        mention.is_mention = 1 if row.mention_count and row.mention_count > 0 else 0
        mention.rank_position = row.avg_rank
        mention.sentiment = row.sentiment
        mention.is_recommended = bool(
            row.avg_rank is not None and 1 <= row.avg_rank <= 5
        )
        mention.extract_status = (
            ExtractStatus.SUCCESS if row.avg_rank is not None else ExtractStatus.SKIPPED
        )
        mention.extract_error = None

    db.flush()

    # --- 引用媒体（按 subtask 合并进 reference_list_json，url 去重） ---
    refs_by_subtask: dict[str, list[dict]] = defaultdict(list)
    seen_urls: dict[str, set[str]] = defaultdict(set)
    for row in outcome.citations:
        key = subtask_key(
            row.date, row.platform_code, row.delivery_mode,
            row.thinking_mode, normalize_prompt(row.prompt_raw),
        )
        subtask_id = outcome.subtask_index[key]
        if row.url in seen_urls[subtask_id]:
            continue
        seen_urls[subtask_id].add(row.url)
        refs_by_subtask[subtask_id].append({
            "url": row.url,
            "site": row.media_name,
            "title": row.title,
        })
    for subtask_id, new_refs in refs_by_subtask.items():
        subtask = db.get(Subtask, subtask_id)
        if subtask is None:
            continue
        existing = list(subtask.reference_list_json or [])
        existing_urls = {
            item.get("url") for item in existing if isinstance(item, dict)
        }
        merged = existing + [r for r in new_refs if r["url"] not in existing_urls]
        # JSON 列必须整体重新赋值，不能原地 mutate。
        subtask.reference_list_json = merged
        # 只记**实际新增**的引用 —— 重复导入时 url 已在库里，不能虚报。
        stats["citations_written"] += len(merged) - len(existing)

    db.flush()

    db.flush()
    return stats


# --------------------------------------------------------------------------
# 撤销导入
# --------------------------------------------------------------------------


def _get_batch(db: Session, project_id: int, batch_id: str) -> ImportBatch:
    batch = db.get(ImportBatch, batch_id)
    if batch is None or batch.project_id != project_id:
        raise ImportConfigError(f"import batch {batch_id} not found")
    return batch


def _batch_task_ids(db: Session, batch_id: str) -> list[str]:
    return list(db.execute(
        select(Task.task_id).where(Task.import_batch_id == batch_id)
    ).scalars())


def _batch_subtask_ids(db: Session, task_ids: list[str]) -> list[str]:
    if not task_ids:
        return []
    return list(db.execute(
        select(Subtask.subtask_id).where(Subtask.task_id.in_(task_ids))
    ).scalars())


def _chunks(items: list[str], size: int = 500):
    """分片 —— IN (...) 的参数太多会撞 MySQL 的 max_allowed_packet。"""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def compute_delete_impact(db: Session, project_id: int, batch_id: str) -> DeleteImpact:
    """撤销这个批次会少掉多少数据 —— 撤销前先算给用户看。"""
    _get_batch(db, project_id, batch_id)
    task_ids = _batch_task_ids(db, batch_id)
    subtask_ids = _batch_subtask_ids(db, task_ids)
    mentions = 0
    if subtask_ids:
        mentions = db.execute(
            select(func.count()).select_from(BrandMention).where(
                BrandMention.subtask_id.in_(subtask_ids)
            )
        ).scalar() or 0
    runs = db.execute(
        select(func.count()).select_from(ScheduleRun).where(
            ScheduleRun.cooldown_key.like(f"import:{project_id}:{batch_id}:%")
        )
    ).scalar() or 0
    return DeleteImpact(
        tasks=len(task_ids),
        subtasks=len(subtask_ids),
        brand_mentions=int(mentions),
        runs=int(runs),
    )


def undo_import(db: Session, project_id: int, batch_id: str) -> DeleteImpact:
    """撤销一次导入 —— 删掉它写入的全部行。

    跨表关联列都是普通列、没有 ForeignKey，所以删除要手工按顺序做：
    task → subtask → brand_mention → run → 批次行。
    **平台自身抽取流水线写的 brand_mentions 不受影响** —— 删除只限定在
    本批次的 subtask 集合内。
    """
    _get_batch(db, project_id, batch_id)
    impact = compute_delete_impact(db, project_id, batch_id)
    task_ids = _batch_task_ids(db, batch_id)
    subtask_ids = _batch_subtask_ids(db, task_ids)

    for chunk in _chunks(subtask_ids):
        db.execute(delete(BrandMention).where(BrandMention.subtask_id.in_(chunk)))
    for chunk in _chunks(subtask_ids):
        db.execute(delete(Subtask).where(Subtask.subtask_id.in_(chunk)))
    for chunk in _chunks(task_ids):
        db.execute(delete(Task).where(Task.task_id.in_(chunk)))
    db.execute(delete(ScheduleRun).where(
        ScheduleRun.cooldown_key.like(f"import:{project_id}:{batch_id}:%")
    ))
    db.delete(db.get(ImportBatch, batch_id))
    db.commit()
    return impact
