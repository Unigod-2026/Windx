/**
 * 「信源偏好媒体」sub-tab —— 完成态。
 *
 * 视觉参照 docs/信源分析.docx → image3(去掉 4 个分析列:覆盖模型 /
 * 稳定性 / 近期趋势 / 备注 —— 用户不想要这 4 列,见需求澄清)。
 *
 * 列(从 image3 保留的 13 列):
 *   合作(S) | 媒体名称 | 总引用次数 | 出现期数 | 期数覆盖率 |
 *   最长连续期数 | 首现期 | 文心 | DeepSeek | 豆包 | Kimi |
 *   通义千问 | 元宝
 *
 * 数据来源:``GET /projects/{id}/source-media`` —— 后端按
 * ``geo_media_dictionary.media_name`` 聚合,跨期统计 + per-model counts。
 * 不复用 ``source-preferences`` 的 ``top_sources``,因为那条路按 URL 聚合
 * 而非 media_name。
 *
 * 「期」口径:一次 schedule run = 1 期(SUCCESS 状态才计入 period_total),
 * 不是 ISO 周。窗口由 GlobalToolbar 控制。
 *
 * per-model counts 列根据项目配置的 platform 列表动态渲染(跟 PromptMatrix
 * 的 platformColumns 策略一致)—— 默认按 WIZARD_MODELS 顺序兜底。
 */

import { useEffect, useMemo, useState } from "react";
import { Empty, Skeleton, Tag, Tooltip, message } from "antd";
import {
  getProject,
  getSourceMedia,
  type ProjectPlatform,
  type SourceMediaOut,
} from "../../../api/projects";
import {
  platformColor,
  platformLabel,
  rowKeyOfPlatform,
} from "../platforms";
import { useToolbarFilter } from "../../../components/ToolbarFilterContext";

interface Props {
  projectId: number;
}

/** image3 默认 6 个 per-model counts 列顺序,跟用户视角的"豆包/Kimi/..."对齐。
 *  项目实际配置不同时,按平台 dropdown 的 compound key 顺序覆盖。 */
const DEFAULT_PLATFORM_COLUMNS = [
  "baiduai__web__fast",
  "deepseek__web__fast",
  "doubao__web__fast",
  "kimi__web__fast",
  "qianwen__web__fast",
  "yuanbao__web__fast",
];

function PlatformCountCell({
  code,
  count,
}: {
  code: string;
  count: number | undefined;
}) {
  const label = platformLabel(code);
  if (count === undefined || count === 0) {
    return (
      <span style={{ color: "var(--text-tertiary)", fontFamily: "monospace" }}>
        —
      </span>
    );
  }
  return (
    <Tooltip title={label} mouseEnterDelay={0.2}>
      <span
        style={{
          fontVariantNumeric: "tabular-nums",
          fontWeight: 600,
          color: platformColor(code),
        }}
      >
        {count}
      </span>
    </Tooltip>
  );
}

/** 「期数覆盖率」百分比 cell —— 用浅蓝/浅绿二档区分 100% vs 部分。 */
function CoverageCell({ pct }: { pct: number }) {
  const percent = (pct * 100).toFixed(1);
  const isFull = pct >= 0.999;
  return (
    <span
      style={{
        fontVariantNumeric: "tabular-nums",
        fontWeight: 600,
        color: isFull ? "#16a34a" : "var(--text-primary)",
        background: isFull ? "#f0fdf4" : "transparent",
        padding: isFull ? "1px 6px" : 0,
        borderRadius: isFull ? 4 : 0,
      }}
    >
      {percent}%
    </span>
  );
}

export default function SourceMedia({ projectId }: Props) {
  const [out, setOut] = useState<SourceMediaOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [projectPlatforms, setProjectPlatforms] = useState<
    ProjectPlatform[] | null
  >(null);
  const toolbar = useToolbarFilter();

  useEffect(() => {
    let cancelled = false;
    getProject(projectId)
      .then((d) => {
        if (!cancelled) setProjectPlatforms(d.platforms);
      })
      .catch(() => {
        if (!cancelled) setProjectPlatforms([]);
      });
    return () => {
      cancelled = true;
    };
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
    () =>
      toolbar.selectedPromptIds
        ? [...toolbar.selectedPromptIds].sort().join("|")
        : "all",
    [toolbar.selectedPromptIds],
  );

  useEffect(() => {
    if (effectiveModels === undefined) return;
    let cancelled = false;
    setLoading(true);
    getSourceMedia(projectId, {
      days: dateQuery.days,
      start: dateQuery.start,
      end: dateQuery.end,
      models: effectiveModels,
      prompts: toolbar.selectedPromptIds ?? undefined,
    })
      .then((d) => {
        if (!cancelled) setOut(d);
      })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "信源偏好媒体加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, toolbar.version, effectiveModels, dateKey, promptsKey]);

  // per-model counts 列顺序:
  // 1. 用户 toolbar 选了 N 个 → 用那 N 个
  // 2. 项目 platform 配置加载完 → 用 rowKeyOfPlatform 结果
  // 3. fallback DEFAULT_PLATFORM_COLUMNS(对齐 image3 默认 6 个)
  const platformColumns = useMemo<string[]>(() => {
    if (toolbar.selectedModels && toolbar.selectedModels.length > 0) {
      return toolbar.selectedModels;
    }
    if (projectPlatforms && projectPlatforms.length > 0) {
      return projectPlatforms.map(rowKeyOfPlatform);
    }
    return DEFAULT_PLATFORM_COLUMNS;
  }, [toolbar.selectedModels, projectPlatforms]);

  // 裁掉 Wizard 没登记的 compound key(以防 dropdown 选了 7 个但只 6 个有数据)。
  // image3 默认 6 列的语义保留:多于 6 个时,渲染全 dropdown 列;少时按现有渲染。
  const items = out?.items ?? [];
  const periodTotal = out?.items?.[0]?.period_total ?? 0;
  const windowStart = out?.start ?? "";
  const windowEnd = out?.end ?? "";

  return (
    <div className="sm-root">
      <div className="panel">
        <div className="panel-header">
          <div>
            {/* <h3>信源偏好媒体</h3> */}
            <p>
              按官方媒体字典聚合 · 窗口 {windowStart} ~ {windowEnd} · 共{" "}
              {periodTotal} 期监控
            </p>
          </div>
        </div>
        <div className="panel-body sm-h-scroll">
          {loading && !out ? (
            <Skeleton active paragraph={{ rows: 6 }} />
          ) : items.length === 0 ? (
            <Empty description="窗口内尚无信源媒体数据" style={{ padding: 32 }} />
          ) : (
            <div className="sm-table-wrap">
              <table className="sm-table">
                <colgroup>
                  <col style={{ width: "50px" }} />
                  <col style={{ width: "240px" }} />
                  <col style={{ width: "100px" }} />
                  <col style={{ width: "90px" }} />
                  <col style={{ width: "120px" }} />
                  <col style={{ width: "110px" }} />
                  <col style={{ width: "120px" }} />
                  {platformColumns.map((code) => (
                    <col key={code} style={{ width: "80px" }} />
                  ))}
                </colgroup>
                <thead>
                  <tr>
                    <th className="sm-th-center" title="合作">
                      合作
                    </th>
                    <th>媒体名称</th>
                    <th className="sm-th-num">总引用<br />次数</th>
                    <th className="sm-th-num">出现<br />期数</th>
                    <th className="sm-th-num">期数<br />覆盖率</th>
                    <th className="sm-th-num">最长连续<br />期数</th>
                    <th className="sm-th-num">首现期</th>
                    {platformColumns.map((code) => {
                      // 多行 platformLabel:拆 "-",保留 「千问/网页/快速」
                      // 视觉跟 PromptMatrix 的 PlatformLabelMultiLine 一致。
                      const parts = platformLabel(code)
                        .split(/[- ]/)
                        .filter(Boolean);
                      const color = platformColor(code);
                      return (
                        <th
                          key={code}
                          className="sm-th-model"
                          style={{ color }}
                        >
                          {parts.map((p, i) => (
                            <div key={i}>{p}</div>
                          ))}
                        </th>
                      );
                    })}
                  </tr>
                </thead>
                <tbody>
                  {items.map((r) => (
                    <tr key={r.media_name}>
                      <td className="sm-td-center sm-td-partner">
                        <Tooltip title="信源偏好媒体条目" mouseEnterDelay={0.3}>
                          <span className="sm-partner-mark">S</span>
                        </Tooltip>
                      </td>
                      <td className="sm-td-name">
                        <div className="sm-name-main" title={r.media_name}>
                          {r.media_name}
                        </div>
                        <a
                          className="sm-name-url"
                          href={r.sample_url}
                          target="_blank"
                          rel="noreferrer"
                          title={r.sample_title ?? r.sample_url}
                        >
                          {r.sample_title || r.sample_url}
                        </a>
                        <div className="sm-name-tags">
                          {r.category ? (
                            <Tag
                              color="blue"
                              className="sm-name-cat"
                              style={{ margin: 0 }}
                            >
                              {r.category}
                            </Tag>
                          ) : (
                            <Tag
                              color="default"
                              className="sm-name-cat"
                              style={{ margin: 0 }}
                            >
                              未收录
                            </Tag>
                          )}
                          <span className="sm-name-count">
                            {" "}
                            {r.platforms.length} 模型
                          </span>
                        </div>
                      </td>
                      <td className="sm-td-num">
                        <strong style={{ color: "var(--brand-blue, #1a55e8)" }}>
                          {r.count}
                        </strong>
                      </td>
                      <td className="sm-td-num">
                        <span style={{ fontVariantNumeric: "tabular-nums" }}>
                          {r.period_count}
                        </span>
                        <span className="sm-td-sub">/{r.period_total}</span>
                      </td>
                      <td className="sm-td-num">
                        <CoverageCell pct={r.period_coverage} />
                      </td>
                      <td className="sm-td-num">
                        <span
                          style={{
                            fontVariantNumeric: "tabular-nums",
                            fontWeight: r.max_consecutive_periods >= r.period_total && r.period_total > 0 ? 700 : 500,
                            color:
                              r.max_consecutive_periods >= r.period_total && r.period_total > 0
                                ? "#16a34a"
                                : "var(--text-primary)",
                          }}
                        >
                          {r.max_consecutive_periods}
                        </span>
                      </td>
                      <td className="sm-td-num">
                        <span style={{ fontVariantNumeric: "tabular-nums", fontSize: 12 }}>
                          {r.first_seen.slice(0, 10)}
                        </span>
                      </td>
                      {platformColumns.map((code) => (
                        <td key={code} className="sm-td-num">
                          <PlatformCountCell
                            code={code}
                            count={r.model_counts[code]}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <style>{`
        .sm-root { padding: 12px 0; }
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
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
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
        /* SourceMedia 专属:把横向滚动挪到 panel-body,sm-table-wrap 只管
           竖向滚动 —— 这样两个滚动条不在同一个容器里,不会互相遮挡;
           横向滚动条固定在 panel 底部可见位置,不再被竖向滚动条推到
           wrap 底部外。 */
        .panel-body.sm-h-scroll {
          overflow-x: auto;
          overflow-y: visible;
          padding-bottom: 0;
        }
        .sm-table-wrap {
          overflow-y: auto;
          max-height: calc(100vh - 280px);
          width: 100%;
          /* 横向溢出交给父级 panel-body;wrap 自身不截,让 table 撑出
             wrap 边界 → 父级 overflow-x: auto 出滚动条。 */
        }
        .sm-table {
          width: 100%;
          min-width: 1500px;
          table-layout: fixed;
          border-collapse: collapse;
          font-size: 13px;
        }
        .sm-table th, .sm-table td {
          padding: 10px 8px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          border-right: 1px solid var(--border-light, #f0f0f0);
          text-align: left;
          vertical-align: middle;
        }
        .sm-table th:last-child, .sm-table td:last-child { border-right: 0; }
        .sm-table thead th {
          background: #f5f7fa;
          font-size: 11px;
          font-weight: 600;
          color: var(--text-secondary, #4f4f4f);
          white-space: nowrap;
          position: sticky;
          top: 0;
          z-index: 1;
          line-height: 1.3;
        }
        .sm-th-center { text-align: center; }
        .sm-th-num {
          text-align: center;
        }
        .sm-th-model {
          text-align: center;
          font-size: 10px;
          font-weight: 600;
          line-height: 1.2;
        }
        .sm-td-center { text-align: center; }
        .sm-td-num {
          text-align: center;
          font-variant-numeric: tabular-nums;
        }
        .sm-td-sub {
          color: var(--text-tertiary);
          font-size: 11px;
          margin-left: 2px;
        }
        .sm-td-name {
          background: #fff;
        }
        .sm-name-main {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .sm-name-url {
          font-size: 11px;
          color: var(--text-tertiary);
          display: block;
          margin-top: 2px;
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
          max-width: 200px;
        }
        .sm-name-tags {
          margin-top: 4px;
          display: flex;
          align-items: center;
          gap: 6px;
          flex-wrap: wrap;
        }
        .sm-name-cat {
          font-size: 10px !important;
          padding: 0 6px !important;
          line-height: 18px !important;
        }
        .sm-name-count {
          font-size: 11px;
          color: var(--text-tertiary);
        }
        .sm-td-partner { padding: 8px 4px !important; }
        .sm-partner-mark {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 22px;
          height: 22px;
          border-radius: 999px;
          background: rgba(26, 85, 232, 0.08);
          color: var(--brand-blue, #1a55e8);
          font-size: 11px;
          font-weight: 700;
          cursor: help;
        }
        .sm-table tbody tr:hover { background: #fafbfc; }
      `}</style>
    </div>
  );
}
