# 竞品分析整页重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 按 `docs/更新版UI/index.html #tab-competitor` 重写竞品分析页:3 个二级 tab(全部竞品 / 趋势对比 / 差异化分析)+ 6 个 panel,新增后端字段(top1 / 情感三档 / 环比 / diff 三件套),并把后端计算从 `api/projects.py` 抽到新建的 `services/competitor_analysis.py`。

**Architecture:**
- 后端:把竞品分析计算整体迁出 `api/projects.py`,放进 `services/competitor_analysis.py`(`按页面分开`);endpoint 缩为薄壳。Schema 在 `app/schemas/project.py` 扩展,不动数据库(无需 alembic)。
- 前端:`CompetitorAnalysisTab` 整页重写,3 个二级 tab + 6 个 panel。表格 8 列;SVG 折线 / 柱状 / 散点三套图表纯手写,沿用现有 TrendChart 风格。不引新依赖。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2 + pytest;React 18 + Vite + Ant Design 5 + 纯 SVG 图表(无 chart lib)。

---

## File Structure

**新建文件:**
- `backend/app/services/competitor_analysis.py` — 整页计算服务
- `backend/tests/test_competitor_analysis_api.py` — endpoint 集成测试(此前无测试覆盖)

**修改文件:**
- `backend/app/schemas/project.py` — 扩 `CompetitorKpi`(+7 字段)+ 新 `QuadrantPoint` / `ModelDiff` + 扩 `CompetitorAnalysisOut`(加 diff 三件套 + previous_window,删 `concern_tags`)
- `backend/app/api/projects.py` — 删 `_resolve_competitor_window` / `_COMPETITOR_LINE_COLORS` / `competitor_analysis()` 函数体,endpoint 改薄壳
- `frontend/src/api/projects.ts` — 扩 `CompetitorKpi` + 新 `QuadrantPoint` / `ModelDiff` + 扩 `CompetitorAnalysisOut` + 删 `ConcernTag*`
- `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx` — 整页重写

**前端组件拆分(同文件):**
- `<CompetitorAnalysisTab>` — 根(数据加载 + Tabs 容器)
- `<AllCompetitorsPane>` — Tab "all"
- `<TrendFullPane>` — Tab "trend"
- `<DiffPane>` — Tab "diff"
- `<OverviewTable>` — 8 列概览
- `<BarChart>` — 分组柱状图(generic)
- `<QuadrantChart>` — 散点图
- 复用现有 `<Sparkline>` + `<TrendChart>`

---

## Task 1: 后端 Schema — 扩 CompetitorKpi 加 7 字段(TDD)

**Files:**
- Modify: `backend/app/schemas/project.py:714-743`(CompetitorKpi)
- Test: `backend/tests/test_competitor_analysis_api.py`(新建,先放 placeholder)

- [ ] **Step 1: 创建测试文件 placeholder**

新建 `backend/tests/test_competitor_analysis_api.py`,从 `test_questions_analytics.py` 复制 in-memory SQLite + ASGITransport fixture + `token` / `h` fixtures(后几个 task 会用)。文件头写:

```python
"""Tests for GET /api/projects/{id}/competitor-analysis endpoint."""
```

`grep -n "token\|h = " test_questions_analytics.py` 找到 fixture 定义,copy 过来(约 30 行)。

- [ ] **Step 2: 写新字段存在的失败断言**

在 `test_competitor_analysis_api.py` 加一个 placeholder test 函数(占位,等 Task 10 一起实跑):

```python
def test_competitor_kpi_has_new_fields():
    from app.schemas.project import CompetitorKpi
    fields = CompetitorKpi.model_fields
    for name in ("top1_rate", "sentiment_positive", "sentiment_neutral",
                 "sentiment_negative", "mention_rate_delta", "top1_rate_delta",
                 "top3_rate_delta", "sentiment_delta"):
        assert name in fields, f"missing field {name}"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_competitor_kpi_has_new_fields -v`
Expected: FAIL — `AssertionError: missing field top1_rate`

- [ ] **Step 4: 扩 CompetitorKpi**

打开 `backend/app/schemas/project.py:714-743`,在 `CompetitorKpi` 末尾(`spark: list[int]` 后)加:

```python
    # — 新增 — 详见 docs/superpowers/specs/2026-08-19-competitor-analysis-remove-advantages-matrix.md §1.1
    top1_rate: float
    sentiment_positive: float
    sentiment_neutral: float
    sentiment_negative: float
    mention_rate_delta: float | None
    top1_rate_delta: float | None
    top3_rate_delta: float | None
    sentiment_delta: float | None
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_competitor_kpi_has_new_fields -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/schemas/project.py backend/tests/test_competitor_analysis_api.py
git commit -m "feat(backend): extend CompetitorKpi with top1/sentiment/delta fields"
```

---

## Task 2: 后端 Schema — 新增 QuadrantPoint / ModelDiff + 扩 CompetitorAnalysisOut

**Files:**
- Modify: `backend/app/schemas/project.py:763-796`(ConcernTag + CompetitorAnalysisOut)

- [ ] **Step 1: 写失败断言**

在 `test_competitor_analysis_api.py` 加:

```python
def test_competitor_analysis_out_has_new_fields():
    from app.schemas.project import CompetitorAnalysisOut, ModelDiff, QuadrantPoint
    fields = CompetitorAnalysisOut.model_fields
    for name in ("diff_core", "diff_model", "diff_quadrant",
                 "previous_window_start", "previous_window_end"):
        assert name in fields, f"missing field {name}"
    assert "concern_tags" not in fields, "concern_tags should be removed"
    # Verify the new types are importable
    assert ModelDiff.model_fields.keys() >= {
        "platform", "self_mention_rate", "self_top1_rate", "self_top3_rate",
        "competitor_mention_rate", "competitor_top1_rate", "competitor_top3_rate"
    }
    assert QuadrantPoint.model_fields.keys() >= {
        "platform", "self_mention_rate", "competitor_avg_mention_rate"
    }
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_competitor_analysis_out_has_new_fields -v`
Expected: FAIL — missing `diff_core`

- [ ] **Step 3: 加 QuadrantPoint / ModelDiff,扩 CompetitorAnalysisOut,删 ConcernTag**

打开 `backend/app/schemas/project.py`:

1. 删 `ConcernTag` 类(行 763-770,共 8 行)
2. 在 `ConcernTag` 删掉的位置之前(`CompetitorTrendBlock` 后)加:

```python
class QuadrantPoint(BaseModel):
    platform: str
    self_mention_rate: float
    competitor_avg_mention_rate: float


class ModelDiff(BaseModel):
    platform: str
    self_mention_rate: float
    self_top1_rate: float
    self_top3_rate: float
    competitor_mention_rate: float
    competitor_top1_rate: float
    competitor_top3_rate: float
```

3. 在 `CompetitorAnalysisOut` 类中,删除 `concern_tags: list[ConcernTag]` 那一行,在它后面加:

```python
    # — 新增 — 详见 spec §1.3
    diff_core: dict                                # {"labels":[...], "self":[...], "competitor_avg":[...]}
    diff_model: list[ModelDiff]
    diff_quadrant: list[QuadrantPoint]
    previous_window_start: date | None
    previous_window_end: date | None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_competitor_analysis_out_has_new_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/schemas/project.py backend/tests/test_competitor_analysis_api.py
git commit -m "feat(backend): extend CompetitorAnalysisOut with diff/previous_window, drop concern_tags"
```

---

## Task 3: 后端 — 新建 services/competitor_analysis.py,搬移 _resolve_competitor_window + _COMPETITOR_LINE_COLORS

**Files:**
- Create: `backend/app/services/competitor_analysis.py`
- Modify: `backend/app/api/projects.py:2083-2109`(删 `_COMPETITOR_LINE_COLORS` + `_resolve_competitor_window`)

- [ ] **Step 1: 在新文件放 _COMPETITOR_LINE_COLORS + _resolve_competitor_window**

新建 `backend/app/services/competitor_analysis.py`,开头写:

```python
"""竞品分析 (data tab → 竞品分析) 计算服务。

本文件按页面分开,把所有竞品分析相关的 SQL/聚合/序列化集中在这里,
``api/projects.py`` 只剩薄壳 endpoint 调 :func:`compute_competitor_analysis`。
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta

from sqlalchemy import and_, case, func, select

from app.models.common import now_local
from app.models.project import BrandMention, ProjectCompetitor
from app.schemas.project import (
    CompetitorAnalysisOut,
    CompetitorKpi,
    CompetitorTrendBlock,
    CompetitorTrendSeries,
    ConcernTag,
)


_COMPETITOR_LINE_COLORS = [
    "#1a55e8",  # self — brand blue
    "#ff6b1a",  # 元宝
    "#13c2c2",  # DeepSeek
    "#52c41a",  # 通义
    "#722ed1",  # Kimi
    "#eb2f96",  # 文心
]


def _resolve_competitor_window(
    days: int, start: date | None, end: date | None
) -> tuple[date, date]:
    """Same shape as :func:`_overview_window` but accepts a wider range
    because the 竞品分析 tab doesn't need to compare against a baseline —
    the chart just shows the window directly."""
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("start and end must be provided together")
        if end < start:
            raise ValueError("end must not be earlier than start")
        if (end - start).days + 1 > 90:
            raise ValueError("range must not exceed 90 days")
        return start, end
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")
    today = now_local().date()
    return today - timedelta(days=days - 1), today
```

- [ ] **Step 2: 验证 import 工作**

Run: `cd backend && uv run python -c "from app.services.competitor_analysis import _resolve_competitor_window, _COMPETITOR_LINE_COLORS; print(len(_COMPETITOR_LINE_COLORS))"`
Expected: `6`

- [ ] **Step 3: 从 api/projects.py 删两个符号**

打开 `backend/app/api/projects.py`:
- 删 `_COMPETITOR_LINE_COLORS` 整个列表(行 2083-2089,共 7 行)
- 删 `_resolve_competitor_window` 整个函数(行 2092-2109,共 18 行,含前置空行)

- [ ] **Step 4: 跑现有测试看是否破坏了什么**

Run: `cd backend && uv run pytest -q --collect-only 2>&1 | head -30`
Expected: collect 通过(目前还没真正用到这两个符号的测试)

如果出现 import 错误,在 `api/projects.py` 顶部加:
```python
from app.services.competitor_analysis import _resolve_competitor_window
```

(先放着,Task 4 会一并清掉)

- [ ] **Step 5: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/services/competitor_analysis.py backend/app/api/projects.py
git commit -m "refactor(backend): move competitor_analysis helpers into services layer"
```

---

## Task 4: 后端 — 搬移 compute_competitor_analysis 函数体(暂不带新字段)

**Files:**
- Modify: `backend/app/services/competitor_analysis.py`
- Modify: `backend/app/api/projects.py:2112-2435`(endpoint body)

- [ ] **Step 1: 在新文件放 compute_competitor_analysis 函数**

打开 `backend/app/services/competitor_analysis.py`,在末尾加:

```python
def compute_competitor_analysis(
    *,
    db,
    project_id: int,
    project,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
):
    """Drives the 竞品分析 tab. Returns a ``CompetitorAnalysisOut``
    populated with self + competitors + trend. 暂未含新字段(top1 /
    情感三档 / 环比 / diff 三件套),后续 task 增量加。
    """
    win_start, win_end = _resolve_competitor_window(days, start, end)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    competitor_rows = db.scalars(
        select(ProjectCompetitor).where(ProjectCompetitor.project_id == project_id)
    ).all()
    name_by_brand: dict[str, tuple[str, list[str] | None, bool]] = {}
    for c in competitor_rows:
        name_by_brand[c.name] = (c.name, c.aliases, False)
    self_brand_name = project.brand
    self_brand_aliases = project.aliases
    if self_brand_name:
        name_by_brand[self_brand_name] = (
            self_brand_name,
            self_brand_aliases,
            True,
        )

    brand_rows = db.execute(
        select(
            BrandMention.brand_canonical,
            BrandMention.is_self,
            func.sum(case((BrandMention.mention_count > 0, 1), else_=0)).label("matched"),
            func.count().label("rows_total"),
            func.avg(
                case(
                    (
                        BrandMention.mention_count > 0,
                        case(
                            (BrandMention.sentiment_score == "positive", 1.0),
                            (BrandMention.sentiment_score == "neutral", 0.5),
                            (BrandMention.sentiment_score == "negative", 0.0),
                            else_=None,
                        ),
                    ),
                    else_=None,
                )
            ).label("avg_sentiment"),
            func.avg(
                case(
                    (
                        and_(
                            BrandMention.mention_count > 0,
                            BrandMention.rank_position.is_not(None),
                        ),
                        BrandMention.rank_position,
                    ),
                    else_=None,
                )
            ).label("avg_rank"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.mention_count > 0,
                            BrandMention.rank_position.is_not(None),
                            BrandMention.rank_position <= 3,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("top3_hits"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.mention_count > 0,
                            BrandMention.is_recommended.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("rec_hits"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
        )
        .group_by(BrandMention.brand_canonical, BrandMention.is_self)
    ).all()

    total_subtasks = db.scalar(
        select(func.count(func.distinct(BrandMention.subtask_id))).where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
        )
    ) or 0

    days_n = (win_end - win_start).days + 1
    daily_by_brand: dict[str, dict[date, int]] = {}
    daily_rows = db.execute(
        select(
            BrandMention.brand_canonical,
            func.date(BrandMention.created_at).label("day"),
            func.count(func.distinct(BrandMention.subtask_id)).label("c"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.mention_count > 0,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
        )
        .group_by(BrandMention.brand_canonical, func.date(BrandMention.created_at))
    ).all()
    for r in daily_rows:
        daily_by_brand.setdefault(r.brand_canonical, {})[r.day] = r.c

    spark_len = min(15, days_n)
    spark_start = win_end - timedelta(days=spark_len - 1)

    def _kpi_for(brand: str, is_self: bool, r) -> CompetitorKpi:
        matched = int(r.matched or 0)
        top3 = int(r.top3_hits or 0)
        rec = int(r.rec_hits or 0)
        avg_sent = float(r.avg_sentiment) if r.avg_sentiment is not None else None
        avg_rk = float(r.avg_rank) if r.avg_rank is not None else None
        display_name, aliases, _is_self_lookup = name_by_brand.get(
            brand, (brand, None, is_self)
        )
        spark: list[int] = []
        for i in range(spark_len):
            d = spark_start + timedelta(days=i)
            if d < win_start:
                spark.append(0)
            else:
                spark.append(daily_by_brand.get(brand, {}).get(d, 0))
        return CompetitorKpi(
            brand_canonical=brand,
            name=display_name,
            aliases=aliases,
            is_self=is_self,
            mention_count=matched,
            mention_rate=matched / total_subtasks if total_subtasks else 0.0,
            top3_rate=top3 / total_subtasks if total_subtasks else 0.0,
            recommend_rate=rec / total_subtasks if total_subtasks else 0.0,
            avg_sentiment=avg_sent,
            avg_rank=avg_rk,
            spark=spark,
            top1_rate=0.0,  # Task 5 填
            sentiment_positive=0.0,
            sentiment_neutral=0.0,
            sentiment_negative=0.0,
            mention_rate_delta=None,
            top1_rate_delta=None,
            top3_rate_delta=None,
            sentiment_delta=None,
        )

    self_kpi: CompetitorKpi | None = None
    competitor_kpis: list[CompetitorKpi] = []
    for r in brand_rows:
        kpi = _kpi_for(r.brand_canonical, bool(r.is_self), r)
        if r.is_self:
            self_kpi = kpi
        else:
            competitor_kpis.append(kpi)
    competitor_kpis.sort(key=lambda k: k.mention_count, reverse=True)

    labels: list[str] = []
    for i in range(days_n):
        d = win_start + timedelta(days=i)
        labels.append(d.isoformat())

    def _series_for(brand: str, name: str, is_self: bool, color: str) -> CompetitorTrendSeries:
        per_day = daily_by_brand.get(brand, {})
        data = [per_day.get(win_start + timedelta(days=i), 0) for i in range(days_n)]
        return CompetitorTrendSeries(
            brand_canonical=brand, name=name, is_self=is_self, color=color, data=data,
        )

    series: list[CompetitorTrendSeries] = []
    if self_kpi is not None:
        series.append(
            _series_for(self_kpi.brand_canonical, self_kpi.name, True, _COMPETITOR_LINE_COLORS[0])
        )
    for i, kpi in enumerate(competitor_kpis[:5], start=1):
        series.append(
            _series_for(
                kpi.brand_canonical, kpi.name, False,
                _COMPETITOR_LINE_COLORS[i % len(_COMPETITOR_LINE_COLORS)],
            )
        )

    trend_block = CompetitorTrendBlock(labels=labels, series=series)

    # Concern tag cloud — placeholder,Task 9 删
    tag_counter: Counter[str] = Counter()
    concern_tags: list[ConcernTag] = []
    _ = tag_counter  # 占位,避免未使用变量警告

    return CompetitorAnalysisOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=days_n,
        total_subtasks=int(total_subtasks),
        self_brand=self_kpi,
        competitors=competitor_kpis,
        trend=trend_block,
        concern_tags=concern_tags,
        diff_core={"labels": [], "self": [], "competitor_avg": []},
        diff_model=[],
        diff_quadrant=[],
        previous_window_start=None,
        previous_window_end=None,
    )
```

- [ ] **Step 2: api/projects.py 改为薄壳**

打开 `backend/app/api/projects.py`,替换行 2112-2435 的 endpoint + 函数体为:

```python
@router.get(
    "/projects/{project_id}/competitor-analysis",
    response_model=CompetitorAnalysisOut,
)
def get_competitor_analysis(
    project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)
    return compute_competitor_analysis(
        db=db, project_id=project_id, project=project,
        days=days, start=start, end=end,
    )
```

并在文件顶部 import 区加(放在其他 services 导入旁边):
```python
from app.services.competitor_analysis import compute_competitor_analysis
```

- [ ] **Step 3: 验证 import + smoke 调用**

Run: `cd backend && uv run python -c "from app.api.projects import get_competitor_analysis; print('ok')"`
Expected: `ok`

- [ ] **Step 4: 跑现有测试看回归**

Run: `cd backend && uv run pytest -q -x`
Expected: 全 PASS(此 task 不应破坏任何现有测试,因为 endpoint 行为不变)

- [ ] **Step 5: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/services/competitor_analysis.py backend/app/api/projects.py
git commit -m "refactor(backend): move competitor_analysis compute into services layer"
```

---

## Task 5: 后端 — 给 _kpi_for 加 top1_rate + 情感三档

**Files:**
- Modify: `backend/app/services/competitor_analysis.py`(SELECT + _kpi_for)
- Modify: `backend/tests/test_competitor_analysis_api.py`(加 helper + 真实测试)

- [ ] **Step 1: 写测试(先用占位 helper,然后写真实断言)**

在 `test_competitor_analysis_api.py` 加 helper + 真实测试:

```python
from app.models.task import Subtask as TSubtask, Task as TTask
from app.models.enums import ExtractStatus
from app.models.project import BrandMention


def _make_subtask(db, project_id, customer_id, platform="doubao"):
    """Seed one subtask + task pair."""
    task = TTask(project_id=project_id, task_id=f"task-{platform}-x", platform=platform,
                 status="success")
    db.add(task); db.flush()
    sub = TSubtask(task_id=task.task_id, subtask_id=f"subtask-{platform}-x",
                   platform=platform, status="success")
    db.add(sub); db.flush()
    return sub


def test_kpi_top1_and_sentiment_computed(client, h):
    from app.models import Customer, Project

    with TestSessionLocal() as db:
        cust = Customer(name="test", code="test")
        db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", brand="自身A")
        db.add(proj); db.flush()
        pid = proj.id

        # Seed 1 subtask, 2 brand mentions: 自身 rank=1 positive; 竞品 rank=2 negative
        sub = _make_subtask(db, pid, cust.id)
        db.add(BrandMention(
            subtask_id=sub.subtask_id, task_id=sub.task_id,
            project_id=pid, customer_id=cust.id,
            brand_canonical="自身A", is_self=True,
            mention_count=1, rank_position=1, sentiment_score="positive",
            extract_status=ExtractStatus.SUCCESS,
        ))
        db.add(BrandMention(
            subtask_id=sub.subtask_id, task_id=sub.task_id,
            project_id=pid, customer_id=cust.id,
            brand_canonical="竞品B", is_self=False,
            mention_count=1, rank_position=2, sentiment_score="negative",
            extract_status=ExtractStatus.SUCCESS,
        ))
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    self_kpi = body["self_brand"]
    assert self_kpi["top1_rate"] == 1.0
    assert self_kpi["sentiment_positive"] == 1.0
    assert self_kpi["sentiment_neutral"] == 0.0
    assert self_kpi["sentiment_negative"] == 0.0
    comp = next(c for c in body["competitors"] if c["brand_canonical"] == "竞品B")
    assert comp["top1_rate"] == 0.0  # rank=2,不是 Top1
    assert comp["sentiment_negative"] == 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_kpi_top1_and_sentiment_computed -v`
Expected: FAIL — `top1_rate == 1.0` 不通过(目前实现返回 0.0)

- [ ] **Step 3: 在 SELECT 加 top1 + sent_pos/neu/neg**

打开 `services/competitor_analysis.py` 的 `compute_competitor_analysis`,在 SELECT 里 `rec_hits` 之后加:

```python
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.mention_count > 0,
                            BrandMention.rank_position == 1,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("top1_hits"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.mention_count > 0,
                            BrandMention.sentiment_score == "positive",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("sent_pos"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.mention_count > 0,
                            BrandMention.sentiment_score == "neutral",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("sent_neu"),
            func.sum(
                case(
                    (
                        and_(
                            BrandMention.mention_count > 0,
                            BrandMention.sentiment_score == "negative",
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("sent_neg"),
```

- [ ] **Step 3: 在 _kpi_for 算新字段**

在 `_kpi_for` 函数内,`return CompetitorKpi(...)` 之前加:

```python
        top1 = int(r.top1_hits or 0)
        sent_pos = int(r.sent_pos or 0)
        sent_neu = int(r.sent_neu or 0)
        sent_neg = int(r.sent_neg or 0)
        sent_denom = matched if matched else 1
```

并把 `CompetitorKpi(...)` 调用里的:
```python
        top1_rate=0.0,  # Task 5 填
        sentiment_positive=0.0,
        sentiment_neutral=0.0,
        sentiment_negative=0.0,
```
替换为:
```python
        top1_rate=top1 / total_subtasks if total_subtasks else 0.0,
        sentiment_positive=sent_pos / sent_denom,
        sentiment_neutral=sent_neu / sent_denom,
        sentiment_negative=sent_neg / sent_denom,
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_kpi_top1_and_sentiment_computed -v`
Expected: PASS

- [ ] **Step 5: 跑全套确认没回归**

Run: `cd backend && uv run pytest -q`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/services/competitor_analysis.py backend/tests/test_competitor_analysis_api.py
git commit -m "feat(backend): add top1_rate + sentiment 3-way to CompetitorKpi"
```

---

## Task 6: 后端 — _compute_previous_window + 4 个 delta

**Files:**
- Modify: `backend/app/services/competitor_analysis.py`

- [ ] **Step 1: 写测试**

在 `test_competitor_analysis_api.py` 加:

```python
def test_kpi_deltas_compare_previous_window(client, h):
    """Seeds current window with mention_rate=1.0, prev window with 0.0 → delta=+1.0"""
    from app.models import Customer, Project

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", brand="A"); db.add(proj); db.flush()
        pid = proj.id

        today = now_local().date()
        # Current window: today (1 subtask mentioned)
        cur_sub = _make_subtask_at(db, pid, cust.id, today, platform="doubao")
        _brandmention_at(db, cur_sub, pid, cust.id, "A", True, today,
                         mention_count=1, rank=1, sentiment="positive",
                         extract_status=ExtractStatus.SUCCESS)
        # Prev window: yesterday (1 subtask, NOT mentioned)
        prev_sub = _make_subtask_at(db, pid, cust.id, today - timedelta(days=1), platform="doubao")
        _brandmention_at(db, prev_sub, pid, cust.id, "A", True, today - timedelta(days=1),
                         mention_count=0, rank=None, sentiment=None,
                         extract_status=ExtractStatus.SKIPPED)
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    assert r.status_code == 200, r.text
    self_kpi = r.json()["self_brand"]
    # current mention_rate=1.0, prev=0.0 → delta=1.0
    assert self_kpi["mention_rate_delta"] == 1.0
    assert self_kpi["top1_rate_delta"] == 1.0
    assert self_kpi["top3_rate_delta"] == 1.0
    # prev brand was SKIPPED (no sentiment) → sentiment_delta is None
    assert self_kpi["sentiment_delta"] is None
```

helper `_make_subtask_at`:

```python
def _make_subtask_at(db, project_id, customer_id, day, platform="doubao"):
    """Seed a task+subtask pair at a specific calendar day. Caller should also
    backdate the BrandMention rows that reference this subtask (BrandMention
    has its own server-default created_at, so without backdating the
    BrandMention stays in the current window)."""
    from app.models.task import Subtask as TSubtask, Task as TTask
    from datetime import datetime, time
    task = TTask(project_id=project_id, task_id=f"task-{platform}-{day}", platform=platform,
                 status="success")
    db.add(task); db.flush()
    sub = TSubtask(task_id=task.task_id, subtask_id=f"sub-{platform}-{day}",
                   platform=platform, status="success")
    db.add(sub); db.flush()
    sub.created_at = datetime.combine(day, time.min)
    return sub


def _brandmention_at(db, sub, project_id, customer_id, brand, is_self, day,
                    mention_count, rank, sentiment, extract_status):
    """BrandMention with explicit created_at so window placement is deterministic."""
    from app.models.project import BrandMention
    from app.models.enums import ExtractStatus as ES
    from datetime import datetime, time
    bm = BrandMention(
        subtask_id=sub.subtask_id, task_id=sub.task_id,
        project_id=project_id, customer_id=customer_id,
        brand_canonical=brand, is_self=is_self,
        mention_count=mention_count, rank_position=rank,
        sentiment_score=sentiment, extract_status=extract_status,
    )
    bm.created_at = datetime.combine(day, time.min)
    db.add(bm)
    return bm
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_kpi_deltas_compare_previous_window -v`
Expected: FAIL — `mention_rate_delta is None`

- [ ] **Step 3: 加 _compute_previous_window + 在 _kpi_for 算 delta**

打开 `services/competitor_analysis.py`,在 `compute_competitor_analysis` 函数体的 `daily_by_brand` 填充之前,加:

```python
    # ------------------------------------------------------------
    # 1b. Previous-window rollup for the 4 deltas.
    # ------------------------------------------------------------
    prev_end_dt = win_start_dt - timedelta(seconds=1)
    prev_start_dt = prev_end_dt - timedelta(days=days_n - 1)
    prev_brand_rows = db.execute(
        select(
            BrandMention.brand_canonical,
            BrandMention.is_self,
            func.sum(case((BrandMention.mention_count > 0, 1), else_=0)).label("matched"),
            func.avg(
                case(
                    (
                        BrandMention.mention_count > 0,
                        case(
                            (BrandMention.sentiment_score == "positive", 1.0),
                            (BrandMention.sentiment_score == "neutral", 0.5),
                            (BrandMention.sentiment_score == "negative", 0.0),
                            else_=None,
                        ),
                    ),
                    else_=None,
                )
            ).label("avg_sentiment"),
            func.sum(
                case(
                    (and_(BrandMention.mention_count > 0, BrandMention.rank_position == 1), 1),
                    else_=0,
                )
            ).label("top1_hits"),
            func.sum(
                case(
                    (and_(BrandMention.mention_count > 0, BrandMention.rank_position.is_not(None),
                          BrandMention.rank_position <= 3), 1),
                    else_=0,
                )
            ).label("top3_hits"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= prev_start_dt,
            BrandMention.created_at <= prev_end_dt,
        )
        .group_by(BrandMention.brand_canonical, BrandMention.is_self)
    ).all()

    prev_total_subtasks = db.scalar(
        select(func.count(func.distinct(BrandMention.subtask_id))).where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= prev_start_dt,
            BrandMention.created_at <= prev_end_dt,
        )
    ) or 0

    prev_window_start_d: date = prev_start_dt.date()
    prev_window_end_d: date = prev_end_dt.date()

    prev_by_brand: dict[str, dict[str, float]] = {}
    for r in prev_brand_rows:
        matched = int(r.matched or 0)
        prev_by_brand[r.brand_canonical] = {
            "mention_rate": matched / prev_total_subtasks if prev_total_subtasks else 0.0,
            "top1_rate": int(r.top1_hits or 0) / prev_total_subtasks if prev_total_subtasks else 0.0,
            "top3_rate": int(r.top3_hits or 0) / prev_total_subtasks if prev_total_subtasks else 0.0,
            "avg_sentiment": float(r.avg_sentiment) if r.avg_sentiment is not None else None,
        }
```

- [ ] **Step 4: 在 _kpi_for 算 4 个 delta**

在 `_kpi_for` 函数内 `sent_denom = matched if matched else 1` 之后加:

```python
        prev = prev_by_brand.get(brand, {})
        mention_rate_delta = (
            (matched / total_subtasks) - prev.get("mention_rate")
            if prev and total_subtasks else None
        )
        top1_rate_delta = (
            (top1 / total_subtasks) - prev.get("top1_rate")
            if prev and total_subtasks else None
        )
        top3_rate_delta = (
            (top3 / total_subtasks) - prev.get("top3_rate")
            if prev and total_subtasks else None
        )
        sentiment_delta = (
            avg_sent - prev.get("avg_sentiment")
            if prev and avg_sent is not None and prev.get("avg_sentiment") is not None
            else None
        )
```

并把 return 里:
```python
            mention_rate_delta=None,
            top1_rate_delta=None,
            top3_rate_delta=None,
            sentiment_delta=None,
```
替换为上面 4 个变量。

- [ ] **Step 5: 在 return 处填 previous_window_start/end**

把 `compute_competitor_analysis` 末尾 `return CompetitorAnalysisOut(...)` 里:
```python
        previous_window_start=None,
        previous_window_end=None,
```
替换为:
```python
        previous_window_start=prev_window_start_d if prev_brand_rows else None,
        previous_window_end=prev_window_end_d if prev_brand_rows else None,
```

- [ ] **Step 6: 跑测试**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_kpi_deltas_compare_previous_window -v`
Expected: PASS

- [ ] **Step 7: 跑全套**

Run: `cd backend && uv run pytest -q`
Expected: 全 PASS

- [ ] **Step 8: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/services/competitor_analysis.py backend/tests/test_competitor_analysis_api.py
git commit -m "feat(backend): add 4 deltas comparing current vs previous window"
```

---

## Task 7: 后端 — _compute_diff_core

**Files:**
- Modify: `backend/app/services/competitor_analysis.py`

- [ ] **Step 1: 写测试**

在 `test_competitor_analysis_api.py` 加:

```python
def test_diff_core_self_vs_competitor_avg(client, h):
    """3 个指标 self vs competitor avg,百分比 0-100。"""
    from app.models import Customer, Project

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", brand="自身A"); db.add(proj); db.flush()
        pid = proj.id

        # 1 subtask, 自身 rank=1 mentioned, 2 竞品 各 rank=2 mentioned
        sub = _make_subtask(db, pid, cust.id)
        for b, is_self, rank in [("自身A", True, 1), ("竞品B", False, 2), ("竞品C", False, 2)]:
            db.add(BrandMention(
                subtask_id=sub.subtask_id, task_id=sub.task_id,
                project_id=pid, customer_id=cust.id,
                brand_canonical=b, is_self=is_self,
                mention_count=1, rank_position=rank,
                sentiment_score="positive" if is_self else "neutral",
                extract_status=ExtractStatus.SUCCESS,
            ))
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    body = r.json()["diff_core"]
    assert body["labels"] == ["提及率", "Top1", "Top3"]
    # 自身:mention_rate=1.0, top1=1.0, top3=1.0 → 100,100,100
    assert body["self"] == [100.0, 100.0, 100.0]
    # 竞品均值:mention_rate=1.0 each (avg=1.0), top1=0.0, top3=0.0 → 100,0,0
    assert body["competitor_avg"] == [100.0, 0.0, 0.0]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_diff_core_self_vs_competitor_avg -v`
Expected: FAIL — `body["self"] == []`

- [ ] **Step 3: 在 services 文件加 _compute_diff_core**

打开 `services/competitor_analysis.py`,在文件顶部(类/函数定义后)加:

```python
def _compute_diff_core(self_kpi, competitor_kpis):
    """核心指标对比 — 3 个指标(mention_rate / top1_rate / top3_rate)的自身 vs 竞品均值,
    单位 0-100(已乘 100),便于 UI 直接画柱状图。"""
    empty = {"labels": ["提及率", "Top1", "Top3"], "self": [0.0, 0.0, 0.0], "competitor_avg": [0.0, 0.0, 0.0]}
    if not self_kpi or not competitor_kpis:
        return empty
    n = len(competitor_kpis)
    return {
        "labels": ["提及率", "Top1", "Top3"],
        "self": [
            self_kpi.mention_rate * 100,
            self_kpi.top1_rate * 100,
            self_kpi.top3_rate * 100,
        ],
        "competitor_avg": [
            sum(c.mention_rate for c in competitor_kpis) / n * 100,
            sum(c.top1_rate for c in competitor_kpis) / n * 100,
            sum(c.top3_rate for c in competitor_kpis) / n * 100,
        ],
    }
```

- [ ] **Step 4: 在 compute_competitor_analysis 调用 _compute_diff_core**

在 `trend_block = CompetitorTrendBlock(...)` 之后,加:

```python
    diff_core = _compute_diff_core(self_kpi, competitor_kpis)
```

并把 `return CompetitorAnalysisOut(...)` 里:
```python
        diff_core={"labels": [], "self": [], "competitor_avg": []},
```
替换为 `diff_core=diff_core,`。

- [ ] **Step 5: 跑测试**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_diff_core_self_vs_competitor_avg -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/services/competitor_analysis.py backend/tests/test_competitor_analysis_api.py
git commit -m "feat(backend): add _compute_diff_core for 核心指标对比"
```

---

## Task 8: 后端 — _compute_diff_model

**Files:**
- Modify: `backend/app/services/competitor_analysis.py`

- [ ] **Step 1: 写测试**

在 `test_competitor_analysis_api.py` 加:

```python
def test_diff_model_per_platform_self_vs_competitor(client, h):
    """每个 platform 一行,自身/竞品均值 in 提及率/Top1/Top3。"""
    from app.models import Customer, Project

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", brand="A"); db.add(proj); db.flush()
        pid = proj.id

        # doubao: 自身 rank=1 + 1 竞品 rank=2 (1 subtask)
        sub1 = _make_subtask(db, pid, cust.id, platform="doubao")
        db.add(BrandMention(subtask_id=sub1.subtask_id, task_id=sub1.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="A", is_self=True,
            mention_count=1, rank_position=1, sentiment_score="positive", extract_status=ExtractStatus.SUCCESS))
        db.add(BrandMention(subtask_id=sub1.subtask_id, task_id=sub1.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="B", is_self=False,
            mention_count=1, rank_position=2, sentiment_score="neutral", extract_status=ExtractStatus.SUCCESS))
        # kimi: 自身 未提及 + 1 竞品 rank=1
        sub2 = _make_subtask(db, pid, cust.id, platform="kimi")
        db.add(BrandMention(subtask_id=sub2.subtask_id, task_id=sub2.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="A", is_self=True,
            mention_count=0, extract_status=ExtractStatus.SKIPPED))
        db.add(BrandMention(subtask_id=sub2.subtask_id, task_id=sub2.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="B", is_self=False,
            mention_count=1, rank_position=1, sentiment_score="positive", extract_status=ExtractStatus.SUCCESS))
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    diff_model = {m["platform"]: m for m in r.json()["diff_model"]}
    assert "doubao" in diff_model
    assert "kimi" in diff_model
    # doubao: self mention_rate=1.0, top1=1.0, top3=1.0; comp avg mention=1.0, top1=0.0, top3=0.0
    assert diff_model["doubao"]["self_mention_rate"] == 1.0
    assert diff_model["doubao"]["self_top1_rate"] == 1.0
    assert diff_model["doubao"]["competitor_top1_rate"] == 0.0
    # kimi: self mention_rate=0.0, comp avg mention=1.0, top1=1.0
    assert diff_model["kimi"]["self_mention_rate"] == 0.0
    assert diff_model["kimi"]["competitor_mention_rate"] == 1.0
    assert diff_model["kimi"]["competitor_top1_rate"] == 1.0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_diff_model_per_platform_self_vs_competitor -v`
Expected: FAIL — `diff_model` 为空

- [ ] **Step 3: 在 services 文件加 _compute_diff_model**

打开 `services/competitor_analysis.py`,在 `_compute_diff_core` 后加:

```python
def _compute_diff_model(db, project_id, win_start_dt, win_end_dt):
    """模型维度提及率 — 每个 platform 一行,自身 vs 竞品均值。"""
    from sqlalchemy import and_, case, func, select
    from app.models.project import BrandMention
    from app.schemas.project import ModelDiff

    rows = db.execute(
        select(
            BrandMention.platform,
            BrandMention.is_self,
            func.count(func.distinct(BrandMention.subtask_id)).label("total"),
            func.sum(case((and_(BrandMention.mention_count > 0, BrandMention.rank_position == 1), 1), else_=0)).label("top1"),
            func.sum(case((and_(BrandMention.mention_count > 0,
                                  BrandMention.rank_position.is_not(None),
                                  BrandMention.rank_position <= 3), 1), else_=0)).label("top3"),
            func.sum(case((BrandMention.mention_count > 0, 1), else_=0)).label("matched"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
            BrandMention.platform.is_not(None),
        )
        .group_by(BrandMention.platform, BrandMention.is_self)
    ).all()

    by_plat: dict[str, dict[str, dict[str, float]]] = {}
    for r in rows:
        plat = r.platform
        total = int(r.total or 0)
        denom = total if total else 1
        bucket = by_plat.setdefault(plat, {"self": {}, "comp": {}})
        side = "self" if r.is_self else "comp"
        bucket[side] = {
            "mention_rate": int(r.matched or 0) / denom,
            "top1_rate": int(r.top1 or 0) / denom,
            "top3_rate": int(r.top3 or 0) / denom,
        }

    out: list[ModelDiff] = []
    for plat, sides in by_plat.items():
        s = sides.get("self", {"mention_rate": 0.0, "top1_rate": 0.0, "top3_rate": 0.0})
        c = sides.get("comp", {"mention_rate": 0.0, "top1_rate": 0.0, "top3_rate": 0.0})
        out.append(ModelDiff(
            platform=plat,
            self_mention_rate=s["mention_rate"],
            self_top1_rate=s["top1_rate"],
            self_top3_rate=s["top3_rate"],
            competitor_mention_rate=c["mention_rate"],
            competitor_top1_rate=c["top1_rate"],
            competitor_top3_rate=c["top3_rate"],
        ))
    out.sort(key=lambda m: m.platform)
    return out
```

- [ ] **Step 4: 在 compute_competitor_analysis 调用**

在 `diff_core = _compute_diff_core(...)` 之后,加:

```python
    diff_model = _compute_diff_model(db, project_id, win_start_dt, win_end_dt)
```

并把 return 里 `diff_model=[]` 替换为 `diff_model=diff_model`。

- [ ] **Step 5: 跑测试**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_diff_model_per_platform_self_vs_competitor -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/services/competitor_analysis.py backend/tests/test_competitor_analysis_api.py
git commit -m "feat(backend): add _compute_diff_model for 模型维度提及率"
```

---

## Task 9: 后端 — _compute_diff_quadrant + 删 concern_tags

**Files:**
- Modify: `backend/app/services/competitor_analysis.py`

- [ ] **Step 1: 写 quadrant 测试**

```python
def test_diff_quadrant_per_platform_point(client, h):
    from app.models import Customer, Project

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", brand="A"); db.add(proj); db.flush()
        pid = proj.id
        sub = _make_subtask(db, pid, cust.id, platform="doubao")
        db.add(BrandMention(subtask_id=sub.subtask_id, task_id=sub.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="A", is_self=True,
            mention_count=1, rank_position=1, sentiment_score="positive", extract_status=ExtractStatus.SUCCESS))
        db.add(BrandMention(subtask_id=sub.subtask_id, task_id=sub.task_id,
            project_id=pid, customer_id=cust.id, brand_canonical="B", is_self=False,
            mention_count=1, rank_position=2, sentiment_score="neutral", extract_status=ExtractStatus.SUCCESS))
        db.commit()

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    quad = r.json()["diff_quadrant"]
    assert len(quad) == 1
    assert quad[0]["platform"] == "doubao"
    assert quad[0]["self_mention_rate"] == 1.0
    assert quad[0]["competitor_avg_mention_rate"] == 1.0
```

- [ ] **Step 2: 写 concern_tags 删除验证测试**

```python
def test_competitor_analysis_no_concern_tags(client, h):
    from app.models import Customer, Project

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", brand="A"); db.add(proj); db.flush()
        pid = proj.id

    r = await client.get(f"/api/projects/{pid}/competitor-analysis?days=15", headers=h)
    assert r.status_code == 200
    assert "concern_tags" not in r.json()
```

- [ ] **Step 3: 跑测试确认失败**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_diff_quadrant_per_platform_point tests/test_competitor_analysis_api.py::test_competitor_analysis_no_concern_tags -v`
Expected: 2 FAIL — diff_quadrant 空 + concern_tags 仍存在

- [ ] **Step 4: 在 services 文件加 _compute_diff_quadrant**

在 `_compute_diff_model` 后加:

```python
def _compute_diff_quadrant(diff_model):
    """四象限 — 从 per-platform 抽 mention_rate 点。每个 platform 一个点。"""
    from app.schemas.project import QuadrantPoint
    return [
        QuadrantPoint(
            platform=m.platform,
            self_mention_rate=m.self_mention_rate,
            competitor_avg_mention_rate=m.competitor_mention_rate,
        )
        for m in diff_model
    ]
```

- [ ] **Step 5: 在 compute_competitor_analysis 调用 + 删 concern_tags 整块**

在 `diff_model = _compute_diff_model(...)` 之后加:

```python
    diff_quadrant = _compute_diff_quadrant(diff_model)
```

把 return 里 `diff_quadrant=[]` 替换为 `diff_quadrant=diff_quadrant`。

然后删 `compute_competitor_analysis` 里整个 `tag_counter` / `concern_tags` 块(从 `# Concern tag cloud — placeholder` 注释到 `concern_tags: list[ConcernTag] = []` 行)。

return 里把:
```python
        concern_tags=concern_tags,
```
整行删掉。

- [ ] **Step 6: 跑测试**

Run: `cd backend && uv run pytest tests/test_competitor_analysis_api.py::test_diff_quadrant_per_platform_point tests/test_competitor_analysis_api.py::test_competitor_analysis_no_concern_tags -v`
Expected: 2 PASS

- [ ] **Step 7: 跑全套**

Run: `cd backend && uv run pytest -q`
Expected: 全 PASS

- [ ] **Step 8: Commit**

```bash
cd /home/wangjh/projects/windx
git add backend/app/services/competitor_analysis.py backend/tests/test_competitor_analysis_api.py
git commit -m "feat(backend): add quadrant + remove concern_tags"
```

---

## Task 10: 前端 — 更新 api/projects.ts 类型

**Files:**
- Modify: `frontend/src/api/projects.ts:735-786`

- [ ] **Step 1: 扩 CompetitorKpi**

打开 `frontend/src/api/projects.ts`,把:

```ts
export interface CompetitorKpi {
  brand_canonical: string;
  name: string;
  aliases: string[] | null;
  is_self: boolean;
  mention_count: number;
  mention_rate: number;
  top3_rate: number;
  recommend_rate: number;
  avg_sentiment: number | null;
  avg_rank: number | null;
  /** 7-day sparkline, zero-filled, ordered oldest → newest. */
  spark: number[];
}
```

替换为:

```ts
export interface CompetitorKpi {
  brand_canonical: string;
  name: string;
  aliases: string[] | null;
  is_self: boolean;
  mention_count: number;
  mention_rate: number;
  top3_rate: number;
  recommend_rate: number;
  avg_sentiment: number | null;
  avg_rank: number | null;
  /** 15-day sparkline, zero-filled, ordered oldest → newest. */
  spark: number[];
  /** Top1 提及率(= rank_position=1 且 mention_count>0 的次数 / total_subtasks) */
  top1_rate: number;
  /** 情感三档占比(分母 = mention_count>0 的样本数) */
  sentiment_positive: number;
  sentiment_neutral: number;
  sentiment_negative: number;
  /** 环比 vs 同长度上一窗口;窗口太短或无数据为 null */
  mention_rate_delta: number | null;
  top1_rate_delta: number | null;
  top3_rate_delta: number | null;
  sentiment_delta: number | null;
}
```

- [ ] **Step 2: 加 QuadrantPoint / ModelDiff,删 ConcernTag*,扩 CompetitorAnalysisOut**

在 `CompetitorTrendBlock` 后,删 `ConcernTagCls` / `ConcernTag` 整个定义。

然后加新类型:

```ts
export interface QuadrantPoint {
  platform: string;
  self_mention_rate: number;
  competitor_avg_mention_rate: number;
}

export interface ModelDiff {
  platform: string;
  self_mention_rate: number;
  self_top1_rate: number;
  self_top3_rate: number;
  competitor_mention_rate: number;
  competitor_top1_rate: number;
  competitor_top3_rate: number;
}

export interface DiffCore {
  labels: string[];
  self: number[];
  competitor_avg: number[];
}
```

把 `CompetitorAnalysisOut` 替换为:

```ts
export interface CompetitorAnalysisOut {
  project_id: number;
  start: string;
  end: string;
  days: number;
  total_subtasks: number;
  self_brand: CompetitorKpi | null;
  competitors: CompetitorKpi[];
  trend: CompetitorTrendBlock;
  diff_core: DiffCore;
  diff_model: ModelDiff[];
  diff_quadrant: QuadrantPoint[];
  previous_window_start: string | null;
  previous_window_end: string | null;
}
```

- [ ] **Step 3: 跑 typecheck 看是否破坏其他文件**

Run: `cd frontend && pnpm run typecheck 2>&1 | tail -30`
Expected: 失败 — `CompetitorAnalysisTab.tsx` 仍用 `concern_tags`

- [ ] **Step 4: Commit**

```bash
cd /home/wangjh/projects/windx
git add frontend/src/api/projects.ts
git commit -m "feat(frontend): extend competitor analysis types with diff/previous_window"
```

---

## Task 11: 前端 — CompetitorAnalysisTab 改 3 个二级 tab 结构

**Files:**
- Modify: `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx`(整页重写骨架)

- [ ] **Step 1: 重写文件骨架(只放 tab 容器,内容稍后填)**

整文件覆盖为:

```tsx
import { useEffect, useState } from "react";
import { Empty, Skeleton, Tabs, message } from "antd";
import {
  getCompetitorAnalysis,
  type CompetitorAnalysisOut,
  type CompetitorKpi,
} from "../../api/projects";
import OverviewTable from "./competitorAnalysis/OverviewTable";
import TrendFullPane from "./competitorAnalysis/TrendFullPane";
import DiffPane from "./competitorAnalysis/DiffPane";

interface Props {
  projectId: number;
}

type SubTab = "all" | "trend" | "diff";

export default function CompetitorAnalysisTab({ projectId }: Props) {
  const [data, setData] = useState<CompetitorAnalysisOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [sub, setSub] = useState<SubTab>("all");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getCompetitorAnalysis(projectId)
      .then((analysis) => {
        if (cancelled) return;
        setData(analysis);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        message.error(err.message || "竞品分析数据加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [projectId]);

  if (loading) return <Skeleton active paragraph={{ rows: 12 }} />;
  if (!data) return <Empty description="暂无可展示的竞品分析数据" />;

  const overviewRows: CompetitorKpi[] = [];
  if (data.self_brand) overviewRows.push(data.self_brand);
  overviewRows.push(...data.competitors);

  return (
    <div className="cna-root">
      <Tabs
        activeKey={sub}
        onChange={(k) => setSub(k as SubTab)}
        items={[
          { key: "all", label: "全部竞品", children: <AllPane data={data} rows={overviewRows} /> },
          { key: "trend", label: "趋势对比", children: <TrendFullPane data={data} /> },
          { key: "diff", label: "差异化分析", children: <DiffPane data={data} /> },
        ]}
      />
    </div>
  );
}

function AllPane({ data, rows }: { data: CompetitorAnalysisOut; rows: CompetitorKpi[] }) {
  return (
    <div className="cna-grid">
      <OverviewTable rows={rows} />
      <div className="panel panel-wide">
        <div className="panel-header"><h3>提及趋势对比(自身 vs 竞品)</h3></div>
        <div className="panel-body">
          {data.trend.series.length === 0
            ? <Empty description="窗口内尚无每日提及数据" style={{ padding: 32 }} />
            : <TrendChart labels={data.trend.labels} series={data.trend.series} />}
        </div>
      </div>
    </div>
  );
}

// 复用 TrendChart(从原文件搬过来)
import { CompetitorTrendSeries } from "../../api/projects";

function TrendChart({ labels, series }: {
  labels: string[];
  series: CompetitorTrendSeries[];
}) {
  const w = 760, h = 240, padL = 40, padR = 12, padT = 12, padB = 28;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const allValues = series.flatMap((s) => s.data);
  const max = Math.max(...allValues, 1);
  const yMax = Math.ceil(max / 5) * 5 || 5;
  const x = (i: number) => padL + (labels.length > 1 ? (i * innerW) / (labels.length - 1) : innerW / 2);
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => Math.round((yMax * i) / ticks));
  return (
    <svg className="trend-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {yTicks.map((t, i) => {
        const yy = padT + innerH - (t / yMax) * innerH;
        return (
          <g key={i}>
            <line className="grid-line" x1={padL} y1={yy} x2={w - padR} y2={yy} />
            <text className="axis-label" x={padL - 6} y={yy + 3} textAnchor="end">{t}</text>
          </g>
        );
      })}
      {labels.map((lab, i) => {
        if (labels.length > 7 && i % Math.ceil(labels.length / 6) !== 0) return null;
        return <text className="axis-label" key={i} x={x(i)} y={h - 8} textAnchor="middle">{lab.slice(5)}</text>;
      })}
      {series.map((s) => {
        const points = s.data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
        return (
          <g key={s.brand_canonical}>
            <polyline className="line" stroke={s.color} points={points} />
            {s.data.map((v, i) => v > 0 ? (
              <circle key={i} className="dot" cx={x(i)} cy={y(v)} r={2.5} fill={s.color} />
            ) : null)}
          </g>
        );
      })}
    </svg>
  );
}
```

(其他内部样式类如 `.cna-root` / `.cna-grid` / `.panel` 复用 Task 18 集中加的 `<style>` 块;OverviewTable / TrendFullPane / DiffPane 在后续 task 创建)

- [ ] **Step 2: 创建占位子组件文件**

新建三个文件,每个里面放空组件(后续 task 填):

`frontend/src/pages/Projects/competitorAnalysis/OverviewTable.tsx`:
```tsx
import type { CompetitorKpi } from "../../../api/projects";

export default function OverviewTable({ rows }: { rows: CompetitorKpi[] }) {
  return (
    <div className="panel panel-wide">
      <div className="panel-header"><h3>竞品概览</h3></div>
      <div className="panel-body" style={{ padding: 0 }}>
        <table className="data-table data-table-hover">
          <thead><tr><th>品牌</th><th>待填</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.brand_canonical}><td>{r.name}</td><td>—</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
```

`frontend/src/pages/Projects/competitorAnalysis/TrendFullPane.tsx`:
```tsx
import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";

export default function TrendFullPane({ data }: { data: CompetitorAnalysisOut }) {
  return (
    <div className="panel panel-wide">
      <div className="panel-header">
        <div>
          <h3>完整提及趋势对比(自身 vs 竞品)</h3>
          <p>{data.start} ~ {data.end} · 共 {data.days} 天</p>
        </div>
      </div>
      <div className="panel-body">
        <Empty description="占位 — Task 13 填充" style={{ padding: 32 }} />
      </div>
    </div>
  );
}
```

`frontend/src/pages/Projects/competitorAnalysis/DiffPane.tsx`:
```tsx
import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";

export default function DiffPane({ data }: { data: CompetitorAnalysisOut }) {
  return (
    <div className="diff-grid">
      <div className="panel"><div className="panel-header"><h3>核心指标对比</h3></div>
        <div className="panel-body"><Empty description="占位 — Task 16/17 填充" style={{ padding: 32 }} /></div></div>
      <div className="panel"><div className="panel-header"><h3>模型维度提及率</h3></div>
        <div className="panel-body"><Empty description="占位 — Task 16/17 填充" style={{ padding: 32 }} /></div></div>
      <div className="panel panel-wide"><div className="panel-header"><h3>模型竞争四象限</h3></div>
        <div className="panel-body"><Empty description="占位 — Task 16/17 填充" style={{ padding: 32 }} /></div></div>
    </div>
  );
}
```

- [ ] **Step 3: 跑 typecheck**

Run: `cd frontend && pnpm run typecheck 2>&1 | tail -20`
Expected: 通过(三个子组件都有 stub)

- [ ] **Step 4: 跑 lint**

Run: `cd frontend && pnpm run lint 2>&1 | tail -20`
Expected: 通过

- [ ] **Step 5: Commit**

```bash
cd /home/wangjh/projects/windx
git add frontend/src/pages/Projects/CompetitorAnalysisTab.tsx frontend/src/pages/Projects/competitorAnalysis/
git commit -m "feat(frontend): restructure CompetitorAnalysisTab with 3 sub-tabs"
```

---

## Task 12: 前端 — 重写 OverviewTable 为 8 列

**Files:**
- Modify: `frontend/src/pages/Projects/competitorAnalysis/OverviewTable.tsx`

- [ ] **Step 1: 替换为完整 8 列实现**

整文件覆盖:

```tsx
import { Empty, Tag } from "antd";
import type { CompetitorKpi } from "../../../api/projects";

function pct(v: number): string { return `${(v * 100).toFixed(1)}%`; }
function pctDelta(v: number | null): string {
  if (v === null) return "—";
  const arrow = v > 0 ? "▲" : v < 0 ? "▼" : "—";
  return `${arrow} ${(Math.abs(v) * 100).toFixed(1)}%`;
}
function deltaClass(v: number | null): string {
  if (v === null || v === 0) return "delta-neutral";
  return v > 0 ? "delta-up" : "delta-down";
}

function Sparkline({ values }: { values: number[] }) {
  if (!values || values.length === 0) return <span>—</span>;
  const max = Math.max(...values, 1);
  const w = 120, h = 22;
  const step = values.length > 1 ? w / (values.length - 1) : 0;
  const points = values.map((v, i) => `${(i * step).toFixed(1)},${(h - (v / max) * h).toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline fill="none" stroke="var(--brand-blue, #1a55e8)" strokeWidth="1.5" points={points} />
    </svg>
  );
}

export default function OverviewTable({ rows }: { rows: CompetitorKpi[] }) {
  return (
    <div className="panel panel-wide">
      <div className="panel-header"><h3>竞品概览</h3></div>
      <div className="panel-body" style={{ padding: 0 }}>
        {rows.length === 0
          ? <Empty description="窗口内尚未识别到任何品牌" style={{ padding: 32 }} />
          : (
            <table className="data-table data-table-hover">
              <thead>
                <tr>
                  <th rowSpan={2}>品牌</th>
                  <th rowSpan={2}>提及率</th>
                  <th rowSpan={2}>Top1</th>
                  <th rowSpan={2}>Top3</th>
                  <th rowSpan={2}>情感-正</th>
                  <th rowSpan={2}>情感-中</th>
                  <th rowSpan={2}>情感-负</th>
                  <th colSpan={4}>环比变化</th>
                </tr>
                <tr>
                  <th className="th-sub">提及率</th>
                  <th className="th-sub">Top1</th>
                  <th className="th-sub">Top3</th>
                  <th className="th-sub">情感</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.brand_canonical}>
                    <td>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        {row.is_self && <Tag color="blue" style={{ margin: 0 }}>自身</Tag>}
                        <span style={{ fontWeight: row.is_self ? 600 : 500 }}>{row.name}</span>
                      </div>
                      {row.aliases && row.aliases.length > 0 && (
                        <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>
                          别名:{row.aliases.slice(0, 3).join("、")}{row.aliases.length > 3 && " …"}
                        </div>
                      )}
                    </td>
                    <td>{pct(row.mention_rate)}</td>
                    <td>{pct(row.top1_rate)}</td>
                    <td>{pct(row.top3_rate)}</td>
                    <td>{pct(row.sentiment_positive)}</td>
                    <td>{pct(row.sentiment_neutral)}</td>
                    <td>{pct(row.sentiment_negative)}</td>
                    <td className={deltaClass(row.mention_rate_delta)}>{pctDelta(row.mention_rate_delta)}</td>
                    <td className={deltaClass(row.top1_rate_delta)}>{pctDelta(row.top1_rate_delta)}</td>
                    <td className={deltaClass(row.top3_rate_delta)}>{pctDelta(row.top3_rate_delta)}</td>
                    <td className={deltaClass(row.sentiment_delta)}>{pctDelta(row.sentiment_delta)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 跑 typecheck + lint**

Run: `cd frontend && pnpm run typecheck && pnpm run lint 2>&1 | tail -15`
Expected: 通过

- [ ] **Step 3: Commit**

```bash
cd /home/wangjh/projects/windx
git add frontend/src/pages/Projects/competitorAnalysis/OverviewTable.tsx
git commit -m "feat(frontend): 8-column overview table with delta indicators"
```

---

## Task 13: 前端 — TrendFullPane 复用 TrendChart

**Files:**
- Modify: `frontend/src/pages/Projects/competitorAnalysis/TrendFullPane.tsx`
- Create: `frontend/src/pages/Projects/competitorAnalysis/TrendChart.tsx`(抽出来,供 AllPane 和 TrendFullPane 复用)

- [ ] **Step 1: 抽 TrendChart 到独立文件**

新建 `frontend/src/pages/Projects/competitorAnalysis/TrendChart.tsx`,把 Task 11 里 inline 在 CompetitorAnalysisTab.tsx 的 TrendChart 函数搬过来(全函数体复制,只改 import 路径)。最终文件内容:

```tsx
import type { CompetitorTrendSeries } from "../../../api/projects";

export default function TrendChart({ labels, series }: {
  labels: string[];
  series: CompetitorTrendSeries[];
}) {
  const w = 760, h = 240, padL = 40, padR = 12, padT = 12, padB = 28;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const allValues = series.flatMap((s) => s.data);
  const max = Math.max(...allValues, 1);
  const yMax = Math.ceil(max / 5) * 5 || 5;
  const x = (i: number) => padL + (labels.length > 1 ? (i * innerW) / (labels.length - 1) : innerW / 2);
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) => Math.round((yMax * i) / ticks));
  return (
    <svg className="trend-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {yTicks.map((t, i) => {
        const yy = padT + innerH - (t / yMax) * innerH;
        return (
          <g key={i}>
            <line className="grid-line" x1={padL} y1={yy} x2={w - padR} y2={yy} />
            <text className="axis-label" x={padL - 6} y={yy + 3} textAnchor="end">{t}</text>
          </g>
        );
      })}
      {labels.map((lab, i) => {
        if (labels.length > 7 && i % Math.ceil(labels.length / 6) !== 0) return null;
        return <text className="axis-label" key={i} x={x(i)} y={h - 8} textAnchor="middle">{lab.slice(5)}</text>;
      })}
      {series.map((s) => {
        const points = s.data.map((v, i) => `${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
        return (
          <g key={s.brand_canonical}>
            <polyline className="line" stroke={s.color} points={points} />
            {s.data.map((v, i) => v > 0 ? (
              <circle key={i} className="dot" cx={x(i)} cy={y(v)} r={2.5} fill={s.color} />
            ) : null)}
          </g>
        );
      })}
    </svg>
  );
}
```

- [ ] **Step 2: CompetitorAnalysisTab.tsx 删内部 TrendChart,改为 import**

打开 `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx`:
- 删除 Task 11 里 inline 的 `TrendChart` 函数(末尾)
- 顶部 import 加:
  ```tsx
  import TrendChart from "./competitorAnalysis/TrendChart";
  ```

- [ ] **Step 3: TrendFullPane 用上 TrendChart**

整文件覆盖:

```tsx
import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";
import TrendChart from "./TrendChart";

export default function TrendFullPane({ data }: { data: CompetitorAnalysisOut }) {
  return (
    <div className="panel panel-wide">
      <div className="panel-header">
        <div>
          <h3>完整提及趋势对比(自身 vs 竞品)</h3>
          <p>{data.start} ~ {data.end} · 共 {data.days} 天</p>
        </div>
        <div className="trend-legend">
          {data.trend.series.map((s) => (
            <span key={s.brand_canonical} className="legend-item">
              <span className="legend-swatch" style={{ background: s.color }} />
              {s.name}
            </span>
          ))}
        </div>
      </div>
      <div className="panel-body">
        {data.trend.series.length === 0
          ? <Empty description="窗口内尚无每日提及数据" style={{ padding: 32 }} />
          : <TrendChart labels={data.trend.labels} series={data.trend.series} />}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: 跑 typecheck + lint**

Run: `cd frontend && pnpm run typecheck && pnpm run lint 2>&1 | tail -15`
Expected: 通过

- [ ] **Step 5: Commit**

```bash
cd /home/wangjh/projects/windx
git add frontend/src/pages/Projects/CompetitorAnalysisTab.tsx frontend/src/pages/Projects/competitorAnalysis/
git commit -m "feat(frontend): extract TrendChart; TrendFullPane reuses it"
```

---

## Task 14: 前端 — BarChart 通用组件

**Files:**
- Create: `frontend/src/pages/Projects/competitorAnalysis/BarChart.tsx`

- [ ] **Step 1: 创建组件**

新建 `frontend/src/pages/Projects/competitorAnalysis/BarChart.tsx`:

```tsx
interface BarSeries {
  name: string;
  color: string;
  data: number[];
}

interface Props {
  labels: string[];
  series: BarSeries[];
  /** Optional y-axis unit suffix displayed in tooltips/labels. */
  unit?: string;
  /** Hard upper bound for y-axis. If omitted, computed from data. */
  yMax?: number;
}

export default function BarChart({ labels, series, unit, yMax }: Props) {
  const w = 520, h = 240, padL = 44, padR = 16, padT = 12, padB = 36;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const allValues = series.flatMap((s) => s.data);
  const computedMax = Math.max(...allValues, 1);
  const yTop = yMax ?? Math.ceil(computedMax / 5) * 5 || 5;
  const groupWidth = innerW / Math.max(labels.length, 1);
  const barWidth = Math.min(28, (groupWidth * 0.8) / Math.max(series.length, 1));

  const xCenter = (i: number) => padL + i * groupWidth + groupWidth / 2;
  const y = (v: number) => padT + innerH - (v / yTop) * innerH;

  const ticks = 4;
  const yTicks = Array.from({ length: ticks + 1 }, (_, i) =>
    Math.round((yTop * i) / ticks),
  );

  return (
    <svg className="bar-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {yTicks.map((t, i) => {
        const yy = padT + innerH - (t / yTop) * innerH;
        return (
          <g key={i}>
            <line className="grid-line" x1={padL} y1={yy} x2={w - padR} y2={yy} />
            <text className="axis-label" x={padL - 6} y={yy + 3} textAnchor="end">{t}{unit ?? ""}</text>
          </g>
        );
      })}
      {labels.map((lab, i) => (
        <text key={i} className="axis-label" x={xCenter(i)} y={h - 12} textAnchor="middle">
          {lab.length > 8 ? lab.slice(0, 7) + "…" : lab}
        </text>
      ))}
      {labels.map((_, i) =>
        series.map((s, sIdx) => {
          const v = s.data[i] ?? 0;
          const xOff = xCenter(i) - (series.length * barWidth) / 2 + sIdx * barWidth;
          return (
            <rect
              key={`${i}-${sIdx}`}
              x={xOff}
              y={y(v)}
              width={barWidth - 2}
              height={padT + innerH - y(v)}
              fill={s.color}
              rx={2}
            >
              <title>{`${s.name} · ${labels[i]}: ${v}${unit ?? ""}`}</title>
            </rect>
          );
        }),
      )}
    </svg>
  );
}
```

- [ ] **Step 2: 跑 typecheck**

Run: `cd frontend && pnpm run typecheck 2>&1 | tail -10`
Expected: 通过

- [ ] **Step 3: Commit**

```bash
cd /home/wangjh/projects/windx
git add frontend/src/pages/Projects/competitorAnalysis/BarChart.tsx
git commit -m "feat(frontend): add BarChart generic grouped bar component"
```

---

## Task 15: 前端 — QuadrantChart 组件

**Files:**
- Create: `frontend/src/pages/Projects/competitorAnalysis/QuadrantChart.tsx`

- [ ] **Step 1: 创建组件**

新建 `frontend/src/pages/Projects/competitorAnalysis/QuadrantChart.tsx`:

```tsx
import type { QuadrantPoint } from "../../../api/projects";

interface Props {
  points: QuadrantPoint[];
  selfAvg: number;
  competitorAvg: number;
}

export default function QuadrantChart({ points, selfAvg, competitorAvg }: Props) {
  const w = 760, h = 380, padL = 56, padR = 24, padT = 24, padB = 36;
  const innerW = w - padL - padR, innerH = h - padT - padB;
  const yMax = 1, xMax = 1;
  const x = (v: number) => padL + (v / xMax) * innerW;
  const y = (v: number) => padT + innerH - (v / yMax) * innerH;
  return (
    <svg className="quadrant-chart" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="xMidYMid meet">
      {/* axes */}
      <line className="axis-line" x1={padL} y1={padT} x2={padL} y2={padT + innerH} />
      <line className="axis-line" x1={padL} y1={padT + innerH} x2={w - padR} y2={padT + innerH} />
      {/* quadrant split lines (avg) */}
      <line className="ref-line" x1={x(selfAvg)} y1={padT} x2={x(selfAvg)} y2={padT + innerH} />
      <line className="ref-line" x1={padL} y1={y(competitorAvg)} x2={w - padR} y2={y(competitorAvg)} />
      {/* axis labels */}
      <text className="axis-label" x={w - padR} y={padT + innerH + 16} textAnchor="end">自身提及率</text>
      <text className="axis-label" x={padL - 8} y={padT - 8} textAnchor="end">竞品提及率</text>
      {/* quadrant quadrant labels */}
      <text className="quadrant-label" x={padL + innerW * 0.75} y={padT + 14} textAnchor="middle">优势区</text>
      <text className="quadrant-label" x={padL + innerW * 0.25} y={padT + innerH - 8} textAnchor="middle">劣势区</text>
      {/* points */}
      {points.map((p) => (
        <g key={p.platform}>
          <circle cx={x(p.self_mention_rate)} cy={y(p.competitor_avg_mention_rate)} r={6} fill="#1a55e8">
            <title>{`${p.platform}: 自身 ${(p.self_mention_rate * 100).toFixed(0)}% · 竞品均值 ${(p.competitor_avg_mention_rate * 100).toFixed(0)}%`}</title>
          </circle>
          <text className="point-label" x={x(p.self_mention_rate) + 9} y={y(p.competitor_avg_mention_rate) + 4}>
            {p.platform}
          </text>
        </g>
      ))}
    </svg>
  );
}
```

- [ ] **Step 2: 跑 typecheck**

Run: `cd frontend && pnpm run typecheck 2>&1 | tail -10`
Expected: 通过

- [ ] **Step 3: Commit**

```bash
cd /home/wangjh/projects/windx
git add frontend/src/pages/Projects/competitorAnalysis/QuadrantChart.tsx
git commit -m "feat(frontend): add QuadrantChart scatter component"
```

---

## Task 16: 前端 — DiffPane 用上 BarChart + QuadrantChart

**Files:**
- Modify: `frontend/src/pages/Projects/competitorAnalysis/DiffPane.tsx`

- [ ] **Step 1: 整文件覆盖**

```tsx
import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";
import BarChart from "./BarChart";
import QuadrantChart from "./QuadrantChart";

export default function DiffPane({ data }: { data: CompetitorAnalysisOut }) {
  const { diff_core, diff_model, diff_quadrant } = data;

  // 自身均值 + 竞品均值(用于四象限的参考线)
  const selfAvg = diff_model.length
    ? diff_model.reduce((s, m) => s + m.self_mention_rate, 0) / diff_model.length
    : 0;
  const competitorAvg = diff_model.length
    ? diff_model.reduce((s, m) => s + m.competitor_mention_rate, 0) / diff_model.length
    : 0;

  return (
    <div className="diff-grid">
      {/* 1. 核心指标对比 */}
      <div className="panel">
        <div className="panel-header">
          <h3>核心指标对比</h3>
          <p>自身 vs 竞品均值(总提及率 / Top1 / Top3)</p>
        </div>
        <div className="panel-body">
          {diff_core.labels.length === 0
            ? <Empty description="窗口内尚无对比数据" style={{ padding: 32 }} />
            : (
              <BarChart
                labels={diff_core.labels}
                series={[
                  { name: "自身", color: "#1a55e8", data: diff_core.self },
                  { name: "竞品均值", color: "#ff6b1a", data: diff_core.competitor_avg },
                ]}
                unit="%"
              />
            )}
        </div>
      </div>

      {/* 2. 模型维度提及率 */}
      <div className="panel">
        <div className="panel-header">
          <h3>模型维度提及率</h3>
          <p>{diff_model.length} 个模型 · 自身 vs 竞品均值</p>
        </div>
        <div className="panel-body">
          {diff_model.length === 0
            ? <Empty description="窗口内尚无模型维度数据" style={{ padding: 32 }} />
            : (
              <BarChart
                labels={diff_model.map((m) => m.platform)}
                series={[
                  { name: "自身", color: "#1a55e8", data: diff_model.map((m) => m.self_mention_rate * 100) },
                  { name: "竞品均值", color: "#ff6b1a", data: diff_model.map((m) => m.competitor_mention_rate * 100) },
                ]}
                unit="%"
              />
            )}
        </div>
      </div>

      {/* 3. 模型竞争四象限 */}
      <div className="panel panel-wide">
        <div className="panel-header">
          <h3>模型竞争四象限</h3>
          <p>X = 自身提及率 · Y = 竞品提及率(均值)· 分割线 = 各自均值</p>
        </div>
        <div className="panel-body">
          {diff_quadrant.length === 0
            ? <Empty description="窗口内尚无四象限数据" style={{ padding: 32 }} />
            : <QuadrantChart points={diff_quadrant} selfAvg={selfAvg} competitorAvg={competitorAvg} />}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: 跑 typecheck + lint**

Run: `cd frontend && pnpm run typecheck && pnpm run lint 2>&1 | tail -15`
Expected: 通过

- [ ] **Step 3: Commit**

```bash
cd /home/wangjh/projects/windx
git add frontend/src/pages/Projects/competitorAnalysis/DiffPane.tsx
git commit -m "feat(frontend): wire DiffPane with BarChart + QuadrantChart"
```

---

## Task 17: 前端 — CompetitorAnalysisTab 收尾 + 集中样式

**Files:**
- Modify: `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx`(末尾加 `<style>` 块)

- [ ] **Step 1: 在文件末尾加 style 块**

打开 `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx`,在最后一个 `}` 后加:

```tsx
      <style>{`
        .cna-root {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .cna-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
          padding: 12px 0;
        }
        .diff-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
          padding: 12px 0;
        }
        .diff-grid > .panel-wide { grid-column: span 2; }
        .panel {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          overflow: hidden;
          display: flex;
          flex-direction: column;
        }
        .panel-wide { grid-column: span 2; }
        .panel-header {
          padding: 14px 18px 10px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
          flex-wrap: wrap;
        }
        .panel-header h3 {
          margin: 0;
          font-size: 15px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .panel-header p {
          margin: 4px 0 0;
          font-size: 12px;
          color: var(--text-tertiary);
        }
        .panel-body { padding: 16px 18px; }
        .data-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }
        .data-table thead th {
          padding: 10px 12px;
          text-align: left;
          background: var(--bg-page, #fafafa);
          color: var(--text-secondary);
          font-weight: 500;
          font-size: 12px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .data-table .th-sub {
          font-weight: 400;
          color: var(--text-tertiary);
        }
        .data-table tbody td {
          padding: 10px 12px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .data-table-hover tbody tr:hover { background: var(--bg-hover, #fafafa); }
        .delta-up { color: var(--color-success, #16a34a); font-weight: 600; }
        .delta-down { color: var(--color-danger, #dc2626); font-weight: 600; }
        .delta-neutral { color: var(--text-tertiary); }

        .trend-legend {
          display: flex;
          flex-wrap: wrap;
          gap: 12px;
          align-items: center;
        }
        .trend-legend .legend-item {
          display: inline-flex;
          align-items: center;
          gap: 4px;
          font-size: 12px;
          color: var(--text-secondary);
        }
        .trend-legend .legend-swatch {
          display: inline-block;
          width: 10px;
          height: 10px;
          border-radius: 2px;
        }

        .trend-chart, .bar-chart, .quadrant-chart {
          width: 100%;
          height: 260px;
          display: block;
        }
        .trend-chart .grid-line,
        .bar-chart .grid-line { stroke: var(--border-light, #f0f0f0); }
        .trend-chart .axis-label,
        .bar-chart .axis-label,
        .quadrant-chart .axis-label {
          fill: var(--text-quaternary);
          font-size: 10px;
        }
        .trend-chart .line { fill: none; stroke-width: 2; }
        .trend-chart .dot { stroke: #fff; stroke-width: 1; }
        .quadrant-chart .axis-line { stroke: var(--text-tertiary); stroke-width: 1; }
        .quadrant-chart .ref-line {
          stroke: var(--text-quaternary);
          stroke-dasharray: 4 4;
          stroke-width: 1;
        }
        .quadrant-chart .quadrant-label {
          fill: var(--text-tertiary);
          font-size: 11px;
        }
        .quadrant-chart .point-label {
          fill: var(--text-secondary);
          font-size: 11px;
        }
      `}</style>
```

- [ ] **Step 2: 跑 typecheck + lint**

Run: `cd frontend && pnpm run typecheck && pnpm run lint 2>&1 | tail -15`
Expected: 通过

- [ ] **Step 3: Commit**

```bash
cd /home/wangjh/projects/windx
git add frontend/src/pages/Projects/CompetitorAnalysisTab.tsx
git commit -m "feat(frontend): add shared styles for CompetitorAnalysisTab"
```

---

## Task 18: 前端 — dev server 手动验证

- [ ] **Step 1: 启动 dev server**

Run: `cd /home/wangjh/projects/windx/frontend && pnpm run dev`
Expected: 服务在 5173 端口启动(后台)

- [ ] **Step 2: 浏览器检查(用 document-skills:webapp-testing 或手动)**

1. 登录后选一个有 ≥ 2 个竞品 + ≥ 1 个项目的账号
2. 进入项目 → 切到「竞品分析」tab
3. 验证:
   - 顶部 3 个 tab(全部竞品 / 趋势对比 / 差异化分析)可切换
   - 「全部竞品」:8 列表格渲染,Top1 / 情感三档 / 环比变化都有数值或 `—`
   - 「趋势对比」:折线图渲染,显示完整日期范围
   - 「差异化分析」:核心指标柱状图 + 模型维度柱状图 + 四象限散点图渲染
   - 浏览器 console 无 error
4. **回归:** 整页不含「竞争优势矩阵」「差异化标签云」「关注点」「新增竞品」任何文案

- [ ] **Step 3: 关停 dev server**

```bash
# 找到 dev server 进程,kill
ps aux | grep "pnpm run dev" | grep -v grep | awk '{print $2}' | xargs kill
```

---

## Task 19: 后端 + 前端 全套验证

- [ ] **Step 1: 后端 pytest 全套**

Run: `cd backend && uv run pytest -q`
Expected: 全 PASS

- [ ] **Step 2: 前端 typecheck + lint**

Run: `cd frontend && pnpm run typecheck && pnpm run lint`
Expected: 全 PASS

- [ ] **Step 3: 健康冒烟**

```bash
curl -s -X POST http://localhost:18083/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"<你的账号>","password":"<密码>"}' | jq -r .data.token > /tmp/token
curl -s -H "Authorization: Bearer $(cat /tmp/token)" \
  "http://localhost:18083/api/projects/1/competitor-analysis?days=15" | jq '{
    has_diff_core: (.diff_core.labels | length > 0),
    has_diff_model: (.diff_model | length > 0),
    has_diff_quadrant: (.diff_quadrant | length > 0),
    has_previous_window: (.previous_window_start != null),
    no_concern_tags: (has("concern_tags") | not),
    kpi_top1: .self_brand.top1_rate,
    kpi_sent_pos: .self_brand.sentiment_positive,
  }'
```

Expected: 5 个断言全部 `true`,`kpi_top1` 是 0-1 数字,`kpi_sent_pos` 是 0-1 数字。

- [ ] **Step 4: 提交(若上一步有 fix)**

如有 fix 改动,commit;没有则跳过。

---

## 验收清单

- [ ] 后端 `compute_competitor_analysis` 返回 `CompetitorAnalysisOut` 包含全部新字段(top1 / 情感三档 / 4 deltas / diff_core / diff_model / diff_quadrant / previous_window_*),不含 `concern_tags`
- [ ] 后端 `/projects/{id}/competitor-analysis` endpoint 仍工作,行为对前端透明
- [ ] 后端 pytest 全套通过(包括 4 个新测试)
- [ ] 前端 `CompetitorAnalysisTab` 渲染 3 个 sub-tab + 6 个 panel
- [ ] 前端 8 列概览表 + 4 个环比指示
- [ ] 前端 TrendChart(15 天 + 完整版) / BarChart / QuadrantChart 三个图表组件渲染正确
- [ ] 前端 typecheck + lint 通过
- [ ] 浏览器验证:页面无 console error;无旧文案(竞争优势矩阵 / 差异化标签云 / 关注点 / 新增竞品)残留