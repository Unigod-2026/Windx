# 信源偏好 MVP — 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把项目详情页 `?tab=source` 从 PlaceholderTab 替换成实际的「全部信源」MVP 页(KPI + 分类饼图 + 按模型柱状图 + Top 50 表 + 变化趋势双折线),数据源 `Subtask.reference_list_json`。

**Architecture:** 新建 `app/services/source_preferences.py` 把 `reference_list_json` 拆解 → 按 URL 聚合 → 输出 5 块(`kpi` / `type_counts` / `platform_slices` / `top_sources` 前 50 / `trend` 每日 set diff);新增 `GET /api/projects/{id}/source-preferences?days=15`,沿用 citation-analysis 窗口口径;前端 `SourcePreferencesTab.tsx` 单文件组装 4 个图表 + 1 个表格,替换 `Detail.tsx` 里 `case "source":` 的 PlaceholderTab。分类沿用 `_CITATION_DOMAIN_RULES`,趋势用 set diff,前端图表复用 `EChart` + AntD Table,样式沿用现有 `.panel*` + 新增 `.sp-*`。

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2 + Pydantic、React 18 + Vite + AntD 5 + echarts、MySQL 8。沿用现有依赖,不引入新包。

---

## 涉及文件

| 文件 | 职责 |
|---|---|
| `backend/app/schemas/project.py` | 末尾追加 6 个 Pydantic model:`SourcePreferenceKpi` / `SourceTypeSlice` / `SourcePlatformSlice` / `SourceTrendDay` / `SourcePreferenceItem` / `SourcePreferenceOut` |
| `backend/app/services/source_preferences.py` | 新建,`compute_source_preferences(db, project_id, days)` 把 `reference_list_json` 拆解 → 聚合 → 序列化 |
| `backend/app/api/projects.py` | 在 `citation_analysis` endpoint 之后追加 `source_preferences` endpoint(同窗口校验、同风格) |
| `backend/tests/test_source_preferences_api.py` | 新建,8 个 case(空态 / KPI / 类型 / Top 50 / 趋势 set diff / 窗口边界 / days 越界 / schema 字段存在) |
| `frontend/src/api/projects.ts` | 末尾追加 `SourcePreference*` 类型 + `getSourcePreferences(projectId, days=15)` |
| `frontend/src/pages/Projects/SourcePreferencesTab.tsx` | 新建,单文件主组件 |
| `frontend/src/pages/Projects/Detail.tsx` | `case "source":` 从 PlaceholderTab 改成 `SourcePreferencesTab` |

---

## Task 1: 后端 Schema — 6 个新 Pydantic 模型

**Files:**
- Modify: `backend/app/schemas/project.py` 末尾追加(在 `CitationAnalysisOut` 之后)
- Test: `backend/tests/test_source_preferences_api.py`(新建,只放 schema fixture)

- [ ] **Step 1: 新建测试文件**

新建 `backend/tests/test_source_preferences_api.py`,先把 fixture + 1 个 schema-presence placeholder 写好:

```python
"""Tests for GET /api/projects/{id}/source-preferences endpoint."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from jose import jwt
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import get_settings
from app.db import Base, get_db
from app.main import app
from app.models import AdminUser

settings = get_settings()

test_engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestSessionLocal = sessionmaker(
    bind=test_engine, autoflush=False, autocommit=False, future=True
)


def override_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _setup_db():
    app.dependency_overrides[get_db] = override_db
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture()
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture()
def token():
    with TestSessionLocal() as db:
        u = AdminUser(username="root", password_hash="x", role="super_admin", status="active")
        db.add(u); db.commit(); db.refresh(u)
        uid = u.id
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture()
def h(token):
    return {"Authorization": f"Bearer {token}"}


def test_source_preference_out_has_required_fields():
    from app.schemas.project import (
        SourcePreferenceKpi, SourceTypeSlice, SourcePlatformSlice,
        SourceTrendDay, SourcePreferenceItem, SourcePreferenceOut,
    )
    assert set(SourcePreferenceKpi.model_fields.keys()) >= {
        "total_references", "unique_urls", "cross_platform_urls",
        "avg_refs_per_subtask", "total_subtasks",
    }
    assert set(SourceTypeSlice.model_fields.keys()) == {"type", "count"}
    assert set(SourcePlatformSlice.model_fields.keys()) == {"platform", "total_refs", "unique_urls"}
    assert set(SourceTrendDay.model_fields.keys()) == {"date", "new_urls", "lost_urls"}
    assert set(SourcePreferenceItem.model_fields.keys()) == {
        "url", "site", "title", "type", "count", "platforms", "first_seen", "last_seen",
    }
    assert set(SourcePreferenceOut.model_fields.keys()) == {
        "project_id", "start", "end", "days",
        "kpi", "type_counts", "platform_slices", "top_sources", "trend",
    }
```

- [ ] **Step 2: 跑测试,确认 schema 缺失导致失败**

Run: `cd backend && uv run pytest tests/test_source_preferences_api.py::test_source_preference_out_has_required_fields -v`
Expected: FAIL — `ImportError: cannot import name 'SourcePreferenceKpi' from 'app.schemas.project'`

- [ ] **Step 3: 在 `backend/app/schemas/project.py` 末尾追加 6 个 schema**

把以下代码追加到 `class CitationAnalysisOut` 之后(注意保留文件末尾已有的换行):

```python
class SourcePreferenceKpi(BaseModel):
    """窗口聚合 KPI — 4 个 + 1 个分母。"""
    total_references: int          # 拆出来的 reference_list 总条数
    unique_urls: int              # 去重后的 URL 数
    cross_platform_urls: int      # platforms 长度 ≥ 2 的唯一 URL 数
    avg_refs_per_subtask: float   # total_references / total_subtasks
    total_subtasks: int           # 分母:窗口内 reference_list_json 非空的 subtask 数


class SourceTypeSlice(BaseModel):
    type: str
    count: int


class SourcePlatformSlice(BaseModel):
    platform: str
    total_refs: int      # 该平台下所有 reference_list_json 的总条数
    unique_urls: int     # 该平台下出现过的唯一 URL 数


class SourceTrendDay(BaseModel):
    date: date
    new_urls: int        # 当日首次出现的 URL 数(与前一日 set diff)
    lost_urls: int       # 前一日有、当日没有的 URL 数


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

- [ ] **Step 4: 跑测试,确认通过**

Run: `cd backend && uv run pytest tests/test_source_preferences_api.py::test_source_preference_out_has_required_fields -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/project.py backend/tests/test_source_preferences_api.py
git commit -m "feat(backend): SourcePreference* Pydantic schemas"
```

---

## Task 2: 后端 Service — 空态 + KPI + 分类聚合(TDD)

**Files:**
- Create: `backend/app/services/source_preferences.py`
- Modify: `backend/tests/test_source_preferences_api.py`(追加 3 个 case)

- [ ] **Step 1: 追加 3 个测试到 `test_source_preferences_api.py`**

在文件末尾追加(在 `test_source_preference_out_has_required_fields` 之后):

```python
def _seed_subtask(db, project_id, customer_id, *, platform, day, refs):
    """Seed a Task+Subtask pair at a specific calendar day, with a
    reference_list_json payload. ``refs`` is a list of dicts
    {"url", "site", "title"}. The Subtask's created_at and the Task's
    created_local_at are both backdated to ``day`` so windowing works.
    """
    from datetime import datetime, time
    from app.models.task import Task, Subtask
    suffix = f"{platform}-{day.isoformat()}-{refs[0]['url'] if refs else 'empty'}"
    task = Task(
        project_id=project_id, customer_id=customer_id,
        task_id=f"task-{suffix}", status="success",
    )
    db.add(task); db.flush()
    sub = Subtask(
        task_id=task.task_id, subtask_id=f"sub-{suffix}",
        platform=platform, status="success",
        reference_list_json=refs,
    )
    db.add(sub); db.flush()
    sub.created_at = datetime.combine(day, time.min)
    task.created_local_at = datetime.combine(day, time.min)
    return sub


async def test_empty_window_returns_zeros(client, h):
    """没有任何 subtask → kpi 全 0,所有 list 都空,200。"""
    from datetime import timedelta
    from app.models import Customer, Project
    from app.models.common import now_local

    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-empty", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kpi"]["total_references"] == 0
    assert body["kpi"]["unique_urls"] == 0
    assert body["kpi"]["cross_platform_urls"] == 0
    assert body["kpi"]["avg_refs_per_subtask"] == 0.0
    assert body["kpi"]["total_subtasks"] == 0
    assert body["type_counts"] == []
    assert body["platform_slices"] == []
    assert body["top_sources"] == []
    assert body["trend"] == []


async def test_kpi_basic_aggregation(client, h):
    """1 个 subtask / 3 条 URL / 1 个 platform → total=3, unique=3,
    cross_platform=0, avg=3.0, total_subtasks=1。"""
    from app.models import Customer, Project
    from app.models.common import now_local

    today = now_local().date()
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-kpi"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-kpi", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        _seed_subtask(db, pid, cust.id, platform="doubao", day=today, refs=[
            {"url": "https://a.com/", "site": "a.com", "title": "A"},
            {"url": "https://b.com/", "site": "b.com", "title": "B"},
            {"url": "https://c.com/", "site": "c.com", "title": "C"},
        ])
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    kpi = r.json()["kpi"]
    assert kpi["total_references"] == 3
    assert kpi["unique_urls"] == 3
    assert kpi["cross_platform_urls"] == 0
    assert kpi["avg_refs_per_subtask"] == 3.0
    assert kpi["total_subtasks"] == 1


async def test_kpi_cross_platform_url(client, h):
    """同一 URL 被 2 个不同 platform 的 subtask 引用 → cross_platform_urls=1。"""
    from app.models import Customer, Project
    from app.models.common import now_local

    today = now_local().date()
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-xp"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-xp", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        for plat in ("doubao", "kimi"):
            _seed_subtask(db, pid, cust.id, platform=plat, day=today, refs=[
                {"url": "https://shared.com/", "site": "shared.com", "title": "Shared"},
                {"url": f"https://{plat}-only.com/", "site": f"{plat}-only.com", "title": f"{plat} only"},
            ])
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    kpi = r.json()["kpi"]
    # 2 个 subtask,每个 2 条 = total=4,unique=3(shared + 2 个 plat-only),
    # cross_platform=1(shared.com), avg=2.0
    assert kpi["total_references"] == 4
    assert kpi["unique_urls"] == 3
    assert kpi["cross_platform_urls"] == 1
    assert kpi["avg_refs_per_subtask"] == 2.0
    assert kpi["total_subtasks"] == 2
    # platform_slices:每个 platform 一行
    platform_slices = {p["platform"]: p for p in r.json()["platform_slices"]}
    assert platform_slices["doubao"]["total_refs"] == 2
    assert platform_slices["doubao"]["unique_urls"] == 2
    assert platform_slices["kimi"]["total_refs"] == 2
    assert platform_slices["kimi"]["unique_urls"] == 2
```

- [ ] **Step 2: 跑测试,确认失败(空态会 500,期望是 404/500 因为端点不存在)**

Run: `cd backend && uv run pytest tests/test_source_preferences_api.py -k "empty_window or kpi" -v`
Expected: FAIL — 3 个都失败(endpoint 还不存在)

- [ ] **Step 3: 新建 `backend/app/services/source_preferences.py`**

```python
"""信源偏好页(data tab → 信源偏好 → 全部信源)计算服务。

数据源是 :data:`Subtask.reference_list_json` —— 模型完整可用的信源池
(区别于 :data:`Subtask.citation_list_json` 的「回答正文里实际引用的子集」)。
字段定义与 ``app.api.projects._CITATION_DOMAIN_RULES`` 的 host 子串分类
完全对齐;KPI、Top、trend 的口径见 spec
``docs/superpowers/specs/2026-08-19-source-preferences-tab-design.md``。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.models.common import now_local
from app.models.project import BrandMention
from app.models.task import Subtask, Task
from app.schemas.project import (
    SourcePreferenceKpi,
    SourcePreferenceOut,
    SourceTypeSlice,
    SourcePlatformSlice,
    SourcePreferenceItem,
    SourceTrendDay,
)


def _resolve_window(days: int) -> tuple[date, date]:
    """跟 ``app.api.projects._resolve_competitor_window`` 一致:dafault days=15,
    1-90 区间,否则 raise ValueError。"""
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")
    today = now_local().date()
    return today - timedelta(days=days - 1), today


def _host_for(site: str, url: str) -> str:
    return site if site else url


def compute_source_preferences(
    *, db, project_id: int, days: int = 15,
) -> SourcePreferenceOut:
    win_start, win_end = _resolve_window(days)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    rows = db.execute(
        select(
            Subtask.subtask_id,
            Subtask.platform,
            Subtask.reference_list_json,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    ).all()

    # Per-URL aggregation buckets.
    buckets: dict[str, dict] = {}
    # Per-platform rollup.
    platform_slices: dict[str, dict[str, int]] = {}
    # Per-day unique-URL set for trend set diff.
    daily_urls: dict[date, set[str]] = {}

    total_subtasks = 0
    total_references = 0

    for subtask_id, platform, refs, created_at in rows:
        if not isinstance(refs, list) or not refs:
            continue
        # 拆 dict 项(字符串 / 其它跳过,与 citation-analysis 一致)
        valid_items: list[dict] = []
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not isinstance(url, str) or not url.strip():
                continue
            valid_items.append(item)
        if not valid_items:
            continue

        total_subtasks += 1
        plat_key = platform or "unknown"
        ps = platform_slices.setdefault(plat_key, {"total_refs": 0, "unique_urls": 0})
        seen_urls_in_subtask: set[str] = set()
        for item in valid_items:
            url = item["url"].strip()
            site = item.get("site") or ""
            if not isinstance(site, str):
                site = ""
            title = item.get("title") or ""
            if not isinstance(title, str):
                title = ""
            total_references += 1
            ps["total_refs"] += 1
            seen_urls_in_subtask.add(url)

            cur = buckets.get(url)
            if cur is None:
                cur = {
                    "site": site,
                    "title": title,
                    "count": 0,
                    "platforms": set(),
                    "first_seen": created_at,
                    "last_seen": created_at,
                }
                buckets[url] = cur
            if title:
                cur["title"] = title
            if site and not cur["site"]:
                cur["site"] = site
            cur["count"] += 1
            if platform:
                cur["platforms"].add(platform)
            if created_at < cur["first_seen"]:
                cur["first_seen"] = created_at
            if created_at > cur["last_seen"]:
                cur["last_seen"] = created_at

            # daily set (按 created_at 的本地日期)
            day = created_at.date() if created_at else None
            if day is not None:
                daily_urls.setdefault(day, set()).add(url)
        ps["unique_urls"] += len(seen_urls_in_subtask)

    # ---- KPI ----
    unique_urls = len(buckets)
    cross_platform_urls = sum(
        1 for b in buckets.values() if len(b["platforms"]) >= 2
    )
    avg_refs = (total_references / total_subtasks) if total_subtasks else 0.0

    # ---- type_counts ----
    # 复用 _CITATION_DOMAIN_RULES;为了不在这层导入 api.projects 的私有函数,
    # 直接拷贝相同的 host 子串表。spec §关键边界 #6 要求两端口径必须一致。
    type_counts_map: dict[str, int] = {}
    for url, b in buckets.items():
        host = _host_for(b["site"], url)
        type_name = _classify_host(host)
        type_counts_map[type_name] = type_counts_map.get(type_name, 0) + b["count"]

    # ---- top_sources (前 50,按 count desc + last_seen desc) ----
    sorted_buckets = sorted(
        buckets.items(),
        key=lambda kv: (-kv[1]["count"], -int(kv[1]["last_seen"].timestamp())),
    )
    top_sources = [
        SourcePreferenceItem(
            url=url,
            site=b["site"],
            title=b["title"] or None,
            type=_classify_host(_host_for(b["site"], url)),
            count=b["count"],
            platforms=sorted(b["platforms"]),
            first_seen=b["first_seen"],
            last_seen=b["last_seen"],
        )
        for url, b in sorted_buckets[:50]
    ]

    # ---- trend: 按日 set diff ----
    trend: list[SourceTrendDay] = []
    if daily_urls:
        days_sorted = sorted(daily_urls.keys())
        prev_set: set[str] = set()
        for i, d in enumerate(days_sorted):
            cur_set = daily_urls[d]
            if i == 0:
                new = len(cur_set)
                lost = 0
            else:
                new = len(cur_set - prev_set)
                lost = len(prev_set - cur_set)
            trend.append(SourceTrendDay(date=d, new_urls=new, lost_urls=lost))
            prev_set = cur_set

    return SourcePreferenceOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=days,
        kpi=SourcePreferenceKpi(
            total_references=total_references,
            unique_urls=unique_urls,
            cross_platform_urls=cross_platform_urls,
            avg_refs_per_subtask=avg_refs,
            total_subtasks=total_subtasks,
        ),
        type_counts=[
            SourceTypeSlice(type=t, count=c)
            for t, c in sorted(type_counts_map.items(), key=lambda kv: -kv[1])
        ],
        platform_slices=[
            SourcePlatformSlice(platform=p, total_refs=v["total_refs"], unique_urls=v["unique_urls"])
            for p, v in sorted(platform_slices.items())
        ],
        top_sources=top_sources,
        trend=trend,
    )


# 与 app.api.projects._CITATION_DOMAIN_RULES 完全一致;docstring 解释见同文件。
_CITATION_DOMAIN_RULES = (
    ("垂类论坛", ("zhihu.com", "huxiu.com", "36kr.com", "juejin.cn", "csdn.net", "jianshu.com", "v2ex.com")),
    ("新闻网站", ("people.com.cn", "xinhuanet.com", "qq.com", "sohu.com", "sina.com.cn", "163.com", "thepaper.cn", "bbc.com", "bbc.co.uk")),
    ("官方网站", ("www.gov.cn", "gov.cn", "miit.gov.cn", "samr.gov.cn", "stats.gov.cn", "pbc.gov.cn", "csrc.gov.cn", "moe.gov.cn", "nhc.gov.cn", "nmpa.gov.cn")),
    ("百科", ("baike.baidu.com", "wikipedia.org", "wiki.com")),
    ("社交媒体", ("weibo.com", "weibo.cn", "x.com", "twitter.com", "facebook.com", "instagram.com", "linkedin.com")),
    ("自媒体", ("bilibili.com", "xiaohongshu.com", "douyin.com", "kuaishou.com", "toutiao.com", "youku.com", "tudou.com", "v.qq.com", "mp.weixin.qq.com", "weixin.qq.com")),
    ("海外网站", ("reddit.com", "quora.com", "medium.com", "github.com", "stackoverflow.com")),
)


def _classify_host(host: str) -> str:
    """跟 ``app.api.projects._classify_citation`` 保持完全一致的 host 子串分类。"""
    if not host:
        return "其他"
    h = host.lower()
    for type_name, needles in _CITATION_DOMAIN_RULES:
        for n in needles:
            if n in h:
                return type_name
    return "其他"
```

- [ ] **Step 4: 跑测试,确认 3 个新 case 通过**

Run: `cd backend && uv run pytest tests/test_source_preferences_api.py -k "empty_window or kpi" -v`
Expected: 3 passed(因为现在 service 已存在但 endpoint 还没接,3 个测试都是直接调函数,跳过 endpoint)

> 注:3 个测试目前是直接调 `compute_source_preferences` 还是经 endpoint?看 Step 1 的写法 —— 用 `client.get(.../source-preferences)` 走 HTTP,所以还没接 endpoint 之前会 404。Step 4 之前需要先接 endpoint 或临时把测试改成直接调函数。Step 5 接 endpoint 后,3 个 case 会自然通过。

修正:**Step 4 改成跑测试,确认 404/500 仍然(预期失败)**;测试会在 Task 4 接 endpoint 后转绿。Step 4 输出:
Expected: 3 failed(`404 Not Found` —— endpoint 未注册)

- [ ] **Step 5: Commit(scaffold + service)**

```bash
git add backend/app/services/source_preferences.py backend/tests/test_source_preferences_api.py
git commit -m "feat(backend): source_preferences service + KPI/type/platform aggregation"
```

---

## Task 3: 后端 Top 50 上限 + 趋势 set diff 测试

**Files:**
- Modify: `backend/tests/test_source_preferences_api.py`(追加 2 个 case)

- [ ] **Step 1: 追加 top_sources 上限 + 趋势 set diff 测试**

```python
async def test_top_sources_limit_50(client, h):
    """seed 60 个不同 URL → top_sources 长度 == 50,按 count desc 排序。"""
    from app.models import Customer, Project
    from app.models.common import now_local

    today = now_local().date()
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-top"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-top", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        refs = [
            {"url": f"https://u{i:02d}.com/", "site": f"u{i:02d}.com", "title": f"U{i}"}
            for i in range(60)
        ]
        _seed_subtask(db, pid, cust.id, platform="doubao", day=today, refs=refs)
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    top = r.json()["top_sources"]
    assert len(top) == 50
    counts = [it["count"] for it in top]
    assert counts == sorted(counts, reverse=True)


async def test_trend_set_diff(client, h):
    """day1: {A,B}, day2: {A,B,C}, day3: {A,C} → trend 3 个 day。
    day1: new=2(A,B 全新)/lost=0(无前日)
    day2: new=1(C)/lost=0
    day3: new=0 / lost=1(B 流失)"""
    from app.models import Customer, Project
    from app.models.common import now_local
    from datetime import timedelta

    today = now_local().date()
    d1 = today - timedelta(days=2)
    d2 = today - timedelta(days=1)
    d3 = today
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-trend"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-trend", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        for d, urls in [
            (d1, ["https://a.com/", "https://b.com/"]),
            (d2, ["https://a.com/", "https://b.com/", "https://c.com/"]),
            (d3, ["https://a.com/", "https://c.com/"]),
        ]:
            _seed_subtask(db, pid, cust.id, platform="doubao", day=d, refs=[
                {"url": u, "site": u.split("://")[1].rstrip("/"), "title": u} for u in urls
            ])
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    trend = {t["date"]: t for t in r.json()["trend"]}
    assert trend[d1.isoformat()]["new_urls"] == 2
    assert trend[d1.isoformat()]["lost_urls"] == 0
    assert trend[d2.isoformat()]["new_urls"] == 1
    assert trend[d2.isoformat()]["lost_urls"] == 0
    assert trend[d3.isoformat()]["new_urls"] == 0
    assert trend[d3.isoformat()]["lost_urls"] == 1
```

- [ ] **Step 2: 跑测试,确认两个 case 失败(endpoint 未注册)**

Run: `cd backend && uv run pytest tests/test_source_preferences_api.py -k "top_sources_limit_50 or trend_set_diff" -v`
Expected: 2 failed(`404` —— endpoint 未注册)

- [ ] **Step 3: 不动 service 代码(Service 已经在 Task 2 实现),仅添加这两个 case**

> Service 在 Task 2 已实现 `top_sources[:50]` 和 trend set diff;Task 3 只是把覆盖这两个口径的 case 加上,等 Task 4 endpoint 接好后会一次转绿。

- [ ] **Step 4: 不需要 commit(只改了 test 文件,跟 Task 2 的 case 一起 commit)。若希望单独 commit:**

```bash
git add backend/tests/test_source_preferences_api.py
git commit -m "test(backend): top_sources limit + trend diff cases"
```

---

## Task 4: 后端 Endpoint + 400 守卫 + 全部测试

**Files:**
- Modify: `backend/app/api/projects.py`(在 `citation_analysis` 之后追加)
- Modify: `backend/tests/test_source_preferences_api.py`(追加窗口边界 + 400 case)

- [ ] **Step 1: 追加 2 个 case(窗口边界 + days 越界)**

```python
async def test_window_excludes_out_of_range_subtasks(client, h):
    """task.created_local_at 在窗口外的 subtask 不计入(等同 citation-analysis)。"""
    from datetime import timedelta
    from app.models import Customer, Project
    from app.models.common import now_local

    today = now_local().date()
    out_of_range = today - timedelta(days=30)  # days=15 窗口外
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-win"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-win", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        _seed_subtask(db, pid, cust.id, platform="doubao", day=out_of_range, refs=[
            {"url": "https://outside.com/", "site": "outside.com", "title": "Outside"},
        ])
        db.commit()

    r = await client.get(f"/api/projects/{pid}/source-preferences?days=15", headers=h)
    body = r.json()
    assert body["kpi"]["total_references"] == 0
    assert body["kpi"]["total_subtasks"] == 0


async def test_invalid_days_returns_400(client, h):
    """days=0 / days=91 → HTTP 400。"""
    from app.models import Customer, Project
    with TestSessionLocal() as db:
        cust = Customer(name="t", code="t-sp-400"); db.add(cust); db.flush()
        proj = Project(customer_id=cust.id, name="p", code="p-sp-400", brand="A")
        db.add(proj); db.flush()
        pid = proj.id
        db.commit()

    for bad in (0, 91, -1):
        r = await client.get(f"/api/projects/{pid}/source-preferences?days={bad}", headers=h)
        assert r.status_code == 400, f"days={bad} should be 400, got {r.status_code}"
```

- [ ] **Step 2: 跑测试,确认失败(endpoint 未注册)**

Run: `cd backend && uv run pytest tests/test_source_preferences_api.py -v`
Expected: 7 failed(全是 endpoint 404)

- [ ] **Step 3: 在 `backend/app/api/projects.py` 的 `citation_analysis` 函数之后追加 endpoint**

先在文件顶部 imports 区域追加(找到 `from app.services.competitor_analysis import ...` 那块,新增一行):

```python
from app.services.source_preferences import compute_source_preferences
```

然后在 `citation_analysis` 函数定义后面追加新函数(直接复制粘贴下面整段,保持与 `citation_analysis` 同风格):

```python
# --------------------------------------------------------------------------
# Source preferences (data tab → 信源偏好 → 全部信源)
# --------------------------------------------------------------------------


@router.get(
    "/projects/{project_id}/source-preferences",
    response_model=SourcePreferenceOut,
)
def source_preferences(
    project_id: int,
    days: int = 15,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    """Per-URL aggregation of ``Subtask.reference_list_json`` in the window.

    跟 :func:`citation_analysis` 共用窗口口径(Task.project_id + Task.created_local_at),
    但读的是模型完整可用的信源池,而不是回答正文里实际引用的子集。返回 5 块:
    kpi / type_counts / platform_slices / top_sources(前 50)/ trend(每日 set diff)。
    spec §后端设计 + docs/superpowers/specs/2026-08-19-source-preferences-tab-design.md。
    """
    project = _get_project(db, project_id)
    _assert_customer_access(user, project)

    try:
        win_start, win_end = _resolve_competitor_window(days, None, None)
    except HTTPException:
        raise

    # 把 HTTP 400 的字符串检查抽到 service 之外(避免 service 层返 HTTPException)。
    if days < 1 or days > 90:
        raise HTTPException(400, "days must be between 1 and 90")

    return compute_source_preferences(
        db=db, project_id=project_id, days=days,
    )
```

- [ ] **Step 4: 跑全部 8 个测试,确认全过**

Run: `cd backend && uv run pytest tests/test_source_preferences_api.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/projects.py backend/tests/test_source_preferences_api.py
git commit -m "feat(backend): GET /projects/{id}/source-preferences endpoint"
```

---

## Task 5: 前端 API 客户端 + 类型

**Files:**
- Modify: `frontend/src/api/projects.ts`(末尾追加)

- [ ] **Step 1: 在 `frontend/src/api/projects.ts` 末尾追加类型 + client**

找到文件末尾,在最后一个 export 之后追加:

```typescript
export interface SourcePreferenceKpi {
  total_references: number;
  unique_urls: number;
  cross_platform_urls: number;
  avg_refs_per_subtask: number;
  total_subtasks: number;
}

export interface SourceTypeSlice {
  type: string;
  count: number;
}

export interface SourcePlatformSlice {
  platform: string;
  total_refs: number;
  unique_urls: number;
}

export interface SourceTrendDay {
  date: string;
  new_urls: number;
  lost_urls: number;
}

export interface SourcePreferenceItem {
  url: string;
  site: string;
  title: string | null;
  type: string;
  count: number;
  platforms: string[];
  first_seen: string;
  last_seen: string;
}

export interface SourcePreferenceOut {
  project_id: number;
  start: string;
  end: string;
  days: number;
  kpi: SourcePreferenceKpi;
  type_counts: SourceTypeSlice[];
  platform_slices: SourcePlatformSlice[];
  top_sources: SourcePreferenceItem[];
  trend: SourceTrendDay[];
}

export function getSourcePreferences(
  projectId: number,
  days = 15,
): Promise<SourcePreferenceOut> {
  return request
    .get<SourcePreferenceOut>(
      `/api/projects/${projectId}/source-preferences`,
      { params: { days } },
    )
    .then((r) => r.data);
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && ./node_modules/.bin/tsc -b 2>&1 | tail`
Expected: 无错误输出

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/projects.ts
git commit -m "feat(frontend): getSourcePreferences client + types"
```

---

## Task 6: 前端 SourcePreferencesTab — KPI + 饼图 + 柱状图

**Files:**
- Create: `frontend/src/pages/Projects/SourcePreferencesTab.tsx`

- [ ] **Step 1: 创建组件文件,先实现数据加载 + KPI 行 + 2 个图表(饼图 + 柱状图)**

新建 `frontend/src/pages/Projects/SourcePreferencesTab.tsx`:

```tsx
import { useEffect, useMemo, useState } from "react";
import { Empty, Skeleton, message } from "antd";
import * as echarts from "echarts";
import EChart from "../../components/EChart";
import {
  getSourcePreferences,
  type SourcePreferenceOut,
} from "../../api/projects";

interface Props {
  projectId: number;
}

const TYPE_COLOR: Record<string, string> = {
  垂类论坛: "#13c2c2",
  新闻网站: "#52c41a",
  官方网站: "#1a55e8",
  百科: "#722ed1",
  社交媒体: "#eb2f96",
  自媒体: "#fa8c16",
  海外网站: "#f5222d",
  其他: "#bfbfbf",
};

export default function SourcePreferencesTab({ projectId }: Props) {
  const [out, setOut] = useState<SourcePreferenceOut | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getSourcePreferences(projectId)
      .then((d) => { if (!cancelled) setOut(d); })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "信源偏好数据加载失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId]);

  const typeOption = useMemo<echarts.EChartsOption | null>(() => {
    if (!out || out.type_counts.length === 0) return null;
    return {
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { orient: "horizontal", bottom: 0, textStyle: { fontSize: 11 } },
      series: [{
        type: "pie",
        radius: ["45%", "70%"],
        avoidLabelOverlap: true,
        label: { show: false },
        data: out.type_counts.map((s) => ({
          name: s.type,
          value: s.count,
          itemStyle: { color: TYPE_COLOR[s.type] ?? "#bfbfbf" },
        })),
      }],
    };
  }, [out]);

  const platformOption = useMemo<echarts.EChartsOption | null>(() => {
    if (!out || out.platform_slices.length === 0) return null;
    return {
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      legend: { data: ["引用条数", "唯一 URL"], top: 0, textStyle: { fontSize: 11 } },
      grid: { left: 50, right: 24, top: 36, bottom: 40 },
      xAxis: { type: "category", data: out.platform_slices.map((p) => p.platform) },
      yAxis: [
        { type: "value", name: "引用条数", axisLabel: { fontSize: 11 } },
        { type: "value", name: "唯一 URL", axisLabel: { fontSize: 11 } },
      ],
      series: [
        {
          name: "引用条数",
          type: "bar",
          data: out.platform_slices.map((p) => p.total_refs),
          itemStyle: { color: "#1a55e8" },
          barWidth: 24,
        },
        {
          name: "唯一 URL",
          type: "bar",
          yAxisIndex: 1,
          data: out.platform_slices.map((p) => p.unique_urls),
          itemStyle: { color: "#ff6b1a" },
          barWidth: 24,
        },
      ],
    };
  }, [out]);

  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;
  if (!out) return <Empty description="暂无可展示的信源数据" />;
  if (out.kpi.total_references === 0) {
    return <Empty description="窗口内尚无信源数据" style={{ padding: 32 }} />;
  }

  const k = out.kpi;

  return (
    <div className="sp-root">
      {/* KPI 行 */}
      <div className="sp-kpi-row">
        <KpiCard label="总引用条数" value={k.total_references.toLocaleString()} />
        <KpiCard label="唯一信源" value={k.unique_urls.toLocaleString()} />
        <KpiCard label="跨模型共享" value={k.cross_platform_urls.toLocaleString()} />
        <KpiCard label="平均每条引用" value={k.avg_refs_per_subtask.toFixed(1)} />
      </div>

      {/* 行 1:分类饼图 + 按模型柱状图 */}
      <div className="sp-row">
        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>信源分类分布</h3>
              <p>按 host 子串分类的引用条数占比</p>
            </div>
          </div>
          <div className="panel-body">
            {typeOption
              ? <EChart option={typeOption} className="sp-chart" />
              : <Empty description="暂无分类数据" />}
          </div>
        </div>

        <div className="panel">
          <div className="panel-header">
            <div>
              <h3>按模型引用分布</h3>
              <p>每个大模型引用了多少信源 / 其中多少唯一</p>
            </div>
          </div>
          <div className="panel-body">
            {platformOption
              ? <EChart option={platformOption} className="sp-chart" />
              : <Empty description="暂无模型数据" />}
          </div>
        </div>
      </div>

      <style>{`
        .sp-root { display: flex; flex-direction: column; gap: 12px; padding: 12px 0; }
        .sp-kpi-row {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 12px;
        }
        .sp-kpi-card {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          padding: 14px 18px;
        }
        .sp-kpi-card-label { font-size: 12px; color: var(--text-tertiary); }
        .sp-kpi-card-value { font-size: 22px; font-weight: 600; color: var(--text-primary); margin-top: 6px; }
        .sp-row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
        .sp-chart { width: 100%; height: 280px; display: block; }
        .panel {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          display: flex;
          flex-direction: column;
        }
        .panel-header {
          padding: 14px 18px 10px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .panel-header h3 { margin: 0; font-size: 15px; font-weight: 600; color: var(--text-primary); }
        .panel-header p { margin: 4px 0 0; font-size: 12px; color: var(--text-tertiary); }
        .panel-body { padding: 16px 18px; }
      `}</style>
    </div>
  );
}

function KpiCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="sp-kpi-card">
      <div className="sp-kpi-card-label">{label}</div>
      <div className="sp-kpi-card-value">{value}</div>
    </div>
  );
}
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && ./node_modules/.bin/tsc -b 2>&1 | tail`
Expected: 无错误输出

- [ ] **Step 3: 不 commit(组件未完成,留到 Task 7 一起)**

---

## Task 7: 前端 SourcePreferencesTab — Top 表 + 趋势双折线

**Files:**
- Modify: `frontend/src/pages/Projects/SourcePreferencesTab.tsx`(在 KPI + 2 图表之后追加 2 个 panel)

- [ ] **Step 1: 在 return JSX 的 `</div>` (sp-root 关闭标签) 之前追加 Top 表 + 趋势 panel**

找到 `<style>{...}</style>` 之前那行 `{/* 行 1:分类饼图 + 按模型柱状图 */}`,在它后面追加:

```tsx
      {/* 行 2:Top 50 信源 */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>信源引用 Top 50</h3>
            <p>按引用次数倒序 · 共 {out.top_sources.length} 条</p>
          </div>
        </div>
        <div className="panel-body">
          <TopSourcesTable items={out.top_sources} />
        </div>
      </div>

      {/* 行 3:变化趋势双折线 */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>信源变化趋势</h3>
            <p>每日新增 / 流失 URL 数(按 created_at 所在本地日期 set diff)</p>
          </div>
        </div>
        <div className="panel-body">
          <TrendChart data={out.trend} />
        </div>
      </div>
```

- [ ] **Step 2: 替换 `export default function SourcePreferencesTab(...)` 末尾,在文件最后追加两个子组件**

文件最后追加:

```tsx
function TopSourcesTable({ items }: { items: import("../../api/projects").SourcePreferenceItem[] }) {
  if (items.length === 0) return <Empty description="暂无信源明细" />;
  return (
    <table className="data-table data-table-hover" style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
      <thead>
        <tr>
          <th style={{ width: 48, textAlign: "left" }}>#</th>
          <th style={{ textAlign: "left" }}>信源</th>
          <th style={{ width: 110 }}>类型</th>
          <th style={{ width: 90, textAlign: "right" }}>引用次数</th>
          <th style={{ width: 220 }}>平台</th>
          <th style={{ width: 110 }}>最近引用</th>
        </tr>
      </thead>
      <tbody>
        {items.map((it, i) => (
          <tr key={it.url}>
            <td>{i + 1}</td>
            <td>
              <a href={it.url} target="_blank" rel="noopener noreferrer" style={{ color: "#1a55e8" }}>
                {it.title || it.site || it.url}
              </a>
              {it.title && (
                <div style={{ fontSize: 11, color: "var(--text-tertiary)", marginTop: 2 }}>
                  {it.site || it.url}
                </div>
              )}
            </td>
            <td>
              <span
                style={{
                  padding: "2px 8px",
                  borderRadius: 999,
                  background: TYPE_COLOR[it.type] ?? "#bfbfbf",
                  color: "#fff",
                  fontSize: 11,
                }}
              >
                {it.type}
              </span>
            </td>
            <td style={{ textAlign: "right", fontWeight: 600 }}>{it.count}</td>
            <td>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {it.platforms.map((p) => (
                  <span
                    key={p}
                    style={{
                      padding: "1px 8px",
                      borderRadius: 999,
                      background: "var(--bg-page, #fafafa)",
                      border: "1px solid #e8e9ec",
                      fontSize: 11,
                      color: "var(--text-secondary)",
                    }}
                  >
                    {p}
                  </span>
                ))}
              </div>
            </td>
            <td style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
              {it.last_seen.slice(0, 10)}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function TrendChart({ data }: { data: import("../../api/projects").SourceTrendDay[] }) {
  const option = useMemo<echarts.EChartsOption | null>(() => {
    if (data.length === 0) return null;
    return {
      tooltip: { trigger: "axis" },
      legend: { data: ["新增", "流失"], top: 0, textStyle: { fontSize: 11 } },
      grid: { left: 50, right: 24, top: 36, bottom: 40 },
      xAxis: { type: "category", data: data.map((d) => d.date) },
      yAxis: { type: "value", minInterval: 1, axisLabel: { fontSize: 11 } },
      series: [
        {
          name: "新增",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          data: data.map((d) => d.new_urls),
          itemStyle: { color: "#52c41a" },
          lineStyle: { color: "#52c41a", width: 2 },
          areaStyle: { color: "#52c41a", opacity: 0.08 },
        },
        {
          name: "流失",
          type: "line",
          smooth: true,
          symbol: "circle",
          symbolSize: 6,
          data: data.map((d) => d.lost_urls),
          itemStyle: { color: "#f5222d" },
          lineStyle: { color: "#f5222d", width: 2 },
          areaStyle: { color: "#f5222d", opacity: 0.08 },
        },
      ],
    };
  }, [data]);
  if (!option) return <Empty description="窗口内尚无趋势数据" />;
  return <EChart option={option} className="sp-chart" style={{ height: 280 }} />;
}
```

并在 `import * as echarts from "echarts";` 后面追加 `import type { EChartsOption } from "echarts";`,把 `useMemo<echarts.EChartsOption | null>` 替换为 `useMemo<EChartsOption | null>`(可选,纯风格)。不影响功能。

- [ ] **Step 3: 类型检查**

Run: `cd frontend && ./node_modules/.bin/tsc -b 2>&1 | tail`
Expected: 无错误输出

- [ ] **Step 4: 不 commit,留到 Task 8 接线 + commit**

---

## Task 8: 前端 Detail.tsx 接线 + 手动验证

**Files:**
- Modify: `frontend/src/pages/Projects/Detail.tsx`

- [ ] **Step 1: 替换 import + case 分支**

把 `Detail.tsx` 里的:

```tsx
import PlaceholderTab from "./PlaceholderTab";
```

改成(在现有 imports 里加一行):

```tsx
import PlaceholderTab from "./PlaceholderTab";
import SourcePreferencesTab from "./SourcePreferencesTab";
```

然后把:

```tsx
case "source":
  return (
    <PlaceholderTab
      title="信源偏好"
      hint="每个大模型引用最多的信源类型 TOP3 + 信源异动"
    />
  );
```

改成:

```tsx
case "source":
  return <SourcePreferencesTab projectId={projectId} />;
```

- [ ] **Step 2: 类型检查**

Run: `cd frontend && ./node_modules/.bin/tsc -b 2>&1 | tail`
Expected: 无错误输出

- [ ] **Step 3: 浏览器手动验证**

打开 `http://localhost:5173/admin/projects/<任意项目 id>?tab=source`(或 Vite 实际端口),确认:
1. KPI 行 4 张卡(总引用 / 唯一信源 / 跨模型共享 / 平均每条引用)
2. 信源分类饼图渲染(echarts donut,有颜色)
3. 按模型引用柱状图渲染
4. Top 50 表格渲染,URL 可点击新窗口打开,类型彩色 chip,平台 chips
6. 变化趋势双折线渲染(绿=新增、红=流失)
7. 项目无 reference_list_json 数据 → Empty「窗口内尚无信源数据」
8. 切换到其他 tab(`?tab=overview`、`?tab=competitor`) → 旧页面正常

- [ ] **Step 4: 后端测试再跑一遍,确认 8 个全过**

Run: `cd backend && uv run pytest tests/test_source_preferences_api.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Projects/SourcePreferencesTab.tsx frontend/src/pages/Projects/Detail.tsx
git commit -m "feat(frontend): SourcePreferencesTab replaces ?tab=source PlaceholderTab"
```

---

## 完成标准

1. `cd backend && uv run pytest tests/test_source_preferences_api.py` → 8 passed
2. `cd frontend && ./node_modules/.bin/tsc -b` → 无错误
3. 浏览器访问 `/admin/projects/{id}?tab=source` → 4 个面板(KPI / 饼图柱状图 / Top 表 / 趋势)全部正常
4. 切换 tab 无回归
5. 4 个保留为 PlaceholderTab 的 sub-tab(信源明细 / 自有文章 / 网站分类 / 视频类信源)显示仍为 PlaceholderTab

## 风险与回退

- **`_CITATION_DOMAIN_RULES` 重复维护** —— service 里复制了一份 host 子串表;若 `api.projects` 那份改动,service 会漂移。后续若两类聚合的口径需要严格对齐,可以把规则表移到 `app.schemas.project` 或新建 `app/services/citation_classifier.py`,service 与 endpoint 都 import 同一份。本次按 spec §关键边界 #6 的「先复制定义、留 TODO」策略;真正落地时会跟 `citation-analysis` 端点共用同一份规则。
- **大数据量性能** —— 90 天窗口 × 数千 subtask × 数十 refs/subtask,单次 SELECT 全拉回 Python 内存可控;若日后性能瓶颈,再考虑按平台 / 按日分桶聚合,SPEC 不变更。
- **Top 50 上限** —— 当前硬编码 `[:50]`;若用户反馈希望 Top 100,改 service 即可,schema 无影响。