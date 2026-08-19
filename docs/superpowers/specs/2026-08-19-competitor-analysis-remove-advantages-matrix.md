# 竞品分析页 — 整页重构(按 docs/更新版UI)

- 日期: 2026-08-19
- 状态: 已与用户确认,待实施
- 范围: 后端 `backend/app/services/competitor_analysis.py`(新)+ `backend/app/api/projects.py`(瘦身)+ `backend/app/schemas/project.py`;前端 `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx`(整页重写)

---

## Context

`CompetitorAnalysisTab` 当前实现 4 个 panel:

1. 竞品概览(全宽表格)
2. 提及趋势对比(全宽 SVG 折线)
3. 差异化标签云(半宽,基于 `concern_hits_json` 聚合)
4. 竞争优势矩阵(半宽,「客户关注点」表占位)

`docs/更新版UI/index.html` 的新版 竞品分析(`#tab-competitor`)结构:

| 二级 Tab | panel |
|---|---|
| 全部竞品 | (input-hint-panel — **本次不接入**) + 竞品概览 + 提及趋势对比(15 天) |
| 趋势对比 | 完整提及趋势对比 |
| 差异化分析 | 核心指标对比 + 模型维度提及率 + 模型竞争四象限 |

新设计 **没有** 「差异化标签云」「竞争优势矩阵」「input-hint-panel」「新增竞品」按钮。

后端 `GET /projects/{id}/competitor-analysis` 当前返回的 `CompetitorAnalysisOut` 字段不够支撑新设计的「差异化分析」三图表 — 缺 Top1 rate、情感三档分布、环比、per-platform(自身 vs 竞品均值)、四象限数据。本次一并扩展后端,字段口径与现有 KPI(mention_rate / top3_rate / avg_sentiment)一致 — 不引入新口径。

## 目标

1. 后端:把竞品分析整块计算从 `api/projects.py` 抽到 `services/competitor_analysis.py`(`按页面分开`),扩展 `CompetitorAnalysisOut` schema 字段,支撑新设计。
2. 前端:`CompetitorAnalysisTab` 改为 3 个二级 tab + 6 个 panel,删除「差异化标签云」「竞争优势矩阵」。
3. 不引入「input-hint-panel」「新增竞品」按钮(本期不接入关注点功能)。

## 非目标

- 不动 `CompetitorsTab`(竞品管理 CRUD)。
- 不动 `geo_brand_mentions` 数据库 schema(`sentiment_score` 已是离散 label,可直接 GROUP BY)。
- 不引入 Redis / React Query / 新依赖。
- 不改路由 / `Detail.tsx` / `ProjectContext`。
- 不引入「客户关注点」功能(无后端表)。

---

## 决策摘要

| 议题 | 决定 |
|---|---|
| 后端文件拆分 | 新建 `backend/app/services/competitor_analysis.py`,收纳所有竞品分析计算。`api/projects.py` 里的 endpoint 缩为薄壳调用 service |
| Schema 扩展位置 | 仍在 `backend/app/schemas/project.py`(与现有 KPI 同文件,保持 schema 一致性) |
| 情感三档来源 | `geo_brand_mentions.sentiment_score` 离散 label,GROUP BY 直接统计 |
| 环比窗口 | 同长度上一窗口(`[win_start - days_n, win_start - 1]`);窗口太短(< 7 天)无法计算则置 `None` |
| per-platform 聚合 | GROUP BY `platform, is_self`;每个平台一行,自身/竞品均值 |
| 四象限 | 从 per-platform 聚合抽 `platform, self_mention_rate, competitor_mention_rate` |
| 概览表格删除 | 「差异化标签云」「竞争优势矩阵」 |
| 概览表格新增 | Top1 / 情感三档 / 环比四列 |
| 二级 Tab 组件 | antd `<Tabs>`,本地 state,不写 URL |
| 图表组件 | 纯 SVG,与现有 TrendChart 风格一致 |
| 删除 imports | `ThunderboltFilled`、`tagFontSize` helper、`.tag-cloud` CSS |

---

## 1. 后端 — Schema 扩展

**文件:** `backend/app/schemas/project.py`

### 1.1 `CompetitorKpi` 扩展

```python
class CompetitorKpi(BaseModel):
    # — 现有字段保留 —
    brand_canonical: str
    name: str
    aliases: list[str] | None
    is_self: bool
    mention_count: int
    mention_rate: float
    top3_rate: float
    recommend_rate: float
    avg_sentiment: float | None
    avg_rank: float | None
    spark: list[int]
    # — 新增 —
    top1_rate: float                              # 1.0 * top1_hits / total_subtasks
    sentiment_positive: float                     # 1.0 * count(sentiment='positive', mention_count>0) / matched_count
    sentiment_neutral: float
    sentiment_negative: float
    # 环比 vs 同长度上一窗口;窗口太短或数据不足以计算时 None
    mention_rate_delta: float | None
    top1_rate_delta: float | None
    top3_rate_delta: float | None
    sentiment_delta: float | None                 # avg_sentiment 差值
```

口径说明:`sentiment_positive/neutral/negative` 分母 = `mention_count > 0` 的行数(即"被真正提到过的样本"),不是全部 `total_subtasks`。这样空品牌不会被稀释。

### 1.2 新增 `QuadrantPoint` / `ModelDiff`

```python
class QuadrantPoint(BaseModel):
    platform: str
    self_mention_rate: float
    competitor_avg_mention_rate: float            # 所有竞品的均值,不是单品牌


class ModelDiff(BaseModel):
    platform: str
    self_mention_rate: float
    self_top1_rate: float
    self_top3_rate: float
    competitor_mention_rate: float
    competitor_top1_rate: float
    competitor_top3_rate: float
```

### 1.3 `CompetitorAnalysisOut` 扩展 + 删除

```python
class CompetitorAnalysisOut(BaseModel):
    # — 现有字段保留 —
    project_id: int
    start: date
    end: date
    days: int
    total_subtasks: int
    self_brand: CompetitorKpi | None
    competitors: list[CompetitorKpi]
    trend: CompetitorTrendBlock
    # — 新增 —
    diff_core: dict                               # {"labels":["提及率","Top1","Top3"],"self":[...],"competitor_avg":[...]}
    diff_model: list[ModelDiff]
    diff_quadrant: list[QuadrantPoint]
    previous_window_start: date | None
    previous_window_end: date | None
    # — 删除 —
    # concern_tags: list[ConcernTag]                # 不再需要,前端不渲染
```

## 2. 后端 — Service 层

**新建文件:** `backend/app/services/competitor_analysis.py`

收纳以下内容(从 `api/projects.py` 行 2092-2435 搬过来 + 新加):

| 符号 | 现有/新增 | 说明 |
|---|---|---|
| `_resolve_competitor_window` | 现有 | 从 projects.py 搬过来 |
| `compute_competitor_analysis` | 新(主入口) | 旧 endpoint body,搬过来并扩展 |
| `_kpi_for` | 现有 + 扩展 | 加 top1_rate / 情感三档 / 4 个 delta |
| `_compute_previous_window` | 新 | 在 `[win_start - days_n, win_start - 1]` 上跑同 SELECT/GROUP BY,返回 per-brand dict |
| `_compute_diff_core` | 新 | 从 self_kpi + competitor_kpis 算 3 指标 |
| `_compute_diff_model` | 新 | GROUP BY platform, is_self 算 per-platform 自/竞品均值 |
| `_compute_diff_quadrant` | 新 | 从 _compute_diff_model 抽 |
| `_COMPETITOR_LINE_COLORS` | 现有 | 从 projects.py 搬过来 |

### 2.1 SQL 改动

**`_kpi_for` 内部 SELECT 增量:**

```sql
-- 现有 — 保留
SUM(CASE WHEN mention_count>0 THEN 1 ELSE 0 END) AS matched
AVG(CASE WHEN mention_count>0 THEN ... ELSE NULL END) AS avg_sentiment
SUM(CASE WHEN mention_count>0 AND rank_position<=3 THEN 1 ELSE 0 END) AS top3_hits
SUM(CASE WHEN mention_count>0 AND is_recommended THEN 1 ELSE 0 END) AS rec_hits
-- 新增
SUM(CASE WHEN mention_count>0 AND rank_position=1 THEN 1 ELSE 0 END) AS top1_hits
SUM(CASE WHEN mention_count>0 AND sentiment_score='positive' THEN 1 ELSE 0 END) AS sent_pos
SUM(CASE WHEN mention_count>0 AND sentiment_score='neutral' THEN 1 ELSE 0 END) AS sent_neu
SUM(CASE WHEN mention_count>0 AND sentiment_score='negative' THEN 1 ELSE 0 END) AS sent_neg
```

`_kpi_for` 中算:
```python
top1_rate = top1_hits / total_subtasks if total_subtasks else 0.0
denom = matched if matched else 1                       # 防 0 除
sentiment_positive = sent_pos / denom
sentiment_neutral = sent_neu / denom
sentiment_negative = sent_neg / denom
```

### 2.2 `_compute_previous_window` 增量

```python
def _compute_previous_window(
    db: Session, project_id: int,
    win_start: date, win_end: date,
) -> dict[str, dict[str, float]]:
    """Same SELECT/GROUP BY as the current window, but on [win_start - days_n, win_start - 1].
    Returns {brand_canonical: {mention_rate, top1_rate, top3_rate, avg_sentiment}}.
    Window too short (< 7 days) → returns {}.
    """
    days_n = (win_end - win_start).days + 1
    prev_end = win_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days_n - 1)
    # 复用 compute 逻辑,但不返回完整 KPI,只取 4 个 rate
    ...
```

调用点:`_kpi_for` 收到 previous_window dict 后算 4 个 delta:
```python
prev = prev_by_brand.get(brand, {})
mention_rate_delta = mention_rate - prev.get("mention_rate") if prev else None
# top1/top3/sentiment 同上
```

### 2.3 `_compute_diff_core`

```python
def _compute_diff_core(self_kpi, competitor_kpis) -> dict:
    if not self_kpi or not competitor_kpis:
        return {"labels": ["提及率","Top1","Top3"], "self": [0,0,0], "competitor_avg": [0,0,0]}
    n = len(competitor_kpis)
    return {
        "labels": ["提及率","Top1","Top3"],
        "self": [self_kpi.mention_rate * 100, self_kpi.top1_rate * 100, self_kpi.top3_rate * 100],
        "competitor_avg": [
            sum(c.mention_rate for c in competitor_kpis) / n * 100,
            sum(c.top1_rate for c in competitor_kpis) / n * 100,
            sum(c.top3_rate for c in competitor_kpis) / n * 100,
        ],
    }
```

(乘 100 是 UI 友好,前端拿到的是 0-100 区间百分数)

### 2.4 `_compute_diff_model`

```python
def _compute_diff_model(db, project_id, win_start_dt, win_end_dt) -> list[ModelDiff]:
    rows = db.execute(
        select(
            BrandMention.platform,
            BrandMention.is_self,
            func.count(func.distinct(BrandMention.subtask_id)).label("total"),
            func.sum(case((and_(BrandMention.mention_count>0, BrandMention.rank_position==1), 1), else_=0)).label("top1"),
            func.sum(case((and_(BrandMention.mention_count>0, BrandMention.rank_position.is_not(None), BrandMention.rank_position<=3), 1), else_=0)).label("top3"),
            func.sum(case((BrandMention.mention_count>0, 1), else_=0)).label("matched"),
        )
        .where(
            BrandMention.project_id == project_id,
            BrandMention.created_at >= win_start_dt,
            BrandMention.created_at <= win_end_dt,
            BrandMention.platform.is_not(None),
        )
        .group_by(BrandMention.platform, BrandMention.is_self)
    ).all()
    # 按 platform 聚合 self / competitor
    ...
```

每平台分别给 self 与 competitor 的 mention/top1/top3 rate(分母 = 该平台 distinct subtask 数)。

### 2.5 删除

- `concern_tags` 整段 SQL + Counter 聚合 + cls 分桶逻辑 + ConcernTag return
- `_COMPETITOR_LINE_COLORS` 从 projects.py 搬走

## 3. 后端 — API 瘦身

**文件:** `backend/app/api/projects.py`

1. 删除(已搬走):
   - `_resolve_competitor_window`
   - `_COMPETITOR_LINE_COLORS`
   - `competitor_analysis()` 函数体
2. endpoint 变为薄壳:

```python
@router.get("/projects/{project_id}/competitor-analysis", response_model=CompetitorAnalysisOut)
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
        db=db,
        project_id=project_id,
        project=project,
        days=days,
        start=start,
        end=end,
    )
```

3. import:加 `from app.services.competitor_analysis import compute_competitor_analysis`

## 4. 后端 — 测试更新

**文件:** `backend/tests/test_competitor_and_extensions_api.py`

1. 更新现有 `competitor_analysis` 断言:
   - `concern_tags` 不再在响应里(改为断言它不存在 / 删除相关断言)
   - 新增 `diff_core` / `diff_model` / `diff_quadrant` / `previous_window_*` 字段存在断言
2. 新增字段断言:
   - `top1_rate` / `sentiment_positive/neutral/negative` 在 self_brand + 每个 competitor 里都存在且在 [0, 1] 区间
   - 环比字段存在(可 None)
   - `diff_core.self` 与 self_brand.mention_rate 数值一致(口径校验)
3. 不需要 alembic 迁移(无 DB schema 变化)

## 5. 前端 — 整页重构

**文件:** `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx`

### 5.1 类型扩展 (`frontend/src/api/projects.ts`)

```ts
// 在 CompetitorKpi 上加
top1_rate: number
sentiment_positive: number
sentiment_neutral: number
sentiment_negative: number
mention_rate_delta: number | null
top1_rate_delta: number | null
top3_rate_delta: number | null
sentiment_delta: number | null

// 新增
interface QuadrantPoint { platform: string; self_mention_rate: number; competitor_avg_mention_rate: number }
interface ModelDiff {
  platform: string
  self_mention_rate: number
  self_top1_rate: number
  self_top3_rate: number
  competitor_mention_rate: number
  competitor_top1_rate: number
  competitor_top3_rate: number
}

// CompetitorAnalysisOut 加
diff_core: { labels: string[]; self: number[]; competitor_avg: number[] }
diff_model: ModelDiff[]
diff_quadrant: QuadrantPoint[]
previous_window_start: string | null
previous_window_end: string | null
// 删 concern_tags
```

### 5.2 组件结构

```
CompetitorAnalysisTab
├─ <Tabs activeKey, onChange>(本地 useState)
│   ├─ Tab "all"   → <AllCompetitorsPane/>
│   ├─ Tab "trend" → <TrendFullPane/>
│   └─ Tab "diff"  → <DiffPane/>
└─ <Spin> 包裹数据加载
```

三个 sub-pane 拆成内部组件(同文件),共享 useState/useEffect 数据。

### 5.3 「竞品概览」表格

| 列 | 数据源 |
|---|---|
| 品牌 | `self_brand.name` + 自身 Tag,`competitor[].name` |
| 提及率 | `mention_rate` |
| Top1 | `top1_rate` |
| Top3 | `top3_rate` |
| 情感-正向 | `sentiment_positive` |
| 情感-中性 | `sentiment_neutral` |
| 情感-负面 | `sentiment_negative` |
| 环比变化(4 列) | `mention_rate_delta` / `top1_rate_delta` / `top3_rate_delta` / `sentiment_delta` |

合并行表头:首行 `<th rowspan="2">` 品牌/Top3/Top1/三档;`<th colspan="4">` 环比变化。次行 `<th class="th-sub">` 4 个环比指标名。视觉上对齐新设计。

环比显示规则:`> 0` 绿色 ▲,`< 0` 红色 ▼,`= 0` 灰色 —,`null` 灰色 —。

### 5.4 「趋势对比」完整版

复用现有 `TrendChart` 组件,把 `labels` / `series` 直接传入。panel 副标题显示「YYYY-MM-DD ~ YYYY-MM-DD · 共 N 天」(从 `data.start/end/days`)。

### 5.5 「差异化分析」三个图表

新增两个 SVG 组件:

**`BarChart`** — 分组柱状图,通用:
- 入参:`labels: string[]`, `series: { name, color, data: number[] }[]`, `yMax?: number`, `unit?: string`
- 输出:每个 label 一组 N 根并列柱 + 图例 + y 轴刻度
- 用法 1:核心指标对比 — labels=`['提及率','Top1','Top3']`, series=`[{name:'自身',color,data},{name:'竞品均值',color,data}]`
- 用法 2:模型维度提及率 — labels=`platform[]`, series=`[{name:'自身·提及率',data},{name:'竞品均值·提及率',data}]`(或拆成 6 series)

**`QuadrantChart`** — 散点图:
- 入参:`points: QuadrantPoint[]`, `selfAvg: number`, `competitorAvg: number`
- 输出:散点 + X 自身均值虚线 + Y 竞品均值虚线 + 4 个象限文案(左上/右上/左下/右下)+ 每个点的 platform 标签
- 用法:模型竞争四象限

### 5.6 删除

- 「竞争优势矩阵」panel 整块 + `<style>` 中对应死代码(检查后)
- 「差异化标签云」panel 整块 + `tagFontSize` helper + `<style>` 中 `.tag-cloud*` 全部规则 + `import { ConcernTagCls }` 不用类型
- `import { ThunderboltFilled }`(仅占位 panel 用)
- `concern_tags` 在数据解构处的引用

### 5.7 不动

- `Sparkline`(用在「竞品概览」表格里的 15 日 sparkline)— 保留
- `TrendChart` 组件本身(复用)
- `<style>` 块里 `.cna-root / .cna-grid / .panel / .panel-wide / .panel-header* / .data-table* / .rate-* / .trend-* / .trend-chart*` 全部保留(都被引用)
- `useEffect` 数据加载逻辑(URL 仍传 `projectId`)
- `<Skeleton>` / `<Empty>` 加载与空态处理

## 6. 验证

1. **后端:**
   - `uv run pytest -q` 全部通过;新断言生效
   - `curl /projects/{id}/competitor-analysis` 看新字段齐全、`diff_core.self[0]` 与 `self_brand.mention_rate*100` 数值一致
2. **前端:**
   - `pnpm run typecheck && pnpm run lint` 通过
   - dev server 切到「竞品分析」tab:3 个 sub-tab 切换;8 列表格;2 个折线图(15 天 + 完整);1 个核心指标柱状图;1 个模型维度柱状图;1 个四象限散点图;无 console error
3. **视觉:** 面板顺序 / 列名 / 二级 tab 文案与 `docs/更新版UI/index.html #tab-competitor` 一致
4. **回归:** 「竞争优势矩阵」「差异化标签云」「关注点」「新增竞品」任何文案都不出现在页面

## 7. 风险

- 中。后端 SELECT 增加列,可能让 dashboard 慢一点;per-platform 聚合是新查询。建议在 PR 描述里附项目 2 / 项目 3 实测耗时。
- 前端 8 列表格在窄屏可能溢出;新设计里也是 8 列,UI 自带横向滚动,不需额外处理。

## 8. 后续(不在本次范围)

- 「客户关注点」功能如未来要落地,需新建 focus_points 表 + 后端聚合接口 + 恢复「竞争优势矩阵」panel + 新版「编辑关注点」按钮
- 「完整提及趋势对比」目前与「15 天趋势对比」共用 TrendChart,只是窗口更长。若以后需要按模型筛选,需扩展入参(目前 `competitor_analysis` 接口无 models 参数,沿用现状)