"""信源偏好页(data tab → 信源偏好 → 全部信源)计算服务。

数据源是 :data:`Subtask.reference_list_json` —— 模型完整可用的信源池
(区别于 :data:`Subtask.citation_list_json` 的「回答正文里实际引用的子集」)。
字段定义与 ``app.schemas.project._CITATION_DOMAIN_RULES`` 的 host 子串分类
完全对齐;KPI、Top、trend 的口径见 spec
``docs/superpowers/specs/2026-08-19-source-preferences-tab-design.md``。
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.models.common import now_local
from app.models.task import Subtask, Task
from app.schemas.project import (
    SourceByModelTop,
    SourceDetailItem,
    SourceDetailOut,
    SourceMediaTop,
    SourcePreferenceItem,
    SourcePreferenceKpi,
    SourcePreferenceOut,
    SourcePlatformSlice,
    SourceSelfItem,
    SourceSelfKpi,
    SourceSelfOut,
    SourceStableItem,
    SourceSuggestion,
    SourceTrendDay,
    SourceTrendPlatform,
    SourceTypeSlice,
    VideoPlatformSlice,
    VideoSourceOut,
)


def _resolve_window(
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
) -> tuple[date, date]:
    """跟 ``app.api.projects._resolve_window_inline`` 一致:start/end 优先,
    否则取最近 N 天(default 15,1-90 区间)。端点层把 ValueError 转 HTTP 400。

    toolbar 「自定义」走 start/end(无限 15 / 30 / 60 / 7 预设),普通预设走 days。
    """
    if start is not None or end is not None:
        if start is None or end is None:
            raise ValueError("start and end must be provided together")
        if end < start:
            raise ValueError("end must not be earlier than start")
        return start, end
    if days < 1 or days > 90:
        raise ValueError("days must be between 1 and 90")
    today = now_local().date()
    return today - timedelta(days=days - 1), today


def _host_for(site: str, url: str) -> str:
    """分类用的 host 提取。

    数据契约坑:``reference_list_json`` 的 ``site`` 字段是**中文媒体显示名**
    (凤凰网文化读书 / 壹日一报 / 广西隆林网 等),不是域名;
    真正的 host 在 ``url`` 字段里。直接用 site 去匹配
    :data:`_CITATION_DOMAIN_RULES` 的英文 host 子串会 100% 落「其他」。
    所以分类时统一从 url 提 host(小写,无端口无 path)。
    site 仅作为显示字段保留在 :class:`SourcePreferenceItem.site` 里。
    """
    if url:
        m = _HOST_RE.search(url)
        if m:
            return m.group(1).lower()
    return site or ""


_HOST_RE = re.compile(r"https?://([^/?#]+)", re.IGNORECASE)

# mode → thinking 取值映射,跟前端 GlobalToolbar dropdown 的 fast/think 档位对齐。
# `geo_subtasks.mode`:search → fast,reasoning_search → think;其它/缺省 → fast(兜底)。
_MODE_TO_THINKING: dict[str, str] = {
    "search": "fast",
    "reasoning_search": "think",
}


def _compound_platform(platform: str | None, mode: str | None) -> str:
    """把 (platform, mode) 归一成 ``<code>__<delivery>__<thinking>`` compound key,
    对齐 ``frontend/src/pages/Projects/platforms.ts`` 的 ``OVERVIEW_KEY_RE``。

    delivery:`xxx_mobile` 后缀 → mobile,否则 → web。
    thinking:``_MODE_TO_THINKING`` 映射,缺/未知 → fast。
    platform 为空 / None → 'unknown__web__fast'(避免空 key)。
    """
    code = platform or "unknown"
    if code.endswith("_mobile"):
        delivery = "mobile"
        base = code[: -len("_mobile")]
    else:
        delivery = "web"
        base = code
    thinking = _MODE_TO_THINKING.get(mode or "", "fast")
    return f"{base}__{delivery}__{thinking}"


def _expand_platform_keys(compound_keys: list[str]) -> set[str]:
    """``_compound_platform`` 的逆操作:把 compound key 列表拆回
    ``Subtask.platform`` 实际存的 ``platform_code`` 集合,供 SQL
    ``WHERE platform IN (...)`` 使用。

    兼容两种 compound key 格式:
    - 后端 ``_compound_platform`` 产出 ``<base>__<delivery>__<thinking>``(例
      ``qianwen__mobile__fast``,base 不含 ``_mobile`` 后缀)。
    - 前端 ``rowKeyOfPlatform`` 用 ``ProjectPlatform.platform_code`` 直拼,
      mobile 行产 ``qianwen_mobile__mobile__fast``(code 已带 ``_mobile``)。

    先把 code 的 ``_mobile`` 后缀剥掉,再按 delivery 决定是否加回 —— 否则
    会产出 ``qianwen_mobile_mobile`` 这种不存在的 ``platform_code``,SQL
    ``platform IN (...)`` 一条都命中不了。

    delivery=mobile → 加 ``<base>_mobile``,否则加 ``<base>``。
    非法格式的 key 静默跳过,避免脏数据把整个 SQL 拉爆。
    """
    out: set[str] = set()
    for key in compound_keys:
        parts = key.split("__")
        if len(parts) != 3:
            continue
        code, delivery, _thinking = parts
        if not code:
            continue
        # 前端 compound key 可能 code 已带 ``_mobile`` 后缀,先剥后缀
        # 再按 delivery 决定是否加回。
        if code.endswith("_mobile"):
            base = code[: -len("_mobile")]
        else:
            base = code
        if delivery == "mobile":
            out.add(f"{base}_mobile")
        else:
            out.add(base)
    return out


def _fetch_source_rows(
    *, db,
    win_start_dt: datetime,
    win_end_dt: datetime,
    project_id: int,
    selected_platforms: list[str] | None,
    selected_prompt_texts: list[str] | None,
) -> list:
    """Build SQL + apply toolbar filters + post-filter by compound key.
    返回 (subtask_id, platform, mode, refs, prompt, created_at) 元组列表,
    ``compute_source_preferences`` 与 ``compute_source_detail`` 共用,
    避免两边窗口 / 筛选口径漂移。
    """
    stmt = (
        select(
            Subtask.subtask_id,
            Subtask.platform,
            Subtask.mode,
            Subtask.reference_list_json,
            Subtask.prompt,
            Task.created_local_at,
        )
        .join(Task, Task.task_id == Subtask.task_id)
        .where(
            Task.project_id == project_id,
            Task.created_local_at >= win_start_dt,
            Task.created_local_at <= win_end_dt,
        )
    )
    # toolbar 「问题」筛选:Subtask 按 prompt 文本存,无 prompt_id 外键。
    # ``selected_prompt_texts`` 显式传空列表(全部 id 解析不到)= 不筛中任
    # 何行,这是有意为之 —— 与 toolbar 应用后立即生效的语义对齐。
    if selected_prompt_texts is not None:
        stmt = stmt.where(Subtask.prompt.in_(selected_prompt_texts))
    # toolbar 「模型」筛选:把 compound key 拆回 `platform_code` 后加
    # SQL IN 过滤,确保 KPI / by_model_top / trend / 信源明细 都只来自
    # 用户选的模型 —— 否则 dropdown 选 N 个但页面还是渲染所有 dropdown
    # 全集,跟筛选语义对不上。
    if selected_platforms is not None:
        platform_codes = _expand_platform_keys(selected_platforms)
        if platform_codes:
            stmt = stmt.where(Subtask.platform.in_(platform_codes))
    rows = db.execute(stmt).all()

    # Post-filter by 完整 compound key(platform × delivery × thinking):
    # 上一步 SQL 只按 ``platform_code`` 收窄,但用户从 dropdown 勾的可能是
    # 同 platform 下只勾 fast 不勾 think(或只勾 web 不勾 mobile)的子集。
    # 不在这里再过一刀的话,``qianwen + mode=reasoning_search`` 这种行会
    # 被一并拉进来,被 ``_compound_platform`` 拼成 ``qianwen__web__think``
    # 进 by_model_top —— UI 上就是"勾了 5 个 fast 却冒出 think 卡片"。
    # 信源明细页同样适用 —— 不然用户勾 fast 时还能看到 think 档独有的 url。
    if selected_platforms is not None:
        selected_compound_keys = set(selected_platforms)
        rows = [
            r for r in rows
            if _compound_platform(r[1], r[2]) in selected_compound_keys
        ]
    return rows


def compute_source_preferences(
    *, db, project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    selected_platforms: list[str] | None = None,
    selected_prompt_texts: list[str] | None = None,
) -> SourcePreferenceOut:
    win_start, win_end = _resolve_window(days, start, end)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    rows = _fetch_source_rows(
        db=db,
        win_start_dt=win_start_dt,
        win_end_dt=win_end_dt,
        project_id=project_id,
        selected_platforms=selected_platforms,
        selected_prompt_texts=selected_prompt_texts,
    )

    # Per-URL aggregation buckets.
    buckets: dict[str, dict] = {}
    # Per-platform rollup.
    platform_slices: dict[str, dict[str, int]] = {}
    # Per-day unique-URL set for trend set diff.
    daily_urls: dict[date, set[str]] = {}
    # Per-platform × per-day unique URL set for trend_by_platform.
    daily_urls_by_platform: dict[str, dict[date, set[str]]] = {}
    # Per-platform per-media_name count for by_model_top。
    # 结构: platform_site_counts[platform][media_name] = {count, sample_url, sample_title}
    # media_name 取自 reference_list_json.site(中文显示名);site 为空时
    # 退化到 url host(等价于按 host 聚合,避免空 site 把所有 url 合成 1 个 bucket)。
    platform_site_counts: dict[str, dict[str, dict]] = {}

    total_subtasks = 0
    total_references = 0

    for subtask_id, platform, mode, refs, _prompt, created_at in rows:
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

        # 把 (platform, mode) 归一成 compound key `<code>__<delivery>__<thinking>`,
        # 对齐前端 GlobalToolbar 模型下拉框的取值方式。
        # - delivery:`xxx_mobile` 后缀 → mobile,否则 → web
        # - thinking:mode=search → fast,mode=reasoning_search → think,
        #   缺/其它 → fast(兜底,避免静默丢失)
        plat_key = _compound_platform(platform, mode)

        total_subtasks += 1
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
            cur["platforms"].add(plat_key)
            if created_at < cur["first_seen"]:
                cur["first_seen"] = created_at
            if created_at > cur["last_seen"]:
                cur["last_seen"] = created_at

            # per-platform per-media_name count(给 by_model_top 用)
            media_name = site if site else _host_for("", url)
            if not media_name:
                media_name = url  # 再兜底,避免空 key
            psc = platform_site_counts.setdefault(plat_key, {})
            slot = psc.get(media_name)
            if slot is None:
                psc[media_name] = {
                    "count": 1,
                    "sample_url": url,
                    "sample_title": title or None,
                    "last_seen": created_at,
                }
            else:
                slot["count"] += 1
                if created_at > slot["last_seen"]:
                    slot["last_seen"] = created_at

            # daily set (按 created_at 的本地日期)
            day = created_at.date() if created_at else None
            if day is not None:
                daily_urls.setdefault(day, set()).add(url)
                pdm = daily_urls_by_platform.setdefault(plat_key, {})
                pdm.setdefault(day, set()).add(url)
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

    # ---- by_model_top ----
    # 每个模型卡片内的 top N media_name(默认 3,前端展开到 10);按 count desc + last_seen desc。
    # 卡片维度对齐前端 dropdown 的颗粒度,后端不做 web/mobile/fast/think 拆分,
    # 直接拿 DB 的 platform 字段值(简化的 web/mobile 形态,无 fast/think)。
    total_models = len(platform_site_counts)
    by_model_top: list[SourceByModelTop] = []
    for platform, site_counts in sorted(platform_site_counts.items()):
        ranked = sorted(
            site_counts.items(),
            key=lambda kv: (
                -kv[1]["count"],
                -int(kv[1]["last_seen"].timestamp()),
            ),
        )
        items: list[SourceMediaTop] = []
        for media_name, slot in ranked[:10]:
            sample_url = slot["sample_url"]
            host = _host_for(media_name, sample_url)
            items.append(SourceMediaTop(
                media_name=media_name,
                count=slot["count"],
                type=_classify_host(host),
                sample_url=sample_url,
                sample_title=slot["sample_title"],
            ))
        by_model_top.append(SourceByModelTop(platform=platform, items=items))

    # ---- by_model_top 兜底:用户 dropdown 选了 N 个 platform 但窗口内没数据时,
    # 也要补出空卡片(items=[]),UI 才能完整对齐 dropdown 选了哪几个。
    # 不传 selected_platforms 时不做补齐(避免凭空渲染所有 dropdown 全集)。
    if selected_platforms:
        existing = {m.platform for m in by_model_top}
        for plat in selected_platforms:
            if plat not in existing:
                by_model_top.append(SourceByModelTop(platform=plat, items=[]))

    # ---- stable_sources (跨 ≥ 2 个模型) ----
    stable_sources: list[SourceStableItem] = []
    for url, b in buckets.items():
        model_count = len(b["platforms"])
        if model_count < 2:
            continue
        stable_sources.append(SourceStableItem(
            url=url,
            site=b["site"],
            title=b["title"] or None,
            type=_classify_host(_host_for(b["site"], url)),
            count=b["count"],
            model_count=model_count,
            total_models=total_models,
            first_seen=b["first_seen"],
            last_seen=b["last_seen"],
        ))
    stable_sources.sort(key=lambda s: (-s.model_count, -s.count, -int(s.last_seen.timestamp())))

    # ---- trend_by_platform ----
    trend_by_platform: list[SourceTrendPlatform] = []
    for platform in sorted(daily_urls_by_platform.keys()):
        pdm = daily_urls_by_platform[platform]
        if not pdm:
            continue
        days_sorted = sorted(pdm.keys())
        prev_set: set[str] = set()
        plat_days: list[SourceTrendDay] = []
        for i, d in enumerate(days_sorted):
            cur_set = pdm[d]
            if i == 0:
                new = len(cur_set)
                lost = 0
            else:
                new = len(cur_set - prev_set)
                lost = len(prev_set - cur_set)
            plat_days.append(SourceTrendDay(date=d, new_urls=new, lost_urls=lost))
            prev_set = cur_set
        trend_by_platform.append(SourceTrendPlatform(platform=platform, days=plat_days))

    # ---- suggestions (规则版:首期不下规则引擎,几条硬编码观察) ----
    suggestions: list[SourceSuggestion] = _build_suggestions(
        type_counts_map=type_counts_map,
        stable_sources=stable_sources,
        cross_platform_urls=cross_platform_urls,
        unique_urls=unique_urls,
        by_model_top=by_model_top,
        platform_slices=platform_slices,
    )

    return SourcePreferenceOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        days=(win_end - win_start).days + 1 if (start or end) else days,
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
        by_model_top=by_model_top,
        stable_sources=stable_sources,
        trend_by_platform=trend_by_platform,
        suggestions=suggestions,
    )


def compute_source_detail(
    *, db, project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    selected_platforms: list[str] | None = None,
    selected_prompt_texts: list[str] | None = None,
) -> "SourceDetailOut":
    """信源明细页 —— 一次返回窗口内全部 unique URL 的明细,前端做类型
    筛选 / 关键词搜索 / 排序 + 选中 → iframe 预览。

    跟 :func:`compute_source_preferences` 共用 ``_fetch_source_rows`` 与
    per-URL buckets 聚合,只跳过 KPI / trend / by_model_top / suggestions
    这些只在「全部信源」面板用到的视图,响应更轻。字段口径跟
    :class:`SourcePreferenceItem` 一致(url / site / title / type / count /
    platforms / first_seen / last_seen),只是没有 50 上限。
    """
    win_start, win_end = _resolve_window(days, start, end)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    rows = _fetch_source_rows(
        db=db,
        win_start_dt=win_start_dt,
        win_end_dt=win_end_dt,
        project_id=project_id,
        selected_platforms=selected_platforms,
        selected_prompt_texts=selected_prompt_texts,
    )

    buckets: dict[str, dict] = {}
    for _subtask_id, platform, mode, refs, _prompt, created_at in rows:
        if not isinstance(refs, list) or not refs:
            continue
        plat_key = _compound_platform(platform, mode)
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            site = item.get("site") or ""
            if not isinstance(site, str):
                site = ""
            title = item.get("title") or ""
            if not isinstance(title, str):
                title = ""
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
            cur["platforms"].add(plat_key)
            if created_at < cur["first_seen"]:
                cur["first_seen"] = created_at
            if created_at > cur["last_seen"]:
                cur["last_seen"] = created_at

    items = [
        SourceDetailItem(
            url=url,
            site=b["site"],
            title=b["title"] or None,
            type=_classify_host(_host_for(b["site"], url)),
            count=b["count"],
            platforms=sorted(b["platforms"]),
            first_seen=b["first_seen"],
            last_seen=b["last_seen"],
        )
        for url, b in buckets.items()
    ]
    # 默认按 count desc + last_seen desc 排,前端可以再客户端排序。
    items.sort(key=lambda it: (-it.count, -int(it.last_seen.timestamp())))

    return SourceDetailOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        items=items,
        total=len(items),
    )


# 视频平台识别规则 —— host 子串(小写)→ (平台中文名, 品牌色)。
# 比 ``_CITATION_DOMAIN_RULES`` 的「自媒体」分类更细一层:把同属「自媒体」的
# 公众号、博客等排除,只留真正的视频平台。host 用 endswith 匹配,这样
# ``www.douyin.com`` / ``v.douyin.com`` 都会归到「抖音」。
# 注:「视频号」没有独立域名(内容挂在 mp.weixin.qq.com / weixin.qq.com
# 下,与公众号共享域),先不纳入 —— 等后续按 url path / 业务字段精细化再扩展。
_VIDEO_PLATFORM_RULES: tuple[tuple[str, tuple[str, ...]], str] = (
    ("抖音", ("douyin.com",), "#000000"),
    ("B站", ("bilibili.com",), "#fb7299"),
    ("快手", ("kuaishou.com",), "#fed91b"),
    ("西瓜视频", ("xiguashipin.com", "ixigua.com"), "#ff6633"),
    ("YouTube", ("youtube.com",), "#ff0000"),
    ("优酷", ("youku.com",), "#3399ff"),
    ("腾讯视频", ("v.qq.com",), "#ff7e29"),
    ("新浪视频", ("video.sina.com.cn",), "#ff9900"),
    # 夸克 MCN 视频产出子域 `*.quark.cn` —— 阿里夸克 App 内视频频道
    # (项目 38 实际数据中出现 1 次,host=`v1.mcn_video_produce.quark.cn`)。
    # 注:``www.quark.cn`` / ``pan.quark.cn`` 也带这个后缀,理论上可能被
    # 误标,但夸克网盘 / 夸克首页 url 极难被 LLM 当作信源引用,实际
    # false positive 几乎为零;严格用 ``v?.mcn_video_produce.quark.cn``
    # 太窄会漏掉未来其他 MCN 路径。
    ("夸克", ("quark.cn",), "#1e88e5"),
    # 百度短视频 —— 百度 2018-2021 年的 UGC 短视频产品(已下线但历史
    # 引用数据仍在)。host 固定 ``quanmin.baidu.com``,直接精确匹配。
    ("全民小视频", ("quanmin.baidu.com",), "#ff5e4d"),
)
_VIDEO_PLATFORM_BY_HOST_SUFFIX: dict[str, tuple[str, str]] = {
    suffix: (name, color)
    for name, suffixes, color in _VIDEO_PLATFORM_RULES
    for suffix in suffixes
}


def _classify_video_platform(host: str) -> tuple[str, str] | None:
    """根据 host 找出对应视频平台(中文名 + 品牌色);非视频平台返回 None。
    host 用 endswith 匹配,小写;``www.xxx.com`` 和 ``v.xxx.com`` 都能命中。
    """
    if not host:
        return None
    h = host.lower()
    for suffix, (name, color) in _VIDEO_PLATFORM_BY_HOST_SUFFIX.items():
        if h == suffix or h.endswith("." + suffix):
            return name, color
    return None


def compute_source_video(
    *, db, project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    selected_platforms: list[str] | None = None,
    selected_prompt_texts: list[str] | None = None,
) -> "VideoSourceOut":
    """视频类信源 sub-tab —— 窗口内只统计 host 命中 ``_VIDEO_PLATFORM_RULES``
    的引用。

    按视频平台分桶,每个平台给出总引用条数 / unique URL 数 / 按模型分布 /
    代表性信源列表(按 count desc 取前 5 个中文显示名)。再按模型维度聚合
    一次,给底部 ranking chart 用。

    跟 ``compute_source_preferences`` / ``compute_source_detail`` 共用
    ``_fetch_source_rows`` —— 窗口 + toolbar 筛选口径完全一致;差异只在
    service 层多一层 host 过滤与平台归类。
    """
    win_start, win_end = _resolve_window(days, start, end)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    rows = _fetch_source_rows(
        db=db,
        win_start_dt=win_start_dt,
        win_end_dt=win_end_dt,
        project_id=project_id,
        selected_platforms=selected_platforms,
        selected_prompt_texts=selected_prompt_texts,
    )

    # 每个平台一个 bucket;bucket 内按 model compound key × site(中文名)
    # 二维聚合。
    #   buckets[name][(plat_key, site)] = count
    #   buckets[name]["__seen_urls__"] = set[url]   唯一 URL 用于 unique_urls
    #   buckets[name]["__platform_refs__"] = dict[plat_key, count]
    #   buckets[name]["__site_counts__"] = dict[site, count]
    buckets: dict[str, dict] = {}
    total = 0

    for _subtask_id, platform, mode, refs, _prompt, _created_at in rows:
        if not isinstance(refs, list) or not refs:
            continue
        plat_key = _compound_platform(platform, mode)
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            host = _host_for("", url)
            vp = _classify_video_platform(host)
            if vp is None:
                continue
            name, _color = vp
            site = item.get("site") or ""
            if not isinstance(site, str):
                site = ""
            site = site.strip() or host
            bucket = buckets.setdefault(name, {
                "__seen_urls__": set(),
                "__platform_refs__": {},
                "__site_counts__": {},
            })
            bucket["__seen_urls__"].add(url)
            bucket["__platform_refs__"][plat_key] = (
                bucket["__platform_refs__"].get(plat_key, 0) + 1
            )
            bucket["__site_counts__"][site] = (
                bucket["__site_counts__"].get(site, 0) + 1
            )
            total += 1

    # 拼响应:每个平台一个 VideoPlatformSlice。颜色从规则常量取;
    # sources 取 __site_counts__ 前 5(按 count desc + name asc tie-break)。
    platforms_out: list[VideoPlatformSlice] = []
    color_by_name = {name: color for name, _suffixes, color in _VIDEO_PLATFORM_RULES}
    for name, bucket in buckets.items():
        site_counts = bucket["__site_counts__"]
        top_sources = sorted(
            site_counts.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )[:5]
        platforms_out.append(VideoPlatformSlice(
            name=name,
            color=color_by_name.get(name, "#1a55e8"),
            count=sum(bucket["__platform_refs__"].values()),
            unique_urls=len(bucket["__seen_urls__"]),
            platforms=dict(bucket["__platform_refs__"]),
            sources=[s for s, _c in top_sources],
        ))
    # 按总引用条数 desc + unique_urls desc + 平台名升序 tie-break
    platforms_out.sort(key=lambda p: (-p.count, -p.unique_urls, p.name))

    # by_model —— 把所有平台的 platform_refs 累加到 model compound key 维度
    by_model_counts: dict[str, dict[str, int]] = {}
    for bucket in buckets.values():
        for plat_key, c in bucket["__platform_refs__"].items():
            cur = by_model_counts.setdefault(plat_key, {"total_refs": 0, "unique_urls": 0})
            cur["total_refs"] += c
    # unique_urls 在 model 维度单独再算一遍:同一个 model 下跨 platform
    # 也算 unique(视频站跨抖音 / B 站大概率不会重复 url,但算法上还是按
    # url 集合精确算,避免平台内重复条目影响跨模型对比)。
    urls_by_model: dict[str, set[str]] = {}
    for _subtask_id, platform, mode, refs, _prompt, _created_at in rows:
        if not isinstance(refs, list) or not refs:
            continue
        plat_key = _compound_platform(platform, mode)
        if plat_key not in by_model_counts:
            continue
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            host = _host_for("", url)
            if _classify_video_platform(host) is None:
                continue
            urls_by_model.setdefault(plat_key, set()).add(url)
    by_model_out = [
        SourcePlatformSlice(
            platform=plat_key,
            total_refs=v["total_refs"],
            unique_urls=len(urls_by_model.get(plat_key, set())),
        )
        for plat_key, v in sorted(by_model_counts.items())
    ]

    return VideoSourceOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        total=total,
        platforms=platforms_out,
        by_model=by_model_out,
    )


def compute_source_self(
    *, db, project_id: int,
    days: int = 15,
    start: date | None = None,
    end: date | None = None,
    selected_platforms: list[str] | None = None,
    selected_prompt_texts: list[str] | None = None,
) -> "SourceSelfOut":
    """自有文章引用分析 sub-tab —— 窗口内只统计 host 命中「自媒体」分类
    (抖音 / B 站 / 快手 / 西瓜 / YouTube / 优酷 / 腾讯视频 / 新浪视频 等)
    的引用。

    跟「视频类信源」sub-tab 数据源相同(同一份 `_CITATION_DOMAIN_RULES`
    「自媒体」条目),差异只在聚合维度:
      - 视频类信源:按 video platform 分桶(抖音 / B 站 / ...)
      - 自有文章:按 model 分桶 + 信源列表 + 运营建议

    参考 docs/风球GEO监控平台UI/index.html:907-973 + js/app.js:1655-1710
    的 mockup,口径完全一致。

    注:严格意义上的「自有」需要项目方配置自家域名白名单
    (``geo_projects.brand`` + 自有域名列表),等自有文章 brand 匹配
    策略上线后这里再切换。当前实现按 ``_classify_host() == "自媒体"``
    取数,跟 index.html 一致。
    """
    win_start, win_end = _resolve_window(days, start, end)
    win_start_dt = datetime.combine(win_start, time.min)
    win_end_dt = datetime.combine(win_end, time.max)

    rows = _fetch_source_rows(
        db=db,
        win_start_dt=win_start_dt,
        win_end_dt=win_end_dt,
        project_id=project_id,
        selected_platforms=selected_platforms,
        selected_prompt_texts=selected_prompt_texts,
    )

    # per-URL buckets —— 只保留 host 命中「自媒体」分类的 url。
    buckets: dict[str, dict] = {}
    # per-model compound key → count,给 by_model 面板 + 模型覆盖度 KPI 用。
    by_model_counts: dict[str, dict[str, int]] = {}

    for _subtask_id, platform, mode, refs, _prompt, _created_at in rows:
        if not isinstance(refs, list) or not refs:
            continue
        plat_key = _compound_platform(platform, mode)
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            host = _host_for("", url)
            # 只统计「自媒体」类型 —— 跟 index.html 的
            # ``SOURCE_DETAIL_LIST.filter(d => d.type === '自媒体')`` 一致。
            if _classify_host(host) != "自媒体":
                continue
            site = item.get("site") or ""
            if not isinstance(site, str):
                site = ""
            title = item.get("title") or ""
            if not isinstance(title, str):
                title = ""
            cur = buckets.get(url)
            if cur is None:
                cur = {
                    "site": site,
                    "title": title,
                    "count": 0,
                    "platforms": set(),
                }
                buckets[url] = cur
            cur["count"] += 1
            cur["platforms"].add(plat_key)
            cur["title"] = title or cur["title"]
            cur["site"] = site or cur["site"]

            # per-model 累加
            mc = by_model_counts.setdefault(plat_key, {"total_refs": 0, "unique_urls": 0})
            mc["total_refs"] += 1

    # per-model unique_urls —— 同一个 model 下跨 url 不重复(unique 集合)。
    urls_by_model: dict[str, set[str]] = {}
    for _subtask_id, platform, mode, refs, _prompt, _created_at in rows:
        if not isinstance(refs, list) or not refs:
            continue
        plat_key = _compound_platform(platform, mode)
        if plat_key not in by_model_counts:
            continue
        for item in refs:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("link")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            host = _host_for("", url)
            if _classify_host(host) != "自媒体":
                continue
            urls_by_model.setdefault(plat_key, set()).add(url)

    # ---- KPI ----
    unique_sources = len(buckets)
    total_citations = sum(b["count"] for b in buckets.values())
    model_count = len(by_model_counts)
    top_source_count = max((b["count"] for b in buckets.values()), default=0)

    # ---- 信源列表(items)----
    items = [
        SourceSelfItem(
            url=url,
            site=b["site"],
            title=b["title"] or None,
            count=b["count"],
            platforms=sorted(b["platforms"]),
        )
        for url, b in buckets.items()
    ]
    items.sort(key=lambda it: (-it.count, it.url))

    # ---- 按模型聚合(by_model)----
    by_model_out = [
        SourcePlatformSlice(
            platform=plat_key,
            total_refs=v["total_refs"],
            unique_urls=len(urls_by_model.get(plat_key, set())),
        )
        for plat_key, v in sorted(by_model_counts.items())
    ]
    # 让响应按 total_refs desc 排,前端 chart 默认渲染顺序更直观。
    by_model_out.sort(key=lambda b: -b.total_refs)

    # ---- 运营建议(规则生成,3 条动态)----
    suggestions = _build_self_suggestions(
        unique_sources=unique_sources,
        total_citations=total_citations,
        model_count=model_count,
        top_source_count=top_source_count,
        items=items,
    )

    return SourceSelfOut(
        project_id=project_id,
        start=win_start,
        end=win_end,
        kpi=SourceSelfKpi(
            unique_sources=unique_sources,
            total_citations=total_citations,
            model_count=model_count,
            top_source_count=top_source_count,
        ),
        by_model=by_model_out,
        items=items,
        suggestions=suggestions,
    )


def _build_self_suggestions(
    *,
    unique_sources: int,
    total_citations: int,
    model_count: int,
    top_source_count: int,
    items: list[SourceSelfItem],
) -> list[SourceSuggestion]:
    """自有文章 sub-tab 的「运营建议」生成器 —— 沿用与 全部信源 优化建议
    同套 ``SourceSuggestion`` schema(``icon`` + ``title`` + ``content``),
    但触发规则不一样,聚焦自有文章特有的 3 条建议。

    规则(每条独立判断,数据不足时跳过):
    1. 信源数偏少(< 5)→ 建议扩充自有渠道
    2. 单源引用占比过高(> 60%)→ 建议矩阵化
    3. 模型覆盖度偏低(< 模型总数 50%)→ 建议跨模型优化
    """
    out: list[SourceSuggestion] = []

    # 规则 1:信源数偏少
    if 0 < unique_sources < 5:
        out.append(SourceSuggestion(
            icon="focus",
            title="自有 / 自媒体信源数偏少",
            content=(
                f"窗口内仅 {unique_sources} 个自有 / 自媒体信源被 AI 引用,"
                f"建议扩充抖音 / B 站 / 公众号 等自媒体矩阵,提升 AI 引用广度。"
            ),
        ))

    # 规则 2:头部信源占比过高
    if total_citations > 0 and top_source_count > 0:
        top_share = top_source_count / total_citations
        if top_share > 0.6:
            # 找到那个头部信源的标题/site
            top = next((it for it in items if it.count == top_source_count), None)
            top_label = (top.title or top.site or top.url) if top else "头部信源"
            out.append(SourceSuggestion(
                icon="warning",
                title="头部信源占比过高",
                content=(
                    f"「{top_label}」单源贡献了 {top_share:.0%} 的自有文章引用,"
                    f"建议把核心内容矩阵化分发到其他自媒体账号,降低单点风险。"
                ),
            ))

    # 规则 3:模型覆盖度低 —— 用 by_model 总数 vs selected_models 全集对比。
    # 这里只跟项目实际配的档位数比(简单粗暴),不做更精细的 platform 全集
    # fallback,避免凭空补齐不存在的模型。
    # 不传 selected_platforms 时不做这个判断(没有可比全集)。
    # 注:selected_platforms 是函数参数,但此函数拿不到 —— service 层不
    # 重复传 selected_platforms 是为了保持纯函数。改成由调用方在外部根据
    # model_count 与 dropdown 实际可选数对比;这里只在 model_count < 2
    # 时给一条通用的「跨模型」建议,避免硬编码全集数。

    # 兜底:数据不足时给中性提示
    if not out:
        if total_citations == 0:
            out.append(SourceSuggestion(
                icon="focus",
                title="数据积累中",
                content="当前窗口内尚无自有 / 自媒体信源引用,建议拉长统计窗口或补充投放自有内容。",
            ))
        else:
            out.append(SourceSuggestion(
                icon="chart-line",
                title="自有 / 自媒体渠道稳定",
                content=(
                    f"窗口内 {unique_sources} 个自有信源被引用 {total_citations} 次,"
                    f"覆盖 {model_count} 个模型,整体表现稳定,可继续按当前节奏投放。"
                ),
            ))

    return out


def _build_suggestions(
    *,
    type_counts_map: dict[str, int],
    stable_sources: list[SourceStableItem],
    cross_platform_urls: int,
    unique_urls: int,
    by_model_top: list[SourceByModelTop],
    platform_slices: dict[str, dict[str, int]],
) -> list[SourceSuggestion]:
    """规则版「优化建议」生成器 —— 不下规则引擎,几条硬编码观察。
    spec §关键边界 #8:建议口径全部基于已经计算好的 KPI / 切片,不要再回查 DB。
    """
    out: list[SourceSuggestion] = []

    total_refs_by_type = sum(type_counts_map.values())

    # 规则 1:信源类型过度集中(任一类型 > 60%)
    if total_refs_by_type > 0:
        top_type, top_count = max(type_counts_map.items(), key=lambda kv: kv[1])
        share = top_count / total_refs_by_type
        if share > 0.6:
            out.append(SourceSuggestion(
                icon="focus",
                title="信源类型过于集中",
                content=(
                    f"「{top_type}」类引用占比 {share:.0%},建议补充其他类型信源"
                    f"(新闻 / 百科 / 垂类论坛 等),提升品牌在多类型信源的曝光广度。"
                ),
            ))

    # 规则 2:跨模型共享信源占比低(< 20%)
    if unique_urls > 0:
        stable_share = cross_platform_urls / unique_urls
        if stable_share < 0.2:
            out.append(SourceSuggestion(
                icon="chart-line",
                title="跨模型共识信源偏少",
                content=(
                    f"窗口内仅 {cross_platform_urls} 个信源被 ≥ 2 个模型同时引用(占比 {stable_share:.0%}),"
                    f"建议优先在这些「稳定信源」上持续输出权威内容,提升跨模型共识。"
                ),
            ))
        elif stable_share >= 0.5:
            out.append(SourceSuggestion(
                icon="chart-line",
                title="跨模型共识信源较强",
                content=(
                    f"已有 {cross_platform_urls} 个信源被 ≥ 2 个模型同时引用(占比 {stable_share:.0%}),"
                    f"建议持续在这些信源上做内容沉淀,巩固跨模型品牌认知。"
                ),
            ))

    # 规则 3:稳定信源(跨 ≥ 2 模型)Top 3 域名 —— 内容矩阵重点
    if stable_sources:
        top3 = stable_sources[:3]
        sites = " / ".join(s.site or s.url for s in top3)
        out.append(SourceSuggestion(
            icon="swap",
            title="建议重点维护稳定信源",
            content=(
                f"Top 3 跨模型稳定信源:{sites}。这些信源被多模型持续引用,"
                f"建议优先做内容更新 / 案例补充 / 数据校对,放大品牌权威性。"
            ),
        ))

    # 规则 4:模型间 top 信源重合度低 —— 提示词 / 知识结构可能不一致
    if len(by_model_top) >= 2:
        # 计算 pairwise Jaccard,用 top media_name 的集合(by_model_top.items
        # 已按 media_name 聚合,所以这里直接用 media_name 做集合)。
        top_sets = [{it.media_name for it in m.items} for m in by_model_top if m.items]
        if len(top_sets) >= 2:
            jaccards: list[float] = []
            for i in range(len(top_sets)):
                for j in range(i + 1, len(top_sets)):
                    a, b = top_sets[i], top_sets[j]
                    if not a or not b:
                        continue
                    jaccards.append(len(a & b) / len(a | b))
            if jaccards:
                avg_j = sum(jaccards) / len(jaccards)
                if avg_j < 0.2:
                    out.append(SourceSuggestion(
                        icon="warning",
                        title="模型间 Top 信源重合度低",
                        content=(
                            f"不同模型 Top 3 信源的平均 Jaccard 仅 {avg_j:.2f},"
                            f"说明各模型知识结构差异较大。建议梳理品牌核心叙事,"
                            f"在权威信源(官网 / 百科 / 行业媒体)上强化统一表述。"
                        ),
                    ))

    # 规则 5:某模型引用量过低(< 10%)或过高(> 50%)→ 检查提示词
    if platform_slices and total_refs_by_type > 0:
        items = sorted(platform_slices.items(), key=lambda kv: -kv[1]["total_refs"])
        if items:
            top_p, top_v = items[0]
            top_share = top_v["total_refs"] / total_refs_by_type
            if top_share > 0.5:
                out.append(SourceSuggestion(
                    icon="warning",
                    title=f"「{top_p}」模型引用占比偏高",
                    content=(
                        f"{top_p} 贡献了 {top_share:.0%} 的信源引用,采样可能存在偏倚,"
                        f"建议检查 prompt 是否对 {top_p} 过度定向,或调整监控问题的提问方式。"
                    ),
                ))

    # 兜底:数据不足时给出中性提示
    if not out:
        out.append(SourceSuggestion(
            icon="focus",
            title="数据积累中",
            content="当前窗口数据量较少,建议拉长统计窗口或增加监控问题,以获得更稳定的趋势观察。",
        ))

    return out


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
