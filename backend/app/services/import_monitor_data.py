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

import io
import re
from dataclasses import dataclass, field

import openpyxl

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
