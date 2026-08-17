/**
 * 引用源分析 tab —— data tab → 引用源分析。
 *
 * 布局严格按 docs/ui-sample/index.html #tab-citation:
 *   - 顶部 secondary tabs(全部引用 / 官方网站 / 新闻网站 / 自媒体)+ 右上 15 天
 *   - 筛选区:模型 / 业务排名 / 关键词 + 应用筛选
 *   - 引用源列表(panel-wide):引用源 / 类型 / 引用次数 / 排名位置 / 首次引用 / 最近引用 / 操作
 *
 * 数据由后端 ``GET /projects/{id}/citation-analysis`` 一次性返回,
 * 全部分类、过滤、排名分桶都在前端按这个 bundle 做;后端只算引用
 * 次数 / 平均排名 / 类型 / 首次最近时间。
 */

import { useEffect, useMemo, useState } from "react";
import { Empty, Select, Skeleton, Tag, message } from "antd";
import { PLATFORM_CATALOG, platformLabel } from "./platforms";
import {
  getCitationAnalysis,
  type CitationAnalysisOut,
  type CitationOut,
} from "../../api/projects";

interface Props {
  projectId: number;
}

type TypeTab = "全部" | "官方网站" | "新闻媒体" | "自媒体";
type RankBucket = "全部" | "Top1" | "Top1-3" | "Top3-10" | "Top10+";
type Days = 7 | 15 | 30;
type DrBucket = "全部" | "高(DR>80)" | "中(DR 40-80)" | "低(DR<40)";

// Tab labels match the ui-sample navigation (which says "新闻媒体" on the
// tab strip) but the data ``type`` field from the backend classifier uses
// "新闻网站". This map keeps the two decoupled.
const TYPE_TABS: TypeTab[] = ["全部", "官方网站", "新闻媒体", "自媒体"];
const TYPE_FILTER: Record<TypeTab, string | null> = {
  全部: null,
  官方网站: "官方网站",
  新闻媒体: "新闻网站",
  自媒体: "自媒体",
};

const RANK_BUCKETS: RankBucket[] = ["全部", "Top1", "Top1-3", "Top3-10", "Top10+"];

const DR_BUCKETS: DrBucket[] = ["全部", "高(DR>80)", "中(DR 40-80)", "低(DR<40)"];

const DAY_OPTIONS: { value: Days; label: string }[] = [
  { value: 7, label: "7 天" },
  { value: 15, label: "15 天" },
  { value: 30, label: "30 天" },
];

// Maps the classifier bucket to the color tag used by the ui-sample
// mock. Keys match the type buckets returned by the backend; "其他"
// falls through to a neutral gray.
const TYPE_TAG_CLASS: Record<string, string> = {
  官方网站: "blue",
  新闻网站: "green",
  社交媒体: "purple",
  百科: "cyan",
  海外网站: "red",
  垂类论坛: "gold",
  自媒体: "orange",
  其他: "default",
};

const RANK_TAG_CLASS: Record<RankBucket, string> = {
  全部: "default",
  Top1: "blue",
  "Top1-3": "blue",
  "Top3-10": "default",
  "Top10+": "default",
};

function bucketOf(avg_rank: number | null): RankBucket {
  if (avg_rank === null) return "Top10+";
  if (avg_rank < 1) return "Top1";
  if (avg_rank < 3) return "Top1-3";
  if (avg_rank < 10) return "Top3-10";
  return "Top10+";
}

function platformName(key: string): string {
  return platformLabel(key);
}

export default function CitationAnalysisTab({ projectId }: Props) {
  const [data, setData] = useState<CitationAnalysisOut | null>(null);
  const [loading, setLoading] = useState(true);

  const [typeTab, setTypeTab] = useState<TypeTab>("全部");
  const [platform, setPlatform] = useState<string | undefined>(undefined);
  const [rank, setRank] = useState<RankBucket>("全部");
  const [dr, setDr] = useState<DrBucket>("全部");
  const [keyword, setKeyword] = useState("");
  const [days, setDays] = useState<Days>(15);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getCitationAnalysis(projectId, { days })
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        message.error(err.message || "引用源数据加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, days]);

  // Available platforms = the union of every platform that cited at
  // least one URL in the window. Drives the 全部模型 dropdown.
  const availablePlatforms = useMemo(() => {
    if (!data) return [];
    const set = new Set<string>();
    for (const it of data.items) for (const p of it.platforms) set.add(p);
    // Stable order: follow PLATFORM_CATALOG so the dropdown matches the
    // rest of the app's platform ordering.
    const ordered = PLATFORM_CATALOG.map((c) => c.key).filter((k) => set.has(k));
    for (const k of set) if (!ordered.includes(k)) ordered.push(k);
    return ordered;
  }, [data]);

  // Active filters applied client-side. The "应用筛选" button is a
  // visual marker for the ui-sample pattern — we just keep the
  // filters live-bound so the table updates as the user picks.
  const filtered = useMemo(() => {
    if (!data) return [] as CitationOut[];
    const kw = keyword.trim().toLowerCase();
    const typeMatch = TYPE_FILTER[typeTab];
    return data.items.filter((it) => {
      if (typeMatch !== null && it.type !== typeMatch) return false;
      if (platform && !it.platforms.includes(platform)) return false;
      if (rank !== "全部" && bucketOf(it.avg_rank) !== rank) return false;
      // DR bucket is a placeholder — we don't yet have a DR field on
      // the citation row, so picking anything but "全部" just shows no
      // rows. Keeps the control honest about what the data supports.
      if (dr !== "全部") return false;
      if (kw) {
        const hay = `${it.url} ${it.title ?? ""} ${it.site}`.toLowerCase();
        if (!hay.includes(kw)) return false;
      }
      return true;
    });
  }, [data, typeTab, platform, rank, dr, keyword]);

  if (loading) {
    return <Skeleton active paragraph={{ rows: 12 }} />;
  }
  if (!data) {
    return <Empty description="暂无可展示的引用源数据" />;
  }

  const hasData = data.total_citations > 0;

  return (
    <div className="cta-root">
      {/* secondary tabs + 时间区间(右上角,跟图片一致) */}
      <div className="qt-secondary-tabs">
        <div className="qt-secondary-tabs-left">
          {TYPE_TABS.map((t) => (
            <button
              key={t}
              type="button"
              className={`qt-subtab${typeTab === t ? " active" : ""}`}
              onClick={() => setTypeTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
        <div className="qt-secondary-tabs-right">
          <div className="qt-time-selector">
            {DAY_OPTIONS.map((d) => (
              <button
                key={d.value}
                type="button"
                className={`qt-time-btn${days === d.value ? " active" : ""}`}
                onClick={() => setDays(d.value)}
              >
                {d.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* 筛选区 */}
      <div className="cta-filter-bar">
        <div className="cta-filter-group">
          <label>模型</label>
          <Select
            allowClear
            placeholder="全部模型"
            style={{ width: 160 }}
            value={platform}
            onChange={(v) => setPlatform(v)}
            options={availablePlatforms.map((p) => ({
              value: p,
              label: platformName(p),
            }))}
          />
        </div>
        <div className="cta-filter-group">
          <label>业务排名</label>
          <Select
            value={rank}
            style={{ width: 140 }}
            onChange={(v) => setRank(v as RankBucket)}
            options={RANK_BUCKETS.map((r) => ({ value: r, label: r }))}
          />
        </div>
        <div className="cta-filter-group">
          <label>域名权重</label>
          <Select
            value={dr}
            style={{ width: 140 }}
            onChange={(v) => setDr(v as DrBucket)}
            options={DR_BUCKETS.map((r) => ({ value: r, label: r }))}
          />
        </div>
        <div className="cta-filter-group">
          <label>关键词</label>
          <input
            type="text"
            className="cta-search-input"
            placeholder="搜索 URL / 标题"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
        </div>
        <button
          type="button"
          className="btn-primary"
          onClick={() => {
            // Filters are already live; the button is a visual cue that
            // reflects the ui-sample. Re-render by clearing a hint.
            message.success("筛选已应用");
          }}
        >
          应用筛选
        </button>
      </div>

      {/* 引用源列表 */}
      <div className="panel panel-wide">
        <div className="panel-header">
          <div>
            <h3>引用源列表</h3>
            <p>
              按引用次数倒序 · 共 {filtered.length} / {data.unique_urls} 个
            </p>
          </div>
        </div>
        <div className="panel-body" style={{ padding: 0 }}>
          {filtered.length === 0 ? (
            <Empty
              description={hasData ? "当前筛选下没有引用源" : "窗口内尚无引用源数据"}
              style={{ padding: 32 }}
            />
          ) : (
            <table className="data-table data-table-hover">
              <thead>
                <tr>
                  <th>引用源</th>
                  <th>类型</th>
                  <th>引用次数</th>
                  <th>排名位置</th>
                  <th>近期引用</th>
                  <th>涉及模型</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((row) => {
                  const bucket = bucketOf(row.avg_rank);
                  return (
                    <tr key={row.url}>
                      <td>
                        <div style={{ maxWidth: 360 }}>
                          <strong
                            style={{
                              fontSize: 13,
                              display: "block",
                              marginBottom: 2,
                              color: "var(--text-primary)",
                            }}
                          >
                            {row.title || row.site || row.url}
                          </strong>
                          <span
                            style={{
                              fontSize: 12,
                              color: "var(--text-tertiary)",
                              wordBreak: "break-all",
                            }}
                          >
                            {row.url}
                          </span>
                        </div>
                      </td>
                      <td>
                        <Tag
                          color={TYPE_TAG_CLASS[row.type] ?? "default"}
                          style={{ margin: 0 }}
                        >
                          {row.type}
                        </Tag>
                      </td>
                      <td>
                        <strong>{row.count}</strong>
                      </td>
                      <td>
                        <Tag
                          color={RANK_TAG_CLASS[bucket]}
                          style={{ margin: 0 }}
                        >
                          {bucket}
                        </Tag>
                      </td>
                      <td>
                        <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
                          {row.last_seen.slice(0, 10)}
                        </span>
                      </td>
                      <td>
                        <div
                          style={{
                            display: "flex",
                            flexWrap: "wrap",
                            gap: 4,
                            maxWidth: 220,
                          }}
                        >
                          {row.platforms.slice(0, 4).map((p) => (
                            <Tag
                              key={p}
                              style={{
                                margin: 0,
                                fontSize: 11,
                                background: "var(--bg-page)",
                                color: "var(--text-secondary)",
                                border: "1px solid var(--border-light)",
                              }}
                            >
                              {platformName(p)}
                            </Tag>
                          ))}
                          {row.platforms.length > 4 && (
                            <span
                              style={{
                                fontSize: 11,
                                color: "var(--text-tertiary)",
                                alignSelf: "center",
                              }}
                            >
                              +{row.platforms.length - 4}
                            </span>
                          )}
                        </div>
                      </td>
                      <td>
                        <button
                          type="button"
                          className="btn-text"
                          onClick={() => window.open(row.url, "_blank", "noopener")}
                        >
                          详情
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <style>{`
        .cta-root {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .qt-secondary-tabs {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: #fff;
          padding: 0 24px;
          border-radius: 8px 8px 0 0;
          border: 1px solid var(--border-light, #f0f0f0);
          border-bottom: 0;
          flex-shrink: 0;
        }
        .qt-secondary-tabs-left {
          display: flex;
          gap: 4px;
          flex-wrap: wrap;
        }
        .qt-secondary-tabs-right {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .qt-subtab {
          background: transparent;
          border: 0;
          padding: 12px 16px;
          font-size: 14px;
          color: var(--text-secondary, #4f4f4f);
          cursor: pointer;
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;
          font-family: inherit;
          white-space: nowrap;
        }
        .qt-subtab:hover { color: var(--brand-blue, #1a55e8); }
        .qt-subtab.active {
          color: var(--brand-blue, #1a55e8);
          border-bottom-color: var(--brand-blue, #1a55e8);
          font-weight: 500;
        }

        .qt-time-selector {
          display: inline-flex;
          background: var(--bg-page, #f5f6f8);
          border-radius: 6px;
          padding: 2px;
          gap: 2px;
        }
        .qt-time-btn {
          background: transparent;
          border: 0;
          padding: 4px 12px;
          font-size: 13px;
          color: var(--text-secondary, #4f4f4f);
          cursor: pointer;
          border-radius: 4px;
          font-family: inherit;
        }
        .qt-time-btn:hover { color: var(--brand-blue, #1a55e8); }
        .qt-time-btn.active {
          background: #fff;
          color: var(--brand-blue, #1a55e8);
          font-weight: 500;
          box-shadow: 0 1px 2px rgba(0, 0, 0, 0.06);
        }

        .cta-filter-bar {
          display: flex;
          align-items: flex-end;
          gap: 16px;
          padding: 14px 18px;
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          flex-wrap: wrap;
        }
        .cta-filter-group {
          display: flex;
          flex-direction: column;
          gap: 4px;
        }
        .cta-filter-group label {
          font-size: 12px;
          color: var(--text-tertiary);
        }
        .cta-search-input {
          height: 32px;
          width: 220px;
          padding: 0 12px;
          border: 1px solid var(--border-default, #e7e7e7);
          border-radius: 6px;
          font-size: 13px;
          color: var(--text-primary);
          background: #fff;
          outline: none;
          transition: border-color 0.12s ease;
        }
        .cta-search-input:focus {
          border-color: var(--brand-blue, #1a55e8);
        }
        .btn-primary {
          height: 32px;
          padding: 0 14px;
          border: 0;
          background: var(--brand-blue, #1a55e8);
          color: #fff;
          border-radius: 6px;
          font-size: 13px;
          cursor: pointer;
        }
        .btn-primary:hover {
          background: var(--brand-blue-dark, #1240b8);
        }
        .btn-text {
          background: transparent;
          border: 0;
          color: var(--brand-blue, #1a55e8);
          font-size: 13px;
          cursor: pointer;
          padding: 0;
        }
        .btn-text:hover {
          color: var(--brand-blue-dark, #1240b8);
        }

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
        .data-table tbody td {
          padding: 10px 12px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          vertical-align: middle;
        }
        .data-table-hover tbody tr:hover { background: var(--bg-hover, #fafafa); }
      `}</style>
    </div>
  );
}
