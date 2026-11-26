"""把 :class:`ExportData` 写成 xlsx —— 结构照搬 ``docs/download/数据导出提及率样例.xlsx``。

产出的工作簿:
- **「提及率」** —— 行 = 问题,列 = 平台(按平台名归并),单元格三态
  「已提及」/「未提及」/「-」;表格下方按日期分块,每块三行
  「未提及 / 已提及 / 提及率」+ 一列「合计」。
- **每个平台一个明细 sheet** —— 两行表头(品牌名称 / 问题核心词 / 问题 /
  日期 纵向合并两行,「答案1」横向合并四列,下面是 内容 / 截图链接 / 排名 /
  监控词排名),每行一次回答。

为什么用 xlsxwriter 而不是 openpyxl:openpyxl 的 ``write_only`` 模式不支持
``merge_cells``,而上面这套表头全靠纵向合并;xlsxwriter 的
``constant_memory`` 模式也不行(实测它下 ``merge_range`` 跨行会把内部行
指针推到合并区末行,导致合并区前面那些行的写入被静默丢弃),所以用普通
模式 —— 内存峰值 ≈ 答案文本总量 + 每单元格约 100 字节开销,worker 是独立
进程,pm2 内存上限给到 2G。
"""

from __future__ import annotations

import contextlib
import os
from pathlib import Path

import xlsxwriter

from app.services.export_query import (
    CELL_MAX_CHARS,
    ExportData,
    PlatformGroup,
    StatBlock,
)

#: 表头两行的底色 —— 第一行深,第二行浅一档。
_HEADER_BG = "#2F3A4F"
_SUBHEADER_BG = "#DCE3ED"

_MENTIONED_COLOR = "#237804"
_DASH_COLOR = "#BFBFBF"

#: 超长单元格截断后补的标记。
_TRUNCATE_SUFFIX = "…(已截断)"


def _truncate(text: str) -> str:
    """超 Excel 单元格上限就截断并标注 —— 不让一条超长回答炸掉整个导出。"""
    if len(text) <= CELL_MAX_CHARS:
        return text
    return text[: CELL_MAX_CHARS - len(_TRUNCATE_SUFFIX)] + _TRUNCATE_SUFFIX


def _write_mention_rate_sheet(book, data: ExportData) -> None:
    from app.services.platform_labels import platform_color_for_code

    ws = book.add_worksheet("提及率")
    ws.set_column(0, 0, 6)
    ws.set_column(1, 1, 46)
    ws.set_column(2, 1 + len(data.platforms), 12)

    header = book.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": _HEADER_BG,
            "align": "center",
            "valign": "vcenter",
            "border": 1,
            "border_color": "#D9D9D9",
        }
    )
    mentioned_fmt = book.add_format(
        {"align": "center", "font_color": _MENTIONED_COLOR}
    )
    plain_fmt = book.add_format({"align": "center"})
    dash_fmt = book.add_format({"align": "center", "font_color": _DASH_COLOR})
    text_fmt = book.add_format({"valign": "top", "text_wrap": True})

    # 表头:序号 | 问题 | <平台…>
    ws.write(0, 0, "序号", header)
    ws.write(0, 1, "问题", header)
    for idx, group in enumerate(data.platforms):
        color = platform_color_for_code(group.codes[0] if group.codes else None)
        col_fmt = book.add_format(
            {
                "bold": True,
                "font_color": "#FFFFFF",
                "bg_color": color,
                "align": "center",
                "valign": "vcenter",
                "border": 1,
                "border_color": "#D9D9D9",
            }
        )
        ws.write(0, 2 + idx, group.label, col_fmt)

    # 问题行
    for row_idx, prompt in enumerate(data.prompts, start=1):
        ws.write_number(row_idx, 0, row_idx, plain_fmt)
        ws.write(row_idx, 1, _truncate(prompt.text), text_fmt)
        for col_idx, group in enumerate(data.platforms):
            value = data.cells.get((prompt.id, group.label), "-")
            fmt = (
                mentioned_fmt
                if value == "已提及"
                else dash_fmt
                if value == "-"
                else plain_fmt
            )
            ws.write(row_idx, 2 + col_idx, value, fmt)

    # 统计块:每个日期一块,块与块之间空一行
    row = len(data.prompts) + 2
    for block in data.stat_blocks:
        row = _write_stat_block(book, ws, block, data, row, header, plain_fmt)

    ws.freeze_panes(1, 2)


def _write_stat_block(
    book,
    ws,
    block: StatBlock,
    data: ExportData,
    row: int,
    header,
    plain_fmt,
) -> int:
    """写一个日期的统计块,返回下一个可用行号。

    块结构(4 行):表头行 + 未提及 / 已提及 / 提及率 三行。日期值纵向合并
    那三行(样例的 ``A52:A54``)。合计列 = 横向求和。
    """
    total_col = 2 + len(data.platforms)
    labels = [g.label for g in data.platforms]

    ws.write(row, 0, "日期", header)
    ws.write(row, 1, "AI平台渗透率", header)
    for idx, label in enumerate(labels):
        ws.write(row, 2 + idx, label, header)
    ws.write(row, total_col, "合计", header)
    row += 1

    # 日期纵向合并三行 —— 先写合并区,再写该块的其余单元格。
    ws.merge_range(
        row, 0, row + 2, 0, block.day.isoformat(), plain_fmt
    )

    # 未提及行
    counts = block.not_mentioned
    ws.write(row, 1, "未提及", plain_fmt)
    total = 0
    for idx, label in enumerate(labels):
        value = counts.get(label, 0)
        total += value
        ws.write_number(row, 2 + idx, value, plain_fmt)
    ws.write_number(row, total_col, total, plain_fmt)
    row += 1

    # 已提及行
    counts = block.mentioned
    ws.write(row, 1, "已提及", plain_fmt)
    total = 0
    for idx, label in enumerate(labels):
        value = counts.get(label, 0)
        total += value
        ws.write_number(row, 2 + idx, value, plain_fmt)
    ws.write_number(row, total_col, total, plain_fmt)
    mentioned_total = total
    row += 1

    # 提及率行
    ws.write(row, 1, "提及率", plain_fmt)
    for idx, label in enumerate(labels):
        m = block.mentioned.get(label, 0)
        n = block.not_mentioned.get(label, 0)
        denom = m + n
        ws.write_number(row, 2 + idx, (m / denom) if denom else 0.0, plain_fmt)
    grand = mentioned_total + sum(block.not_mentioned.values())
    ws.write_number(
        row, total_col, (mentioned_total / grand) if grand else 0.0, plain_fmt
    )
    row += 1

    return row + 1  # 块之间空一行


def _write_detail_sheet(
    book, data: ExportData, group: PlatformGroup, rows
) -> None:
    ws = book.add_worksheet(group.label)
    ws.set_column(0, 0, 14)
    ws.set_column(1, 1, 14)
    ws.set_column(2, 2, 40)
    ws.set_column(3, 3, 12)
    ws.set_column(4, 4, 80)
    ws.set_column(5, 5, 30)
    ws.set_column(6, 6, 22)
    ws.set_column(7, 7, 12)
    ws.set_column(8, 8, 4)
    ws.set_column(9, 9, 16)

    header = book.add_format(
        {
            "bold": True,
            "font_color": "#FFFFFF",
            "bg_color": _HEADER_BG,
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
            "border": 1,
            "border_color": "#D9D9D9",
        }
    )
    subheader = book.add_format(
        {
            "bold": True,
            "bg_color": _SUBHEADER_BG,
            "align": "center",
            "valign": "vcenter",
            "text_wrap": True,
            "border": 1,
            "border_color": "#D9D9D9",
        }
    )
    body = book.add_format({"valign": "top", "text_wrap": True})

    # 两行表头:A/B/C/D 纵向合并两行;E:H 横向合并成「答案1」。
    ws.merge_range(0, 0, 1, 0, "品牌名称", header)
    ws.merge_range(0, 1, 1, 1, "问题核心词", header)
    ws.merge_range(0, 2, 1, 2, "问题", header)
    ws.merge_range(0, 3, 1, 3, "日期", header)
    ws.merge_range(0, 4, 0, 7, "答案1", header)
    ws.write(1, 4, "内容", subheader)
    ws.write(1, 5, "截图链接", subheader)
    ws.write(1, 6, "排名", subheader)
    ws.write(1, 7, "监控词排名", subheader)
    ws.merge_range(0, 9, 1, 9, "反向监测", header)

    for row_idx, row in enumerate(rows, start=2):
        ws.write(row_idx, 0, data.brand, body)
        ws.write(row_idx, 1, row.keyword, body)
        ws.write(row_idx, 2, _truncate(row.prompt_text), body)
        ws.write(row_idx, 3, row.day.isoformat(), body)
        ws.write(row_idx, 4, _truncate(row.answer_content), body)
        ws.write(row_idx, 5, row.share_url, body)
        ws.write(row_idx, 6, "\n".join(row.rankings), body)
        ws.write(row_idx, 7, "-", body)
        ws.write(row_idx, 9, "无匹配内容", body)

    ws.freeze_panes(2, 0)


def write_export_workbook(data: ExportData, path: Path) -> None:
    """把 ``data`` 写成 xlsx 落到 ``path``。

    先写 ``path.with_suffix('.xlsx.tmp')`` 再 ``os.replace`` 原子改名 ——
    下载端点可能正在读同一个文件,不能让它读到半个 workbook。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    book = xlsxwriter.Workbook(tmp)
    try:
        _write_mention_rate_sheet(book, data)
        for group in data.platforms:
            rows = data.details.get(group.label) or ()
            if not rows:
                continue
            _write_detail_sheet(book, data, group, rows)
    except BaseException:
        # close() 在 workbook 已损坏时可能再抛一次 —— 吞掉它,让原始异常
        # 往上走,别被 close 的异常盖住。
        with contextlib.suppress(Exception):
            book.close()
        tmp.unlink(missing_ok=True)
        raise
    book.close()
    os.replace(tmp, path)
