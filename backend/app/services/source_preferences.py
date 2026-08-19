"""信源偏好页(data tab → 信源偏好 → 全部信源)计算服务。

数据源是 :data:`Subtask.reference_list_json` —— 模型完整可用的信源池
(区别于 :data:`Subtask.citation_list_json` 的「回答正文里实际引用的子集」)。
字段定义与 ``app.schemas.project._CITATION_DOMAIN_RULES`` 的 host 子串分类
完全对齐;KPI、Top、trend 的口径见 spec
``docs/superpowers/specs/2026-08-19-source-preferences-tab-design.md``。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.models.common import now_local
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


# 与 app.schemas.project._CITATION_DOMAIN_RULES 完全一致;docstring 解释见同文件。
_CITATION_DOMAIN_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("百科", ("baike.baidu.com", "wikipedia.org", "wiki.", "/wiki/")),
    (
        "官方网站",
        (
            ".gov.cn",
            ".gov.",
            ".edu.cn",
            ".edu.",
            ".org.cn",
            "anthropic.com",
            "openai.com",
            "deepseek.com",
            "platform.deepseek",
            "qwen.ai",
            "qwen.com",
            "tongyi.aliyun.com",
            "yiyan.baidu.com",
            "kimi.moonshot.cn",
            "kimi.com",
            "hunyuan.tencent.com",
            "liaobots.com",
            "openrouter.ai",
            "artificialanalysis.ai",
            "lmarena.ai",
            "superclueai.com",
            "superclue.org",
            "vellum.ai",
            "toolcenter.ai",
            "官网",
        ),
    ),
    (
        "新闻网站",
        (
            "news.sina.com.cn",
            "news.sina.com",
            "sina.com",
            "sohu.com",
            "163.com",
            "qq.com/news",
            "ifeng.com",
            "thepaper.cn",
            "xinhuanet.com",
            "people.com.cn",
            "huanqiu.com",
            "chinanews.com",
            "dxy.com",
            "yicai.com",
            "caixin.com",
            "jiemodui.com",
            "36kr.com",
            "tmtpost.com",
            "techweb.com.cn",
            "c114.com.cn",
            "donews.com",
            "ithome.com",
            "leiphone.com",
            "pingwest.com",
        ),
    ),
    (
        "社交媒体",
        (
            "weibo.com",
            "weibo.cn",
            "xiaohongshu.com",
            "douban.com",
            "zhihu.com",
            "weixin.qq.com",
            "mp.weixin.qq.com",
            "tieba.baidu.com",
            "baijiahao.baidu.com",
        ),
    ),
    (
        "垂类论坛",
        (
            "csdn.net",
            "juejin.cn",
            "segmentfault.com",
            "oschina.net",
            "v2ex.com",
            "gitee.com",
            "51cto.com",
            "infoq.cn",
        ),
    ),
    (
        "自媒体",
        (
            "douyin.com",
            "bilibili.com",
            "kuaishou.com",
            "xiguashipin.com",
            "ixigua.com",
            "youtube.com",
            "youku.com",
            "v.qq.com",
            "video.sina.com.cn",
        ),
    ),
)


def _classify_host(host: str) -> str:
    """跟 ``app.api.projects._classify_citation`` / ``app.schemas.project``
    中的 host 子串分类保持完全一致。"""
    if not host:
        return "其他"
    h = host.lower()
    for type_name, needles in _CITATION_DOMAIN_RULES:
        for n in needles:
            if n in h:
                return type_name
    return "其他"
