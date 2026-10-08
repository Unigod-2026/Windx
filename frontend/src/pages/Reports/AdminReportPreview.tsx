/**
 * Admin 路由 `/admin/reports/:id` —— 已登录运营查看 / 编辑草稿并发布。
 *
 * 与公开 URL(`/public/reports/:token`)的分工:
 * - 公开 URL 只展示已发布报告的预渲染 HTML(由后端 ``render_html`` 在
 *   publish 时落盘),任何人都能看、不需要登录。
 * - Admin 路由是草稿编辑入口:auth-gated、读 JSON snapshot、走 React 章节
 *   组件 + 内联 ``EditableCallout``,保存 / 发布 / 取消发布都在这里。
 *
 * 设计原因:把「读 JSON 重渲染」的开销留在登录后的运营侧,把「静态展示」
 * 留给公网。两边不混用 —— 之前一个组件同时承担两种角色,既需要懂 JWT 又
 * 容易把草稿内容泄露到 token URL。
 */

import { useEffect, useState } from "react";
import { Alert, Button, Skeleton, Space, message } from "antd";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  getReportSnapshot,
  publicReportUrl,
  publishReport,
  unpublishReport,
  updateReport,
  type Report,
  type ReportSnapshotOut,
} from "../../api/reports";
import {
  SectionAttribution,
  SectionFiveWeeklyChanges,
  SectionFourContentOps,
  SectionOneOverall,
  SectionThreeBreakdown,
  SectionTwoSummary,
} from "../Projects/ReportSections";
import "../Projects/ReportPreview.css";

export default function AdminReportPreview() {
  const params = useParams<{ id: string }>();
  const id = Number(params?.id ?? 0);
  const navigate = useNavigate();
  const location = useLocation();
  // 公网快照模式:``_render_admin_html_via_browser`` 用 ``?mode=public`` 打开本
  // 路由来生成公网静态 HTML。该模式下必须只读(否则「编辑」链接会被烤进
  // 公网页面,点了没反应),并且整条工具栏都要隐藏(发布 / 取消发布 / 返回
  // 都是 admin 控件)。这是显式契约,不依赖 ``is_published`` 的提交时序。
  const isPublicSnapshot =
    new URLSearchParams(location.search).get("mode") === "public";
  const [data, setData] = useState<ReportSnapshotOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [publishing, setPublishing] = useState(false);

  const reload = async () => {
    if (!id) return;
    const fresh = await getReportSnapshot(id);
    setData(fresh);
    return fresh;
  };

  useEffect(() => {
    if (!id) {
      setLoading(false);
      setError("报告 id 无效");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getReportSnapshot(id)
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
  }, [id]);

  const saveDraft = async (overrides: Record<string, string | null>) => {
    if (!data) return;
    try {
      await updateReport(data.meta.id, overrides);
      message.success("草稿已保存");
      await reload();
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
      const fresh = await reload();
      if (fresh && updated.is_published) {
        // 复制新的 share_token URL 给运营,方便贴到 IM
        const url = publicReportUrl(updated.share_token);
        try {
          await navigator.clipboard.writeText(url);
          message.info("新的分享链接已复制到剪贴板");
        } catch {
          message.info(`新的分享链接:${url}`);
        }
      }
    } catch (err) {
      message.error((err as Error).message || "发布失败");
    } finally {
      setPublishing(false);
    }
  };

  const unpublish = async () => {
    if (!data) return;
    try {
      await unpublishReport(data.meta.id);
      message.success("已取消发布");
      await reload();
    } catch (err) {
      message.error((err as Error).message || "取消发布失败");
    }
  };

  /** 已发布报告的「复制链接」—— 复制公网 token URL,无需登录即可打开。
   *  这个位置原本是「返回」,但运营都是从周报列表 ``window.open`` 打开本页,
   *  没有上一条历史记录,``navigate(-1)`` 点了没反应。 */
  const copyShareLink = async () => {
    if (!data) return;
    const url = publicReportUrl(data.meta.share_token);
    try {
      await navigator.clipboard.writeText(url);
      message.info("公网链接已复制到剪贴板");
    } catch {
      // 非 https / 剪贴板权限被拒 —— 退化成把 URL 直接显示出来
      message.info(`公网链接:${url}`);
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
        <Alert
          type="error"
          message={error}
          action={
            <Button onClick={() => navigate(-1)}>返回</Button>
          }
          showIcon
        />
      </div>
    );
  }
  if (!data) return null;

  const { meta, snapshot } = data;
  const canEdit = !meta.is_published && !isPublicSnapshot;
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
      {/* 公网快照模式下整条工具栏不渲染 —— 这些是 admin 控件,烤进公网
          HTML 会变成点了没反应的死按钮。公网页自己的「打印 / PDF」由
          PublicReportPreview 提供。 */}
      {!isPublicSnapshot && (
        <div className="report-preview-bar">
          <Space>
            {!canEdit && <Button onClick={copyShareLink}>复制链接</Button>}
            {!canEdit && (
              <Button onClick={unpublish} danger>
                取消发布
              </Button>
            )}
            {/* 公开 URL 复制按钮由 ReportTab 列表的「复制链接」提供,
                这里不再嵌一个「查看公开链接」按钮,避免运营点完「发布」后
                误触它跳转到公网 URL(老 token 残留的「旧地址」就是这个来源)。 */}
            {!canEdit && <Button onClick={() => window.print()}>打印 / PDF</Button>}
            {canEdit && (
              <Button
                type="primary"
                onClick={publish}
                loading={publishing}
              >
                发布
              </Button>
            )}
          </Space>
        </div>
      )}

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
          {/* 「状态: 草稿 / 已发布」是 admin 元信息,公网快照里不出现
              (渲染发生在 is_published 提交之前,会显示成「草稿」)。 */}
          {!isPublicSnapshot && (
            <>
              <span className="report-preview-meta-sep">｜</span>
              状态:
              {meta.is_published ? (
                <span style={{ color: "#389E0F", fontWeight: 600 }}>已发布</span>
              ) : (
                <span style={{ color: "#FA8C16", fontWeight: 600 }}>草稿</span>
              )}
            </>
          )}
        </div>

        <SectionOneOverall snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionTwoSummary snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionThreeBreakdown snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionFourContentOps snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionFiveWeeklyChanges snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />
        <SectionAttribution snapshot={snapshot} canEdit={canEdit} onSave={saveDraft} />

        <footer className="report-preview-footer">
          <div>
            本报告由风球科技出具 ｜ 所属公司 {company} ｜ 基线{" "}
            {snapshot.baseline.date ?? "—"} ｜ 报告周期 {meta.period_start} 至{" "}
            {meta.period_end}
          </div>
          <div>
            口径:已提及题数 ÷ {denominator || "—"} ｜ © {reportYear} 风球科技 ·
            仅供 {company} 内部使用
          </div>
        </footer>
      </article>
    </div>
  );
}