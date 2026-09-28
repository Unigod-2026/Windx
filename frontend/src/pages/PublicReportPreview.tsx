/**
 * 周报统一入口 —— 公开 URL `/public/reports/:token`。
 *
 * 编辑权限由 DB 的 `is_published` 决定,不判断登录态:
 * - `is_published=false` → canEdit=true,显示内联编辑器 + 「发布」按钮,
 *   运营通过 share_token 链接修改本周总结等字段并发布。
 * - `is_published=true` → canEdit=false,所有章节只读,显示「取消发布」按钮。
 *
 * JWT 在 localStorage 时 PATCH / publish / unpublish 调用自然带 token 走
 * [client.ts](../api/client.ts) 的拦截器;无 JWT 时 PATCH 401 被拦截器
 * 重定向到 /login。
 *
 * 章节组件统一从 [ReportSections](./Projects/ReportSections.tsx) 导入。
 */

import { useEffect, useState } from "react";
import { Alert, Button, Skeleton, Space, message } from "antd";
import { useParams } from "react-router-dom";
import {
  getPublicReportSnapshot,
  publishReport,
  updateReport,
  type Report,
  type ReportSnapshotOut,
} from "../api/reports";
import {
  SectionAttribution,
  SectionFiveWeeklyChanges,
  SectionFourContentOps,
  SectionOneOverall,
  SectionThreeBreakdown,
  SectionTwoSummary,
} from "./Projects/ReportSections";
import "./Projects/ReportPreview.css";

export default function PublicReportPreview() {
  const params = useParams<{ token: string }>();
  const token = params?.token ?? "";
  const [data, setData] = useState<ReportSnapshotOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      setError("链接无效");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPublicReportSnapshot(token)
      .then((d) => {
        if (!cancelled) setData(d);
      })
      .catch((err: Error) => {
        if (!cancelled) setError(err.message || "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const [publishing, setPublishing] = useState(false);

  const saveDraft = async (overrides: Record<string, string | null>) => {
    if (!data) return;
    try {
      await updateReport(data.meta.id, overrides);
      message.success("草稿已保存");
      const fresh = await getPublicReportSnapshot(token);
      setData(fresh);
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const publish = async () => {
    if (!data) return;
    setPublishing(true);
    try {
      const updated: Report = await publishReport(data.meta.id);
      message.success("已发布");
      setData((prev) => (prev ? { ...prev, meta: updated } : prev));
    } catch (err) {
      message.error((err as Error).message || "发布失败");
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <div className="report-preview">
        <Skeleton active />
      </div>
    );
  }
  if (error) {
    return (
      <div className="report-preview">
        <Alert type="error" message={error} showIcon />
      </div>
    );
  }
  if (!data) return null;

  const { meta, snapshot } = data;
  const canEdit = !meta.is_published;
  // 页脚口径分母 = 题数 × (平台×终端×模式) 组合数,即 3.2 矩阵的总格子数
  const matrix = snapshot.prompt_platform_matrix ?? [];
  const denominator =
    matrix.length > 0
      ? matrix.length * Object.keys(matrix[0].per_platform).length
      : 0;
  const company = snapshot.project.customer_name;
  const reportYear = meta.period_end.slice(0, 4);

  return (
    <div className="report-preview">
      <div className="report-preview-bar">
        <span /> {/* spacer, no 返回 button — public page is standalone */}
        <Space>
          {canEdit && (
            <Button type="primary" onClick={publish} loading={publishing}>
              发布
            </Button>
          )}
          <Button onClick={() => window.print()}>打印 / PDF</Button>
        </Space>
      </div>

      <article className="report-preview-body">
        <div className="report-preview-topbar">
          <div className="report-preview-topbar-left">
            <div className="report-preview-topbar-brand">风球科技</div>
            <div className="report-preview-topbar-tagline">AI · GEO · 数据洞察</div>
          </div>
          <div className="report-preview-topbar-right">
            <div className="report-preview-topbar-project">
              {snapshot.project.name}
            </div>
            <div className="report-preview-topbar-period">
              报告周期 {meta.period_start} 至 {meta.period_end}
              <span className="report-preview-meta-sep">｜</span>
              基线 {snapshot.baseline.date ?? "—"}
            </div>
          </div>
        </div>

        <h1 className="report-preview-title">GEO 优化周报</h1>

        <div className="report-preview-meta">
          报告周期:{meta.period_start} 至 {meta.period_end}
          <span className="report-preview-meta-sep">｜</span>
          基线:{snapshot.baseline.date ?? "—"}
          {snapshot.baseline.rate !== null && (
            <>
              <span className="report-preview-meta-sep">｜</span>
              监测快照:{snapshot.daily_mention_rate?.[0]?.date} /{" "}
              {snapshot.daily_mention_rate?.[snapshot.daily_mention_rate.length - 1]?.date}
            </>
          )}
          <span className="report-preview-meta-sep">｜</span>
          口径:整体提及率 = 已提及题数 ÷ 监测题数
        </div>

        <SectionOneOverall snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionTwoSummary snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionThreeBreakdown snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionFourContentOps snapshot={snapshot} />
        <SectionFiveWeeklyChanges snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionAttribution snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />

        <footer className="report-preview-footer">
          <div>
            本报告由风球科技出具 ｜ 所属公司 {company} ｜ 基线{" "}
            {snapshot.baseline.date ?? "—"} ｜ 报告周期 {meta.period_start} 至{" "}
            {meta.period_end}
          </div>
          <div>
            口径：已提及题数 ÷ {denominator || "—"} ｜ © {reportYear} 风球科技 ·
            仅供 {company} 内部使用
          </div>
        </footer>
      </article>
    </div>
  );
}
