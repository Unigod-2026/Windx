# 信源偏好页 — MVP(按 docs/更新版UI Tab 4「全部信源」)

- 日期: 2026-08-19
- 状态: 已与用户确认,待实施
- 范围: 后端 `backend/app/services/source_preferences.py`(新)+ `backend/app/api/projects.py`(新增 endpoint)+ `backend/app/schemas/project.py`(新增 schema);前端 `frontend/src/pages/Projects/SourcePreferencesTab.tsx`(新)+ `frontend/src/api/projects.ts`(新增 client)+ `frontend/src/pages/Projects/Detail.tsx`(替换 PlaceholderTab)

---

## Context

`Detail.tsx` 当前把 `?tab=source` 路由到 `PlaceholderTab`,提示文案是「每个大模型引用最多的信源类型 TOP3 + 信源异动」。本次把这个占位换成实际页面。

`docs/更新版UI/index.html` Tab 4「信源偏好」有 5 个二级 tab(全部信源 / 信源明细 / 自有文章 / 网站分类 / 视频类信源)+ 十几个图表 / 列表 + KPI 行。

`backend/app/api/projects.py` 已有 `GET /api/projects/{id}/citation-analysis` 端点,数据源是 `Subtask.citation_list_json` —— 这是「模型在回答正文里实际引用的子集」,**不是**用户要求的字段。`Subtask.reference_list_json` 是「模型完整可用的信源池」,生产数据里全部是 `{url, site, title}` 字典(已通过采样验证)。本次要新建端点读 `reference_list_json`。

类型分类已有 `_CITATION_DOMAIN_RULES`(官方 / 新闻 / 垂类 / 社交媒体 / 百科 / 自媒体 / 海外 / 其他),由 host 子串匹配,本次直接复用 —— 不引入新字典。

`ProjectContext` 已经在 `OverviewTab` 等地方承载当前项目 ID;`Detail.tsx` 的 `case "source"` 是替换点。

## 目标

1. **后端**:新增 `GET /api/projects/{id}/source-preferences?days=15`,沿用 `citation-analysis` 的窗口口径(`Task.project_id` + `Task.created_local_at`),但数据源是 `Subtask.reference_list_json`;返回 5 块(`kpi` + `type_counts` + `platform_slices` + `top_sources` + `trend`)。
2. **前端**:新增 `SourcePreferencesTab.tsx` 单页(KPI + 饼图 + 柱状图 + Top 表 + 双折线),替换 `Detail.tsx` 里 `case "source":` 的 PlaceholderTab。
3. **复用**:分类规则用 `_CITATION_DOMAIN_RULES`;图表渲染用 `frontend/src/components/EChart`;不引入新依赖。
4. **数据口径**:Top 表前 50;趋势序列按窗口内每日;KPI 4 个(`total_references` / `unique_urls` / `cross_platform_urls` / `avg_refs_per_subtask`);饼图按类型;柱状图按模型。

## 非目标

- **不**做 5 个二级 tab 中除「全部信源」外的 4 个 —— `信源明细 / 自有文章 / 网站分类 / 视频类信源` 继续是 PlaceholderTab(后续单独排期)。
- **不**接 DR / 流量 / 排名位置 —— 无外部 API,不展示这些字段。
- **不**做品牌 ↔ 域名映射 —— 没有官方信源字典,「官方信源对比」面板本期不做。
- **不**做 iframe 内嵌预览 / 左右分屏 —— 详情链接用 `<a target="_blank">` 外链打开。
- **不**改 `citation-analysis` 端点 / `CitationAnalysisOut` schema —— 用户明确要读 `reference_list_json`,走新端点。
- **不**改 `geo_subtasks.reference_list_json` 字段定义 / 不引入 alembic migration。
- **不**做天数下拉 —— 跟现状保持一致,后端默认 `days=15`,前端不提供 UI 切换(以后接入 ProjectContext 全局天数时再补)。
- **不**做缓存 / 增量更新 —— 跟 `citation-analysis` 一样,每次请求实时聚合。

---

## 决策摘要

| 议题 | 决定 |
|---|---|
| 数据源 | `Subtask.reference_list_json`,过滤口径与 `citation-analysis` 一致 |
| 分类规则 | 复用 `_CITATION_DOMAIN_RULES`,host 子串匹配,无匹配 → 「其他」 |
| 跨模型共享信源数 | 唯一 URL 中 `len(platforms) >= 2` 的条数 |
| 变化趋势算法 | 按日累计 unique-URL 集合,做相邻日 set diff;`new_urls = today_set - prev_set`,`lost_urls = prev_set - today_set` |
| KPI「平均每条 subtask 引用数」 | `total_references / total_subtasks`,分母是窗口内 `reference_list_json` 非空的 subtask 数 |
| Top 表长度 | 前 50,按 `count` 倒序,ties 按 `last_seen` desc |
| 窗口默认 / 上限 | 跟 `citation-analysis` 一致:`days=15` 默认,1-90 区间 |
| 端点位置 | `backend/app/api/projects.py`,跟 `citation_analysis` 同文件、同风格 |
| 计算逻辑落点 | 新建 `backend/app/services/source_preferences.py`,跟 `competitor_analysis` 一样的「按页面分开」模式 |
| 前端组件 | 单文件 `SourcePreferencesTab.tsx`,沿用 `EChart` + echarts donut/bar/line + AntD Table |
| 全局样式 | 沿用现有 `.cna-*` / `.panel*` 样式;新增 `.sp-*` 命名空间,避免与现有竞品分析冲突 |

---

## 后端设计

### 端点

```
GET /api/projects/{project_id}/source-preferences?days=15
Authorization: Bearer <jwt>
→ 200 SourcePreferenceOut
→ 400 days 越界
→ 401/403 鉴权
→ 404 项目不存在
```

### 计算函数(`backend/app/services/source_preferences.py`)

```python
def compute_source_preferences(
    *, db, project_id: int, days: int = 15,
) -> SourcePreferenceOut:
```

流程:

1. **窗口解析** —— 复用 `api.projects._resolve_competitor_window(days, None, None)`,不重复造。
2. **拉数据** —— 单次 `SELECT subtask_id, platform, reference_list_json, created_local_at` 跨 `Task`,过滤窗口。
3. **逐 subtask 拆 reference_list_json** —— 仅处理 dict 形态(`url` / `site` / `title`),字符串 / None 跳过(与 `citation-analysis` 一致的安全策略)。
4. **聚合**:
   - `total_subtasks` = 窗口内 `reference_list_json` 非空(拆出至少 1 条)的 subtask 数
   - `total_references` = 拆出的有效 dict 总条数
   - `buckets[url] = {site, title, count, platforms: set, first_seen, last_seen}`
   - `platform_slices[platform] = {total_refs, unique_urls}`
   - `type_counts` = 用 `_classify_citation(host)` 跑一遍 host → 计数
   - `unique_urls` = `len(buckets)`
   - `cross_platform_urls` = `sum(1 for b in buckets.values() if len(b["platforms"]) >= 2)`
5. **趋势** —— 用 `daily_urls: dict[date, set[str]]` 收集每日首次出现的 URL;按日期排序后做相邻日 set diff:
   - `new_urls[d] = len(daily_urls[d] - daily_urls[d-1])`(窗口第一天 `new_urls = len(daily_urls[d])`)
   - `lost_urls[d] = len(daily_urls[d-1] - daily_urls[d])`(窗口最后一天 `lost_urls = 0`)
6. **Top 50** —— 按 `count desc, last_seen desc` 排序,取前 50。

### Schema(`backend/app/schemas/project.py` 新增)

```python
class SourcePreferenceKpi(BaseModel):
    total_references: int
    unique_urls: int
    cross_platform_urls: int
    avg_refs_per_subtask: float
    total_subtasks: int

class SourceTypeSlice(BaseModel):
    type: str
    count: int

class SourcePlatformSlice(BaseModel):
    platform: str
    total_refs: int
    unique_urls: int

class SourceTrendDay(BaseModel):
    date: date
    new_urls: int
    lost_urls: int

class SourcePreferenceItem(BaseModel):
    url: str
    site: str
    title: str | None
    type: str
    count: int
    platforms: list[str]
    first_seen: datetime
    last_seen: datetime

class SourcePreferenceOut(BaseModel):
    project_id: int
    start: date
    end: date
    days: int
    kpi: SourcePreferenceKpi
    type_counts: list[SourceTypeSlice]
    platform_slices: list[SourcePlatformSlice]
    top_sources: list[SourcePreferenceItem]
    trend: list[SourceTrendDay]
```

### API 客户端(`frontend/src/api/projects.ts` 新增)

```typescript
export interface SourcePreferenceKpi { ... }
export interface SourceTypeSlice { type: string; count: number; }
export interface SourcePlatformSlice { platform: string; total_refs: number; unique_urls: number; }
export interface SourceTrendDay { date: string; new_urls: number; lost_urls: number; }
export interface SourcePreferenceItem { ... }
export interface SourcePreferenceOut { ... }

export function getSourcePreferences(projectId: number, days = 15): Promise<SourcePreferenceOut>
```

---

## 前端设计

### 文件结构

- `frontend/src/pages/Projects/SourcePreferencesTab.tsx` — 新文件,主组件
- `frontend/src/pages/Projects/Detail.tsx` — 改 `case "source":` 路由到新组件
- `frontend/src/api/projects.ts` — 加 client / 类型

### 布局(单页,从上到下)

```
┌─ KPI 行(4 张卡片) ──────────────────────────────────┐
│  总引用 / 唯一信源 / 跨模型共享 / 平均每条引用数      │
└────────────────────────────────────────────────────┘
┌─ 行 1(两栏) ─────────────────────────────────────┐
│  信源分类饼图(echarts donut)  │  按模型引用柱状图  │
└────────────────────────────────────────────────────┘
┌─ 行 2(全宽) ──────────────────────────────────────┐
│  信源引用 Top 50 表格                              │
│  # | URL | title | 类型 | 引用数 | 平台 | 最近     │
└────────────────────────────────────────────────────┘
┌─ 行 3(全宽) ──────────────────────────────────────┐
│  信源变化趋势 — 新增 / 流失 双折线(每日)            │
└────────────────────────────────────────────────────┘
```

### 交互

- 表格行可点击 URL → 新窗口打开(`<a target="_blank" rel="noopener noreferrer">`)
- 「平台」列渲染为 chip 数组(沿用 `.legend-chip` 样式)
- 「类型」列渲染为彩色 chip(沿用更新版UI 的 `typeColor` 方案:官方=蓝 / 新闻=绿 / 垂类=青 / 社交=紫 / 自媒体=橙 / 百科=蓝 / 海外=红 / 其他=灰)
- 空态:任何聚合为空时显示 `Empty description="窗口内尚无信源数据"`

### 样式

- 容器根类名 `sp-root`
- 沿用现有 `.panel*` / `.data-table*` 样式(已在 `CompetitorAnalysisTab.tsx` 内 inline);新增少量 `.sp-*` 用于本页特有元素(KPI 卡片、趋势线图样式)
- 命名空间隔离:不引入 `cna-*` 类(那是竞品分析的)

### 数据空态与错误

- HTTP 失败 → `message.error(...)` + Empty
- 数据为空(总引用 = 0) → 「窗口内尚无信源数据」

---

## 关键边界与回归保证

1. **API 契约** —— 响应字段名、类型与 spec §后端设计 一致;新增端点不影响现有 `citation-analysis`。
2. **跨模型共享信源数** —— 同 URL 被 ≥2 个 platform 引用时,`platforms` 数组含 ≥2 个元素,`cross_platform_urls` 才计数;不要把单平台多次引用算成「跨模型」。
3. **趋势 diff** —— 边界日(窗口第一天 / 最后一天)的 `new_urls` / `lost_urls` 不要假数据;按 set diff 实际算,首日无前一日 → `new_urls = len(daily_urls[d])`、`lost_urls = 0`;末日无后一日 → `lost_urls = 0`(实际是「窗口最后一天没流失,可能明天才流失」,这是合理的)。
4. **Top 表排序 tie-break** —— `count` 相同时按 `last_seen desc`,确保「最近还在被引用的信源」排前面。
5. **平台列去重** —— `platforms` 是 `set`,序列化前 `sorted()`;前端不再次去重。
6. **host 分类** —— 走 `_classify_citation(host)`,host = `site or url`,与现有端点完全一致,避免「同一 URL 在两个端点里被分到不同 type」的诡异 bug。
7. **不修改 `reference_list_json` 字段** —— 仅 SELECT,不写,不引入 alembic。
8. **不修改 `Detail.tsx` 其他分支** —— 只动 `case "source":`,其它分支保持不变。
9. **不引入新依赖** —— 用现有 `echarts` / `antd` / `dayjs` 即可。

---

## 测试策略

### 后端(`backend/tests/test_source_preferences_api.py` 新文件)

- **`test_schema_field_presence`** —— `SourcePreferenceOut` 含 kpi / type_counts / platform_slices / top_sources / trend;`SourcePreferenceItem` 含 url / site / title / type / count / platforms / first_seen / last_seen。
- **`test_empty_window`** —— 没 subtask 时,所有计数为 0,top_sources / trend / type_counts / platform_slices 都是空列表,HTTP 200。
- **`test_kpi_basic_aggregation`** —— 1 个 subtask,reference_list_json 含 3 条 URL(A/B/C),其中 A 被 1 个 platform 引用,B 被 2 个 platform 引用 → `total_references=3, unique_urls=3, cross_platform_urls=1, avg_refs_per_subtask=3.0`。
- **`test_type_counts_uses_domain_rules`** —— seed zhihu.com(垂类) + people.com.cn(新闻) + 无匹配的 `random-site-xyz.com` → type_counts 应含 `{"垂类论坛": 1, "新闻网站": 1, "其他": 1}`(以 `_CITATION_DOMAIN_RULES` 实际返回为准;断言至少这 3 个 key 都在,数字正确)。
- **`test_top_sources_limit_50`** —— seed 60 个不同 URL → top_sources 长度 == 50,且按 count 倒序。
- **`test_trend_set_diff`** —— day1: {A,B}, day2: {A,B,C}, day3: {A,C} → trend 应有 3 个 day,新值分别是 day1={A,B}(全新增)/day2={C}(1 新增)/day3={0}(无新增);流失分别是 day1=0(day1 无前日)/day2=0/day3={B}。
- **`test_window_uses_task_created_at`** —— seed 1 个 task 在窗口外(`today-30d`,days=15 不含) → 不应被计入。
- **`test_invalid_days_rejected`** —— days=0 / days=91 / days=-1 → HTTP 400。

### 前端

- 复用现有 `tsc --noEmit` 通过。
- 手动验证(Vite dev server):打开 `/admin/projects/{id}?tab=source`,确认 4 个面板渲染,KPI 数字与后端一致,饼图 / 柱状图 / 折线图正常渲染,Top 表可点击 URL 跳新窗口。

---

## 风险与开放问题

1. **reference_list_json 大小** —— 一个 subtask 的 reference_list 可能很长(50+),SQL 一次 `SELECT` 全拉回内存在 90 天窗口下可控(估算 1863 个 subtask × 10 条 ≈ 18K dict);不需要分页。
2. **类型字典精度** —— 沿用现有 `_CITATION_DOMAIN_RULES`,对 reference_list 的覆盖度可能不如对 citation_list 的(因为 citation_list 是模型实际引用的,通常更聚焦);但本期不优化。
3. **未配置 ProjectContext 天天下拉** —— 后端默认 `days=15` 不变,前端不引入切换控件;跟 `citation-analysis` 当前行为对齐。
4. **没有 reference_list_json 数据的 subtask** —— `total_subtasks` 不计入,这些 subtask 也不在「平均」分母里;与 spec §决策摘要 一致。

---

## 实施顺序(高阶)

1. 后端 schema + service + endpoint(单 PR / 单 commit)。
2. 后端测试 — 8 个 case 全过。
3. 前端 API client + `SourcePreferencesTab.tsx` + `Detail.tsx` 接线。
4. 手动验证 + 截图。
5. 文档(本 spec 已是文档;无需 README 更新)。