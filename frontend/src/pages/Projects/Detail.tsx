import { useEffect, useState } from "react";
import { Alert, Skeleton, message } from "antd";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useSetCurrentProject } from "../../auth/ProjectContext";
import { getProject, type ProjectDetailOut } from "../../api/projects";
import OverviewTab from "./OverviewTab";
import PromptsTab from "./PromptsTab";
import QuestionTab from "./QuestionTab";
import CompetitorAnalysisTab from "./CompetitorAnalysisTab";
import CitationAnalysisTab from "./CitationAnalysisTab";
import CompetitorsTab from "./CompetitorsTab";
import PlaceholderTab from "./PlaceholderTab";

const VALID_TABS = [
  "overview",
  "question",
  "competitor",
  "source",
  "citation",
  "answer",
  "prompts",
  "competitors",
  "settings",
] as const;
type ProjectTabKey = (typeof VALID_TABS)[number];

const DEFAULT_TAB: ProjectTabKey = "overview";

function readTab(value: string | null): ProjectTabKey {
  if (value && (VALID_TABS as readonly string[]).includes(value)) {
    return value as ProjectTabKey;
  }
  return DEFAULT_TAB;
}

/**
 * 项目详情页 —— 渲染当前 ``?tab=`` 对应的 tab 内容。
 *
 * 左侧导航(数据洞察 / 数据中心 / 系统 + 管理组)由 AppLayout 的统一侧边栏
 * 渲染,项目名 + 操作按钮在监控项目列表页管理,这里只输出 tab 内容,
 * 跟 docs/ui-sample/index.html 的 ``#tab-overview`` 布局一致。
 */
export default function ProjectDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const setCurrentProjectId = useSetCurrentProject();
  const [searchParams] = useSearchParams();
  const projectId = id && /^\d+$/.test(id) ? Number(id) : null;
  const activeKey = readTab(searchParams.get("tab"));

  const [detail, setDetail] = useState<ProjectDetailOut | null>(null);
  const [loading, setLoading] = useState(true);

  const reload = async () => {
    if (projectId === null) return;
    setLoading(true);
    try {
      const data = await getProject(projectId);
      setDetail(data);
    } catch (err) {
      message.error((err as Error).message || "项目加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId]);

  // Publish the loaded project id to ProjectContext so the sidebar's
  // 数据洞察 / 数据中心 / 系统 groups persist when the user navigates
  // away (e.g. clicks 工作台 or 监控项目 under 管理组). We deliberately
  // do NOT clear the context on unmount — the value should outlive this
  // component so sidebar groups stay visible after leaving /admin/projects/:id.
  useEffect(() => {
    if (projectId !== null) setCurrentProjectId(projectId);
  }, [projectId, setCurrentProjectId]);

  if (projectId === null) {
    return (
      <Alert
        type="error"
        message="无效的项目 ID"
        showIcon
        action={
          <a onClick={() => navigate("/admin/projects")}>返回项目列表</a>
        }
      />
    );
  }

  if (loading || !detail) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  const activePanel = (() => {
    switch (activeKey) {
      case "overview":
        return <OverviewTab projectId={projectId} />;
      case "prompts":
        return <PromptsTab projectId={projectId} />;
      case "competitors":
        return <CompetitorsTab projectId={projectId} />;
      case "question":
        return <QuestionTab projectId={projectId} />;
      case "competitor":
        return <CompetitorAnalysisTab projectId={projectId} />;
      case "source":
        return (
          <PlaceholderTab
            title="信源偏好"
            hint="每个大模型引用最多的信源类型 TOP3 + 信源异动"
          />
        );
      case "citation":
        return <CitationAnalysisTab projectId={projectId} />;
      case "answer":
        return (
          <PlaceholderTab
            title="AI 回答详情"
            hint="按 (问题, 模型) 维度查看 AI 原始回答内容"
          />
        );
      case "settings":
        return (
          <PlaceholderTab
            title="项目设置"
            hint="账号、通知偏好、数据导出等基础设置"
          />
        );
    }
  })();

  return <div className="project-detail-page">{activePanel}</div>;
}