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
