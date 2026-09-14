/**
 * 「信源明细」sub-tab —— 完成态。
 *
 * 参照 docs/风球GEO监控平台UI/index.html:1086-1126 的 30/70 分屏:
 *   - 左侧 30%:信源列表 —— 类型筛选 + 排序 + 关键词搜索 + 滚动列表
 *   - 右侧 70%:浏览框 —— 顶部 URL bar + 新窗口打开按钮 + body 内嵌 iframe
 *
 * 数据由后端 ``GET /projects/{id}/source-detail`` 一次返回窗口内全部
 * unique URL(items 不分页),前端按 toolbar 同步(models / prompts / 日期)
 * 重拉,然后在客户端做类型筛选 / 关键词搜索 / 排序 —— 数据量通常几十到
 * 几百条,客户端 filter 完全够用,避免给后端再加一个复杂的查询参数协议。
 *
 * iframe 加载策略:多数目标站会返回 ``X-Frame-Options: DENY`` 或
 * ``Content-Security-Policy: frame-ancestors 'none'``,这里用 5 秒超时 +
 * ``onError`` 兜底显示「无法内嵌」卡(列出 url / 类型 / 引用次数 + 新窗口
 * 打开按钮),跟 index.html:1622-1643 的 ``_sdShowFallback`` 一致。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Button, Empty, Input, Select, Skeleton, message } from "antd";
import { GlobalOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  getSourceDetail,
  getProject,
  type ProjectPlatform,
  type SourceDetailItem,
  type SourceDetailOut,
} from "../../../api/projects";
import { rowKeyOfPlatform } from "../platforms";
import { useToolbarFilter } from "../../../components/ToolbarFilterContext";

interface Props {
  projectId: number;
}

type SortKey = "citations" | "title";
type LoadState = "loading" | "loaded" | "fallback";

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

// 主流默认会拒绝内嵌的站 —— 列表内直接展示「无法内嵌」卡,跳过 5s 等待。
const KNOWN_NO_FRAME_HOSTS = new Set<string>([
  "baidu.com",
  "baike.baidu.com",
  "baijiahao.baidu.com",
  "tieba.baidu.com",
  "mp.weixin.qq.com",
  "weixin.qq.com",
  "zhihu.com",
  "xiaohongshu.com",
  "douban.com",
  "weibo.com",
  "weibo.cn",
  "douyin.com",
  "bilibili.com",
  "kuaishou.com",
  "youtube.com",
  "qq.com",
  "163.com",
]);

export default function SourceDetail({ projectId }: Props) {
  const [out, setOut] = useState<SourceDetailOut | null>(null);
  const [loading, setLoading] = useState(true);
  // 项目当前配置的 platform rows;``null`` 表示还在加载。``effectiveModels``
  // 全选 fallback 用 —— 跟 AllSources 同款实现。
  const [projectPlatforms, setProjectPlatforms] = useState<ProjectPlatform[] | null>(null);
  const toolbar = useToolbarFilter();

  useEffect(() => {
    let cancelled = false;
    getProject(projectId)
      .then((d) => { if (!cancelled) setProjectPlatforms(d.platforms); })
      .catch(() => { if (!cancelled) setProjectPlatforms([]); });
    return () => { cancelled = true; };
  }, [projectId]);

  const effectiveModels = useMemo<string[] | null | undefined>(() => {
    if (toolbar.selectedModels !== null) return toolbar.selectedModels;
    if (projectPlatforms === null) return undefined;
    return projectPlatforms.map(rowKeyOfPlatform);
  }, [toolbar.selectedModels, projectPlatforms]);

  const dateQuery = useMemo(
    () => toolbar.selectedDateRange ?? { days: 15 },
    [toolbar.selectedDateRange],
  );
  const dateKey = useMemo(() => JSON.stringify(dateQuery), [dateQuery]);

  const promptsKey = useMemo(
    () => (toolbar.selectedPromptIds ? [...toolbar.selectedPromptIds].sort().join("|") : "all"),
    [toolbar.selectedPromptIds],
  );

  useEffect(() => {
    if (effectiveModels === undefined) return;
    let cancelled = false;
    setLoading(true);
    getSourceDetail(projectId, {
      days: dateQuery.days,
      start: dateQuery.start,
      end: dateQuery.end,
      models: effectiveModels,
      prompts: toolbar.selectedPromptIds ?? undefined,
    })
      .then((d) => { if (!cancelled) setOut(d); })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "信源明细数据加载失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId, toolbar.version, effectiveModels, dateKey, promptsKey]);

  if (loading) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (!out || out.items.length === 0) {
    return <Empty description="窗口内尚无信源数据" style={{ padding: 32 }} />;
  }

  return <SourceDetailBody items={out.items} />;
}

/* ------------------------------------------------------------------
 * 主体:左侧列表 + 右侧 iframe
 * ------------------------------------------------------------------ */

function SourceDetailBody({ items }: { items: SourceDetailItem[] }) {
  // 类型 / 排序 / 搜索 —— 客户端状态,改时不重拉。
  const [typeFilter, setTypeFilter] = useState<string>("");
  const [sortKey, setSortKey] = useState<SortKey>("citations");
  const [search, setSearch] = useState<string>("");
  // 当前选中的 URL —— 决定右侧 iframe / 兜底卡显示什么。
  const [selectedUrl, setSelectedUrl] = useState<string | null>(null);

  // 全部 type 列表(按出现频率排序)—— 跟后端 _CITATION_DOMAIN_RULES 一致。
  const types = useMemo(() => {
    const m = new Map<string, number>();
    for (const it of items) m.set(it.type, (m.get(it.type) ?? 0) + it.count);
    return Array.from(m.entries())
      .sort((a, b) => b[1] - a[1])
      .map(([t]) => t);
  }, [items]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    let list = items.filter((it) =>
      (!typeFilter || it.type === typeFilter) &&
      (!q ||
        (it.title ?? "").toLowerCase().includes(q) ||
        it.url.toLowerCase().includes(q)),
    );
    if (sortKey === "title") {
      list = [...list].sort((a, b) =>
        (a.title ?? a.url).localeCompare(b.title ?? b.url, "zh"),
      );
    } else {
      // citations desc,last_seen desc tie-breaker
      list = [...list].sort((a, b) =>
        b.count - a.count || (b.last_seen > a.last_seen ? 1 : b.last_seen < a.last_seen ? -1 : 0),
      );
    }
    return list;
  }, [items, typeFilter, sortKey, search]);

  const selected = useMemo(
    () => items.find((it) => it.url === selectedUrl) ?? null,
    [items, selectedUrl],
  );

  return (
    <div className="sd-split">
      {/* 左侧 30% 列表 */}
      <div className="sd-list-panel">
        <div className="sd-toolbar">
          <Select
            className="sd-select"
            size="small"
            value={typeFilter || undefined}
            placeholder="全部类型"
            allowClear
            onChange={(v) => setTypeFilter(v ?? "")}
            options={types.map((t) => ({ value: t, label: t }))}
          />
          <Select
            className="sd-select"
            size="small"
            value={sortKey}
            onChange={(v) => setSortKey(v as SortKey)}
            options={[
              { value: "citations", label: "按引用次数" },
              { value: "title", label: "按标题" },
            ]}
          />
        </div>
        <div className="sd-search">
          <SearchOutlined className="sd-search-icon" />
          <Input
            className="sd-search-input"
            placeholder="搜索标题 / URL…"
            allowClear
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            size="small"
          />
        </div>
        <div className="sd-list">
          {filtered.length === 0 ? (
            <div className="sd-empty-inline">
              没有匹配的信源
              <div className="sd-empty-sub">试试更换关键词或类型</div>
            </div>
          ) : (
            filtered.map((it) => (
              <div
                key={it.url}
                className={`sd-item${selectedUrl === it.url ? " active" : ""}`}
                onClick={() => setSelectedUrl(it.url)}
                title={it.url}
              >
                <div className="sd-item-title">
                  {it.title || it.url}
                </div>
                <div className="sd-item-meta">
                  <span
                    className="sd-item-type"
                    style={{
                      color: TYPE_COLOR[it.type] ?? "#1a55e8",
                      background: `color-mix(in srgb, ${TYPE_COLOR[it.type] ?? "#1a55e8"} 12%, transparent)`,
                    }}
                  >
                    {it.type}
                  </span>
                  <span className="sd-item-cite">引用 {it.count} 次</span>
                </div>
              </div>
            ))
          )}
        </div>
        <div className="sd-list-footer">
          {filtered.length} / {items.length} 条信源
        </div>
      </div>

      {/* 右侧 70% 浏览框 */}
      <div className="sd-frame-panel">
        {selected ? (
          <FramePanel item={selected} />
        ) : (
          <div className="sd-empty">
            <GlobalOutlined className="sd-empty-icon" />
            <p>从左侧列表点击任意信源</p>
            <p className="sd-empty-sub">网页内容将直接在此浏览框内加载,无需跳出系统</p>
          </div>
        )}
      </div>

      <style>{`
        .sd-split {
          display: flex;
          gap: 12px;
          height: calc(100vh - 260px);
          min-height: 480px;
        }
        .sd-list-panel {
          flex: 0 0 30%;
          max-width: 30%;
          display: flex;
          flex-direction: column;
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          overflow: hidden;
        }
        .sd-toolbar {
          display: flex;
          gap: 8px;
          padding: 12px 12px 0;
        }
        .sd-select { flex: 1; min-width: 0; }
        .sd-search {
          position: relative;
          margin: 8px 12px;
        }
        .sd-search-icon {
          position: absolute;
          left: 10px;
          top: 50%;
          transform: translateY(-50%);
          color: var(--text-tertiary, #bfbfbf);
          pointer-events: none;
          z-index: 1;
        }
        .sd-search-input .ant-input {
          padding-left: 30px;
        }
        .sd-list {
          flex: 1;
          overflow-y: auto;
          padding: 4px 8px;
        }
        .sd-item {
          padding: 10px 10px;
          border-radius: 6px;
          cursor: pointer;
          transition: background .12s, box-shadow .12s;
          border: 1px solid transparent;
        }
        .sd-item:hover { background: rgba(26, 85, 232, 0.04); }
        .sd-item.active {
          background: rgba(26, 85, 232, 0.06);
          border-color: rgba(26, 85, 232, 0.4);
        }
        .sd-item-title {
          font-size: 14px;
          font-weight: 500;
          color: var(--text-primary, #1f1f1f);
          line-height: 1.45;
          overflow: hidden;
          text-overflow: ellipsis;
          display: -webkit-box;
          -webkit-line-clamp: 2;
          -webkit-box-orient: vertical;
        }
        .sd-item.active .sd-item-title { color: var(--brand-blue, #1a55e8); }
        .sd-item-meta {
          display: flex;
          align-items: center;
          gap: 8px;
          margin-top: 6px;
        }
        .sd-item-type {
          font-size: 12px;
          border-radius: 6px;
          padding: 1px 6px;
          white-space: nowrap;
        }
        .sd-item-cite {
          font-size: 12px;
          color: var(--text-tertiary, #bfbfbf);
          white-space: nowrap;
        }
        .sd-list-footer {
          padding: 8px 14px;
          border-top: 1px solid var(--border-light, #f0f0f0);
          font-size: 12px;
          color: var(--text-tertiary, #bfbfbf);
        }
        .sd-empty-inline {
          padding: 32px 16px;
          text-align: center;
          color: var(--text-tertiary, #bfbfbf);
          font-size: 13px;
        }
        .sd-empty-sub { font-size: 12px; color: var(--text-tertiary, #bfbfbf); margin-top: 4px; }

        .sd-frame-panel {
          flex: 1;
          min-width: 0;
          display: flex;
          flex-direction: column;
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          overflow: hidden;
        }
        .sd-frame-header {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 9px 14px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          background: var(--bg-page, #fafafa);
        }
        .sd-frame-dots {
          display: flex;
          gap: 5px;
          flex: none;
        }
        .sd-frame-dots span {
          width: 9px; height: 9px;
          border-radius: 50%;
          background: var(--border-light, #f0f0f0);
        }
        .sd-frame-dots span:nth-child(1) { background: #ff5f57; }
        .sd-frame-dots span:nth-child(2) { background: #ffbd2e; }
        .sd-frame-dots span:nth-child(3) { background: #28c941; }
        .sd-frame-url {
          flex: 1;
          min-width: 0;
          font-size: 12px;
          color: var(--text-secondary, #4f4f4f);
          background: var(--bg-page, #fafafa);
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 999px;
          padding: 4px 14px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sd-open-btn { flex: none; font-size: 12px; padding: 0 8px; }
        .sd-frame-body {
          flex: 1;
          position: relative;
          min-height: 0;
        }
        .sd-frame {
          width: 100%;
          height: 100%;
          border: none;
          background: #fff;
        }
        .sd-loading {
          position: absolute;
          inset: 0;
          z-index: 1;
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          font-size: 14px;
          color: var(--text-tertiary, #bfbfbf);
          background: #fff;
        }
        .sd-spinner {
          width: 16px; height: 16px;
          border: 2px solid var(--border-light, #f0f0f0);
          border-top-color: var(--brand-blue, #1a55e8);
          border-radius: 50%;
          animation: sd-spin .8s linear infinite;
        }
        @keyframes sd-spin { to { transform: rotate(360deg); } }
        .sd-fallback {
          height: 100%;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          padding: 32px;
          gap: 12px;
          color: var(--text-secondary, #4f4f4f);
          text-align: center;
        }
        .sd-fallback-icon {
          font-size: 40px;
          color: var(--text-tertiary, #bfbfbf);
        }
        .sd-fallback-reason {
          font-size: 12px;
          color: var(--text-tertiary, #bfbfbf);
          margin: 0;
        }
        .sd-fallback-card {
          margin-top: 12px;
          padding: 14px 18px;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          background: var(--bg-page, #fafafa);
          min-width: 320px;
          text-align: left;
        }
        .sd-fallback-row {
          display: flex;
          gap: 12px;
          padding: 6px 0;
          font-size: 13px;
          border-bottom: 1px dashed var(--border-light, #f0f0f0);
        }
        .sd-fallback-row:last-child { border-bottom: 0; }
        .sd-fallback-row span {
          width: 80px;
          color: var(--text-tertiary, #bfbfbf);
          flex-shrink: 0;
        }
        .sd-fallback-row strong {
          flex: 1;
          word-break: break-all;
          color: var(--text-primary, #1f1f1f);
          font-weight: 500;
        }
        .sd-fallback-actions {
          display: flex;
          gap: 8px;
        }

        .sd-empty {
          height: 100%;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          color: var(--text-tertiary, #bfbfbf);
          font-size: 14px;
          gap: 4px;
        }
        .sd-empty-icon { font-size: 34px; margin-bottom: 6px; }
        .sd-empty-sub { font-size: 12px; color: var(--text-tertiary, #bfbfbf); }
      `}</style>
    </div>
  );
}

/* ------------------------------------------------------------------
 * 右侧浏览框:iframe + 已知禁止嵌套 → 兜底卡
 * ------------------------------------------------------------------ */

function FramePanel({ item }: { item: SourceDetailItem }) {
  const host = useMemo(() => {
    try {
      return new URL(item.url).hostname.replace(/^www\./, "");
    } catch {
      return "";
    }
  }, [item.url]);

  const isBlocked = KNOWN_NO_FRAME_HOSTS.has(host);
  const [loadState, setLoadState] = useState<LoadState>(
    isBlocked ? "fallback" : "loading",
  );
  const [fallbackReason, setFallbackReason] = useState<string>(
    isBlocked ? "该网站禁止被内嵌加载(X-Frame-Options)" : "",
  );
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // 用 key 强制重置 iframe —— 切换 item 时让浏览器重新发请求,而不是复用缓存。
  const frameKey = `${host}:${item.url}`;

  useEffect(() => {
    setLoadState(isBlocked ? "fallback" : "loading");
    setFallbackReason(
      isBlocked ? "该网站禁止被内嵌加载(X-Frame-Options)" : "",
    );
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (!isBlocked) {
      timerRef.current = setTimeout(() => {
        // 5 秒仍未触发 onload → 兜底(目标站可能压根没返回 frame-ancestors
        // 但渲染很慢,或返回了 frame-ancestors 'none' 但浏览器不报错)。
        setLoadState((s) => (s === "loading" ? "fallback" : s));
        setFallbackReason("加载超时(目标网站可能禁止被内嵌)");
      }, 5000);
    }
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [frameKey, isBlocked]);

  const openInNew = () => window.open(item.url, "_blank", "noopener");
  const retryFrame = () => {
    setLoadState("loading");
    setFallbackReason("");
  };

  return (
    <>
      <div className="sd-frame-header">
        <div className="sd-frame-dots">
          <span /><span /><span />
        </div>
        <div className="sd-frame-url" title={item.url}>{item.url}</div>
        <Button
          type="link"
          className="sd-open-btn"
          icon={<GlobalOutlined />}
          onClick={openInNew}
        >
          新窗口打开 ↗
        </Button>
      </div>
      <div className="sd-frame-body">
        {loadState === "fallback" ? (
          <div className="sd-fallback">
            <GlobalOutlined className="sd-fallback-icon" />
            <h4 style={{ margin: 0 }}>无法在内嵌浏览框中显示该网页</h4>
            <p className="sd-fallback-reason">{fallbackReason}</p>
            <div className="sd-fallback-card">
              <div className="sd-fallback-row">
                <span>标题</span><strong>{item.title || "—"}</strong>
              </div>
              <div className="sd-fallback-row">
                <span>网址</span><strong>{item.url}</strong>
              </div>
              <div className="sd-fallback-row">
                <span>类型</span><strong>{item.type}</strong>
              </div>
              <div className="sd-fallback-row">
                <span>引用次数</span><strong>{item.count} 次</strong>
              </div>
            </div>
            <div className="sd-fallback-actions">
              <Button type="primary" icon={<GlobalOutlined />} onClick={openInNew}>
                在新窗口打开 ↗
              </Button>
              <Button icon={<ReloadOutlined />} onClick={retryFrame}>
                仍要内嵌加载
              </Button>
            </div>
          </div>
        ) : (
          <>
            {loadState === "loading" && (
              <div className="sd-loading">
                <div className="sd-spinner" />
                正在加载 {item.url} …
              </div>
            )}
            <iframe
              key={frameKey}
              className="sd-frame"
              src={item.url}
              referrerPolicy="no-referrer"
              title={item.title ?? item.url}
              onLoad={() => {
                if (timerRef.current) clearTimeout(timerRef.current);
                setLoadState((s) => (s === "loading" ? "loaded" : s));
              }}
              onError={() => {
                if (timerRef.current) clearTimeout(timerRef.current);
                setLoadState("fallback");
                setFallbackReason("浏览器拒绝加载(可能被 X-Frame-Options 拦截)");
              }}
            />
          </>
        )}
      </div>
    </>
  );
}
