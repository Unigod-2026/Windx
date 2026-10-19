/**
 * 「自由文章提及状况」tab —— per-prompt × per-period own-article 命中矩阵。
 *
 * 视觉参照 docs/信源分析.docx → image1(精简版,不含 image2 的
 * 引用总次数 / 模式分布 / 被引站点明细等列)。
 *
 * 矩阵列:问题 | per-platform 本期状态(6 个模型列,顺序跟着后端的
 * ``platform_columns``) | 本期提及 | 上期提及 | 基期提及 |
 * Δ较上期(%) | Δ较基期(%) | 自有文章引用(N次 + 命中模型)。
 *
 * 顶栏 3 个 DateRangePicker:本期 / 上期 / 基期,各自可调。
 * 默认值(image1 + 用户确认):
 *   本期  = 本周一 → 今天(Asia/Shanghai)
 *   上期  = 上周一 → 上周日
 *   基期  = 上上周一 → 上上周日
 *
 * cell 渲染:
 *   ✓  提及     (绿色,本期命中 own-article)
 *   —  未提及   (灰色)
 *   ↑  较基期新增  (绿箭头)
 *   ↓  较基期丢失  (红箭头)
 * 三种指示符(mentioned / trend_up / trend_down)正交组合：
 *   "✓" / "✓↑" / "—↓" / "—"
 */

import { useCallback, useEffect, useState } from "react";
import { Button, DatePicker, Empty, Skeleton, Spin, message } from "antd";
import {
  CaretDownOutlined,
  CaretUpOutlined,
  CheckOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import isoWeek from "dayjs/plugin/isoWeek";
import {
  getOwnArticlesByPrompt,
  type PromptMentionRow as PromptRow,
  type PromptMentionStatsOut,
} from "../../../../api/projects";
import { platformColor, platformLabel } from "../../platforms";

interface Props {
  projectId: number;
}

/** dayjs 启用 isoWeek 插件,startOf('isoWeek') 即周一。*/
dayjs.extend(isoWeek);

/** 周区间 [Mon, Sun] helper。 */
function weekRange(anchor: Dayjs, offset = 0): [Dayjs, Dayjs] {
  const monday = anchor.startOf("isoWeek");
  const start = monday.subtract(7 * offset, "day");
  const end = start.add(6, "day");
  return [start, end];
}

function defaultPeriods(now: Dayjs = dayjs()) {
  return {
    current: weekRange(now, 0),  // 本周: Mon..Sun
    previous: weekRange(now, 1), // 上周
    baseline: weekRange(now, 2), // 上上周
  };
}

interface PeriodPickerProps {
  label: string;
  value: [Dayjs, Dayjs];
  onChange: (next: [Dayjs, Dayjs]) => void;
  accent: "current" | "previous" | "baseline";
}

const ACCENT_COLOR: Record<PeriodPickerProps["accent"], string> = {
  current: "var(--brand-blue, #1a55e8)",
  previous: "#7c3aed",
  baseline: "#9ca3af",
};

function PeriodPicker({ label, value, onChange, accent }: PeriodPickerProps) {
  const color = ACCENT_COLOR[accent];
  return (
    <div
      className="pm-period-picker"
      style={{
        borderLeft: `3px solid ${color}`,
      }}
    >
      <span className="pm-period-label" style={{ color }}>{label}</span>
      <DatePicker.RangePicker
        size="small"
        value={value}
        onChange={(v) => {
          if (v && v[0] && v[1]) onChange([v[0], v[1]]);
        }}
        format="YYYY-MM-DD"
        allowClear={false}
      />
    </div>
  );
}

/** cell 复合渲染:✓/— 基础上叠加 ↑/↓ trend。
 *  视觉规范 (与 image1 一致):
 *   cited=True,  trend_up=True   → ✓↑
 *   cited=True,  trend_down=False → ✓
 *   cited=False, trend_down=True  → —↓
 *   cited=False, both False       → — */
function MentionCell({ row }: { row: PromptRow["platform_cells"][string] }) {
  if (!row.cited) {
    return (
      <span style={{ color: "var(--text-tertiary)", fontFamily: "monospace" }}>
        —{row.trend_down && (
          <CaretDownOutlined style={{ color: "#dc2626", marginLeft: 1, fontSize: 10 }} />
        )}
      </span>
    );
  }
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 2 }}>
      <CheckOutlined style={{ color: "#16a34a", fontWeight: 700 }} />
      {row.trend_up && <CaretUpOutlined style={{ color: "#16a34a", fontSize: 10 }} />}
    </span>
  );
}

interface CountCellProps {
  value: number;
  total: number;
  highlight?: boolean;
}
/** 本期/上期/基期 提及:N/6 形式;value=0 时显示红色「未提及」。*/
function CountCell({ value, total, highlight }: CountCellProps) {
  if (value === 0) {
    return (
      <span
        style={{
          color: "#dc2626",
          background: "#fef2f2",
          padding: "2px 8px",
          borderRadius: 999,
          fontSize: 11,
          fontWeight: 600,
        }}
      >
        未提及
      </span>
    );
  }
  return (
    <span
      style={{
        fontVariantNumeric: "tabular-nums",
        fontWeight: highlight ? 700 : 500,
        color: highlight ? "var(--brand-blue, #1a55e8)" : "var(--text-primary)",
      }}
    >
      {value}
      <span style={{ color: "var(--text-tertiary)", fontWeight: 400, fontSize: 11 }}>
        /{total}
      </span>
    </span>
  );
}

/** 平台列头:把 ``platformLabel`` 的「豆包 网页版」/「千问-网页-快速」拆成
 *  两行,模型名在上、变体在下(对齐 image1 列头窄宽度下的折行观感)。 */
function PlatformLabelMultiLine({ code }: { code: string }) {
  const label = platformLabel(code);
  const parts = label.includes("-")
    ? label.split("-").filter(Boolean)
    : label.split(" ").filter(Boolean);
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        lineHeight: 1.25,
        color: platformColor(code),
      }}
    >
      {parts.map((p, i) => (
        <div key={i}>{p}</div>
      ))}
    </div>
  );
}

function DeltaCell({ pct }: { pct: number }) {
  const isPos = pct > 0;
  const isNeg = pct < 0;
  const color = isPos ? "#16a34a" : isNeg ? "#dc2626" : "var(--text-tertiary)";
  const sign = isPos ? "+" : "";
  return (
    <span
      style={{
        fontVariantNumeric: "tabular-nums",
        fontWeight: 600,
        color,
      }}
    >
      {isPos && <CaretUpOutlined style={{ color, fontSize: 10, marginRight: 1 }} />}
      {isNeg && <CaretDownOutlined style={{ color, fontSize: 10, marginRight: 1 }} />}
      {sign}
      {pct.toFixed(2)}
      <span style={{ color: "var(--text-tertiary)", fontWeight: 400, fontSize: 11 }}>
        %
      </span>
    </span>
  );
}

interface PromptMatrixInnerProps {
  stats: PromptMentionStatsOut;
  platformColumns: string[];
  totalPlatforms: number;
}

function PromptMatrixInner({ stats, platformColumns, totalPlatforms }: PromptMatrixInnerProps) {
  if (stats.rows.length === 0) {
    return <Empty description="本项目暂无问题数据" style={{ padding: 48 }} />;
  }

  return (
    <div className="pm-matrix-wrap">
      <table className="pm-matrix">
        <colgroup>
          {/* colgroup 让 table-layout:fixed 知道每列精确宽度 ——
            super-header 的 colSpan 才会真正横跨 platform_columns.length 列。
            「自有文章引用」列已移除(冗余)。 */}
          <col style={{ width: "280px" }} />
          {platformColumns.map((code) => (
            <col key={code} style={{ width: "60px" }} />
          ))}
          <col style={{ width: "74px" }} />
          <col style={{ width: "74px" }} />
          <col style={{ width: "74px" }} />
          <col style={{ width: "90px" }} />
          <col style={{ width: "90px" }} />
        </colgroup>
        <thead>
          <tr>
            <th rowSpan={2} className="pm-th-prompt">问题</th>
            <th
              colSpan={platformColumns.length}
              className="pm-th-period-header"
            >
              本期模型提及状态
            </th>
            <th rowSpan={2} className="pm-th-num">本期<br />提及</th>
            <th rowSpan={2} className="pm-th-num">上期<br />提及</th>
            <th rowSpan={2} className="pm-th-num">基期<br />提及</th>
            <th rowSpan={2} className="pm-th-num">对比<br />上期</th>
            <th rowSpan={2} className="pm-th-num">对比<br />基期</th>
          </tr>
          <tr>
            {platformColumns.map((code) => (
              <th key={code} className="pm-th-platform">
                <PlatformLabelMultiLine code={code} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {stats.rows.map((row) => (
            <tr key={row.prompt_id}>
              <td className="pm-td-prompt">
                <div className="pm-prompt-main">
                  {row.prompt}{row.category && (
                    <span className="pm-prompt-cat">{row.category}</span>
                  )}
                </div>
              </td>
              {platformColumns.map((code) => {
                const cell = row.platform_cells[code] ?? {
                  cited: false, trend_up: false, trend_down: false,
                };
                return (
                  <td key={code} className="pm-td-platform">
                    <MentionCell row={cell} />
                  </td>
                );
              })}
              <td className="pm-td-num">
                <CountCell value={row.cur_count} total={totalPlatforms} highlight />
              </td>
              <td className="pm-td-num">
                <CountCell value={row.prev_count} total={totalPlatforms} />
              </td>
              <td className="pm-td-num">
                <CountCell value={row.base_count} total={totalPlatforms} />
              </td>
              <td className="pm-td-num">
                <DeltaCell pct={row.delta_prev_pct} />
              </td>
              <td className="pm-td-num">
                <DeltaCell pct={row.delta_base_pct} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function PromptMatrix({ projectId }: Props) {
  const [periodCurrent, setPeriodCurrent] = useState<[Dayjs, Dayjs]>(() =>
    defaultPeriods().current,
  );
  const [periodPrevious, setPeriodPrevious] = useState<[Dayjs, Dayjs]>(() =>
    defaultPeriods().previous,
  );
  const [periodBaseline, setPeriodBaseline] = useState<[Dayjs, Dayjs]>(() =>
    defaultPeriods().baseline,
  );
  const [data, setData] = useState<PromptMentionStatsOut | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const d = await getOwnArticlesByPrompt(projectId, {
        start_a: periodCurrent[0].format("YYYY-MM-DD"),
        end_a: periodCurrent[1].format("YYYY-MM-DD"),
        start_b: periodPrevious[0].format("YYYY-MM-DD"),
        end_b: periodPrevious[1].format("YYYY-MM-DD"),
        start_c: periodBaseline[0].format("YYYY-MM-DD"),
        end_c: periodBaseline[1].format("YYYY-MM-DD"),
      });
      setData(d);
    } catch (err) {
      message.error((err as Error).message || "矩阵加载失败");
    } finally {
      setLoading(false);
    }
  }, [
    projectId,
    periodCurrent, periodPrevious, periodBaseline,
  ]);

  // 只在 projectId 变更或首次挂载时自动 reload;
  // pickers 改 state 不自动 reload,等用户按「查询」明确触发 ——
  // 否则 picker onChange 自动 reload 时,点「查询」得到相同结果看不出反应。
  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // 平台列顺序 = 后端 platform_columns(项目 sort 顺序)。
  // totalPlatforms 必须用 platform_columns.length,不用固定的 6 —— 项目可能配 2-8 个平台。
  const platformColumns = data?.platform_columns ?? [];
  const totalPlatforms = platformColumns.length || 6;  // 0 时 fallback 6,等后端返回


  return (
    <div className="pm-root">
      <div className="panel">
        <div className="pm-period-bar">
          <PeriodPicker
            label="本期"
            value={periodCurrent}
            onChange={setPeriodCurrent}
            accent="current"
          />
          <PeriodPicker
            label="上期"
            value={periodPrevious}
            onChange={setPeriodPrevious}
            accent="previous"
          />
          <PeriodPicker
            label="基期"
            value={periodBaseline}
            onChange={setPeriodBaseline}
            accent="baseline"
          />
          <div className="pm-period-bar-action">
            <Button
              type="primary"
              icon={<ReloadOutlined />}
              onClick={reload}
              loading={loading}
            >
              查询
            </Button>
          </div>
        </div>
        <div className="panel-body">
          <Spin spinning={loading} tip="查询中…" wrapperClassName="pm-spin">
            {loading && !data ? (
              <Skeleton active paragraph={{ rows: 8 }} />
            ) : data ? (
              <PromptMatrixInner
                stats={data}
                platformColumns={platformColumns}
                totalPlatforms={totalPlatforms}
              />
            ) : null}
          </Spin>
        </div>
      </div>

      <style>{`
        .pm-root { padding: 12px 0; }
        .pm-period-bar {
          display: flex;
          gap: 16px;
          padding: 12px 18px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          background: #fafbfc;
          flex-wrap: wrap;
          align-items: flex-end;
        }
        .pm-period-bar-action {
          margin-left: auto;
          padding-bottom: 4px;
        }
        .pm-period-picker {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 4px 12px 4px 10px;
          background: #fff;
          border-radius: 6px;
          border: 1px solid var(--border-light, #f0f0f0);
          white-space: nowrap;
        }
        .pm-period-label {
          font-size: 12px;
          font-weight: 600;
          letter-spacing: 0.5px;
        }
        .panel {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          display: flex;
          flex-direction: column;
        }
        .panel-header {
          padding: 10px 18px 8px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
        }
        .panel-header h3 {
          margin: 0;
          font-size: 14px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .panel-header p {
          margin: 4px 0 0;
          font-size: 12px;
          color: var(--text-tertiary);
        }
        .panel-body { padding: 16px 18px; }

        .pm-matrix-wrap {
          overflow-x: auto;
          overflow-y: auto;
          /* 让横向 + 纵向滚动条都只出现在表格区,不出现在 panel-body / 外层上 */
          max-width: 100%;
          max-height: calc(100vh - 360px);
        }
        /* 表头 sticky —— 垂直滚动时表头始终贴顶可见。z-index 拉高,
           跟 sticky 的「问题」列(z=1)叠加时,表头比首列优先。 */
        /* 表头两行都 sticky;super-header 高度 36px,per-platform 行贴着
   super-header 下方(top: 36px)。
   ⚠️ 不在通用规则设 z-index — .pm-matrix thead tr:first-child th
   specificity 0,2,3 压住任何 .pm-matrix thead th.X 覆盖 (0,2,2)。
   z-index 挪到具体 cell 规则里设。 */
        .pm-matrix thead tr:first-child th {
          position: sticky;
          top: 0;
        }
        .pm-matrix thead tr:nth-child(2) th {
          position: sticky;
          top: 36px;
          z-index: 2;
        }
        /* super-header 行 sticky 在最上, z=3 */
        .pm-matrix th.pm-th-period-header {
          z-index: 3;
        }
        /* 「问题」列双向 fixed 提升 z 让它盖过 super-header(水平滚到右时不被
           super-header 蓝色块压在下面) */
        .pm-matrix th.pm-th-prompt {
          position: sticky;
          top: 0;
          left: 0;
          z-index: 4;
        }
        .pm-matrix {
          width: 100%;
          table-layout: fixed;
          border-collapse: collapse;
          font-size: 13px;
        }
        .pm-matrix th, .pm-matrix td {
          padding: 10px 12px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          border-right: 1px solid var(--border-light, #f0f0f0);
          text-align: left;
          vertical-align: middle;
          overflow-wrap: break-word;
        }
        .pm-matrix th:last-child, .pm-matrix td:last-child {
          border-right: 0;
        }
        .pm-matrix thead th {
          background: #f5f7fa;
          font-size: 12px;
          font-weight: 600;
          color: var(--text-secondary, #4f4f4f);
          white-space: nowrap;
        }
        .pm-th-prompt {
          position: sticky;
          left: 0;
          background: #f5f7fa;
          z-index: 1;
        }
        .pm-td-prompt {
          position: sticky;
          left: 0;
          background: #fff;
          z-index: 1;
          box-shadow: 1px 0 0 var(--border-light, #f0f0f0);
        }
        .pm-matrix th.pm-th-period-header {
          text-align: center;
          vertical-align: middle;
          /* height 固定 36px —— per-platform 行的 sticky top:36px 对齐蓝线下沿 */
          height: 36px;
          padding: 0 12px;
          line-height: 36px;
          background: #dbeafe;
          color: var(--brand-blue, #1a55e8);
          font-weight: 700;
          font-size: 13px;
          letter-spacing: 2px;
          border-bottom: 1px solid var(--brand-blue, #1a55e8);
          white-space: nowrap;
        }
        .pm-th-platform, .pm-td-platform {
          text-align: center;
          font-size: 12px;
        }
        .pm-th-num, .pm-td-num {
          text-align: center;
        }
        .pm-td-num, .pm-td-platform {
          font-variant-numeric: tabular-nums;
        }
        .pm-matrix tbody tr:hover .pm-td-prompt {
          background: #f0f7ff;
        }
        .pm-prompt-main {
          color: var(--text-primary);
          line-height: 1.5;
        }
        .pm-prompt-cat {
          display: inline-block;
          margin-left: 4px;
          padding: 1px 6px;
          font-size: 10px;
          color: var(--text-tertiary);
          background: #f3f4f6;
          border-radius: 3px;
          vertical-align: 1px;
          white-space: nowrap;
        }
      `}</style>
    </div>
  );
}
