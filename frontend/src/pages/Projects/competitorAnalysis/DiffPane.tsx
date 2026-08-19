import { Empty } from "antd";
import type { CompetitorAnalysisOut } from "../../../api/projects";

export default function DiffPane({ data }: { data: CompetitorAnalysisOut }) {
  void data; // 占位,Task 16 填充
  return (
    <div className="diff-grid">
      <div className="panel"><div className="panel-header"><h3>核心指标对比</h3></div>
        <div className="panel-body"><Empty description="占位 — Task 16 填充" style={{ padding: 32 }} /></div></div>
      <div className="panel"><div className="panel-header"><h3>模型维度提及率</h3></div>
        <div className="panel-body"><Empty description="占位 — Task 16 填充" style={{ padding: 32 }} /></div></div>
      <div className="panel panel-wide"><div className="panel-header"><h3>模型竞争四象限</h3></div>
        <div className="panel-body"><Empty description="占位 — Task 16 填充" style={{ padding: 32 }} /></div></div>
    </div>
  );
}
