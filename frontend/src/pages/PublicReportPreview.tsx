/**
 * 公开 URL `/public/reports/:token` —— 纯只读。
 *
 * 只服务已发布的报告:后端 gate by ``is_published``(未发布返 404),并返回
 * publish 时预渲染的 HTML 文件文本。前端直接 ``dangerouslySetInnerHTML``
 * 注入,不重跑任何 React 章节组件 —— 这是「公网打开不需要重新渲染」的关键。
 *
 * 编辑草稿请走 admin 路由(/admin/reports/:id,需要登录),不要走 token URL。
 */

import { useEffect, useState } from "react";
import { Alert, Button, Skeleton, Space } from "antd";
import { useParams } from "react-router-dom";
import "./Projects/ReportPreview.css";

export default function PublicReportPreview() {
  const params = useParams<{ token: string }>();
  const token = params?.token ?? "";
  const [html, setHtml] = useState<string | null>(null);
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
    fetch(`/api/public/reports/${encodeURIComponent(token)}`)
      .then((r) => {
        if (!r.ok) {
          throw new Error(
            r.status === 404
              ? "链接无效或报告未发布"
              : `加载失败 (HTTP ${r.status})`,
          );
        }
        return r.text();
      })
      .then((t) => {
        if (!cancelled) setHtml(t);
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

  if (loading) {
    return (
      <div className="report-preview">
        <Skeleton active />
      </div>
    );
  }
  if (error || html === null) {
    return (
      <div className="report-preview">
        <Alert
          type="error"
          message={error ?? "报告加载失败"}
          description="如果是未发布的报告,请登录后到管理后台查看。"
          showIcon
        />
      </div>
    );
  }

  return (
    <div className="report-preview">
      <div className="report-preview-bar">
        <span />
        <Space>
          <Button onClick={() => window.print()}>打印 / PDF</Button>
        </Space>
      </div>
      {/* 后端 render_html 已包含完整 HTML 文档(<html><head>...),这里 innerHTML
          直接挂到根容器即可,不会嵌套 html/body。 */}
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </div>
  );
}