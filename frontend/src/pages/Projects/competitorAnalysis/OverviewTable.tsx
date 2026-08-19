import type { CompetitorKpi } from "../../../api/projects";

export default function OverviewTable({ rows }: { rows: CompetitorKpi[] }) {
  return (
    <div className="panel panel-wide">
      <div className="panel-header"><h3>竞品概览</h3></div>
      <div className="panel-body" style={{ padding: 0 }}>
        <table className="data-table data-table-hover">
          <thead><tr><th>品牌</th><th>待填</th></tr></thead>
          <tbody>{rows.map((r) => <tr key={r.brand_canonical}><td>{r.name}</td><td>—</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}
