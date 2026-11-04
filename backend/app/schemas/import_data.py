"""外部监控数据导入 API 的响应模型。

- ``ImportPreviewOut`` —— POST /preview 返回
- ``ImportResultOut`` —— POST /apply 返回

错误用「按 code 聚合」的结构（``ImportErrorGroup``）而不是逐行列表：
样本文件里「未登记竞品」一条就涉及 2190 行，逐行返回会让响应体爆到
几百 KB，聚合后只带 20 条明细样本 + 去重后的关键值清单。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class DeleteImpact(BaseModel):
    """撤销一次导入会少掉多少数据 —— 撤销前先算给用户看。"""

    tasks: int = 0
    subtasks: int = 0
    brand_mentions: int = 0
    runs: int = 0


class ImportErrorSample(BaseModel):
    """单行明细样本。"""

    row: int
    context: dict[str, str] = Field(default_factory=dict)


class ImportErrorGroup(BaseModel):
    """同一 (sheet, code) 的错误聚合。"""

    sheet: str
    code: str
    message: str
    row_count: int
    #: 去重后的关键值（如未登记的竞品名），最多 500 条
    distinct: list[str] = Field(default_factory=list)
    #: 前 20 条明细
    samples: list[ImportErrorSample] = Field(default_factory=list)


class ImportWarning(BaseModel):
    """归一化成功但与配置有差异的提示（不阻断导入）。"""

    code: str
    message: str


class MappingRow(BaseModel):
    """对账条的一行：外部列 -> 平台内部字段。"""

    source: str
    target: str
    note: str = ""


class SheetPreview(BaseModel):
    key: str
    title: str
    total_rows: int
    importable_rows: int
    blocked_rows: int
    subtasks: int
    #: 这一张是否被勾选导入 —— 未勾选的 sheet 不参与校验，
    #: 不该报「阻断」（那是「没选」不是「不匹配」）。
    selected: bool = True
    sample: list[dict[str, str]] = Field(default_factory=list)


class ImportTotals(BaseModel):
    total_rows: int
    importable_rows: int
    blocked_rows: int
    tasks: int
    subtasks: int
    brand_mentions: int
    citations: int


class ImportPreviewOut(BaseModel):
    project_id: int
    project_name: str
    project_brand: str
    file_name: str
    sheets: list[SheetPreview]
    warnings: list[ImportWarning]
    mapping: list[MappingRow]
    errors: list[ImportErrorGroup]
    totals: ImportTotals
    missing_sheets: list[str] = Field(default_factory=list)


class ImportResultOut(BaseModel):
    #: 本次导入所属批次（内容哈希 × 项目）—— 前端拿它跳到导入历史
    batch_id: str = ""
    tasks_created: int
    tasks_updated: int
    subtasks_created: int
    subtasks_updated: int
    brand_mentions_written: int
    brand_mentions_updated: int
    citations_written: int
    runs_written: int
    skipped_rows: int
    errors: list[ImportErrorGroup] = Field(default_factory=list)
