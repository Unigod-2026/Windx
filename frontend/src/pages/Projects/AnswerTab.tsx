/**
 * 「答案质量分析」一级 tab —— 顶层容器,组合 3 个 sub-pane。
 *
 * 参照 docs/风球GEO监控平台UI/index.html:1510-1783 的 tab-quality
 * 区段,本版本覆盖:
 *   - AI 回答原始内容 → RawAnswersPane(各模型回答合并 + 命中率 + 排名 + 图例)
 *   - 答案详情         → AnswerDetailPane(单模型 + 思考过程 / 命中率)
 *   - 质量概览         → QualityOverviewPane(占位,评分引擎下一期)
 *
 * sub-tab 状态用 local useState,不写 URL —— Detail.tsx 的 URL tab 已经
 * 在管 "answer" 这个一级 tab,sub-tab 是页面内的导航,刷新重置到 raw。
 *
 * 问题筛选走全局工具栏 ``useToolbarFilter().selectedPromptIds``,
 * 本 tab 不再渲染独立的 PromptPicker;工具栏未筛选(``null`` / 空数组)
 * 时 fallback 到项目下第一个非 archived 的 prompt,保证首屏一定有数据。
 * 工具栏筛了多个时取第一个;sub-pane 是单 prompt 视图,多选 UI 不在本期。
 *
 * 数据真源:
 * - ``getProject(projectId)`` + ``listCompetitors(projectId)`` 一次性拉项目
 *   详情和竞品,传给所有 sub-pane 复用。
 *
 * toolbar 联动:
 * - 日期 / 模型 / 终端 / 模式筛选由 RawAnswersPane / AnswerDetailPane 自行
 *   读取 useToolbarFilter,AnswerTab 本身只透传 promptId。
 */

import { useEffect, useMemo, useState } from "react";
import { Skeleton, Tag, message } from "antd";
import {
  getProject,
  listCompetitors,
  type CompetitorOut,
  type ProjectDetailOut,
} from "../../api/projects";
import { useToolbarFilter } from "../../components/ToolbarFilterContext";
import RawAnswersPane from "./answerTab/RawAnswersPane";
import AnswerDetailPane from "./answerTab/AnswerDetailPane";
import QualityOverviewPane from "./answerTab/QualityOverviewPane";

interface Props {
  projectId: number;
}

type SubTab = "raw" | "detail" | "overview";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "raw", label: "AI 回答原始内容" },
  { key: "detail", label: "答案详情" },
  { key: "overview", label: "质量概览" },
];

function pickPromptId(
  selected: number[] | null,
  prompts: ProjectDetailOut["prompts"],
): number | null {
  if (selected && selected.length > 0) return selected[0];
  const first = prompts.find((p) => p.status !== "archived");
  return first ? first.id : null;
}

export default function AnswerTab({ projectId }: Props) {
  const [project, setProject] = useState<ProjectDetailOut | null>(null);
  const [competitors, setCompetitors] = useState<CompetitorOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [sub, setSub] = useState<SubTab>("raw");
  /** RawAnswersPane 跳到 detail 时预选某个 subtask */
  const [initialSubtaskId, setInitialSubtaskId] = useState<string | null>(null);

  const toolbar = useToolbarFilter();
  const toolbarPrompts = toolbar.selectedPromptIds;
  const toolbarVersion = toolbar.version;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    Promise.all([
      getProject(projectId),
      listCompetitors(projectId).catch(() => ({ items: [], total: 0 })),
    ])
      .then(([proj, comps]) => {
        if (cancelled) return;
        setProject(proj);
        setCompetitors(comps.items);
      })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "项目加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const prompts = useMemo(
    () => project?.prompts ?? [],
    [project],
  );

  // toolbar 没筛 → 取第一个非 archived;筛了多个 → 取第一个。
  // 用 toolbarVersion 触发重新计算(用户点应用后这里也会跟着变)。
  const promptId = useMemo(
    () => pickPromptId(toolbarPrompts, prompts),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [toolbarPrompts, toolbarVersion, prompts],
  );

  // 当前展示的 prompt 在工具栏已筛列表里的位置 + 总数,sub-pane 不感知,
  // header 用 Tag 给个上下文。多选时不显示具体位置,只显示「已选 N 个」。
  const promptMeta = useMemo(() => {
    if (!toolbarPrompts || toolbarPrompts.length === 0) return null;
    if (toolbarPrompts.length === 1) return null;
    return { total: toolbarPrompts.length };
  }, [toolbarPrompts]);

  // 切问题(promptId 变化)→ 清空 detail 的预选模型
  useEffect(() => {
    setInitialSubtaskId(null);
  }, [promptId]);

  const handleJumpToDetail = (subtaskId: string) => {
    setInitialSubtaskId(subtaskId);
    setSub("detail");
  };

  if (loading || !project) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  if (prompts.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)" }}>
        本项目尚未配置任何问题,无法做答案质量分析。
      </div>
    );
  }

  return (
    <div className="at-shell">
      {/* 当前筛选上下文 —— 工具栏已筛多个问题时报个提示,单选 / 未筛时静默 */}
      {promptMeta && (
        <div className="at-context">
          <Tag color="blue" style={{ margin: 0 }}>
            工具栏已选 {promptMeta.total} 个问题,本页展示第一个
          </Tag>
        </div>
      )}

      {/* sub-tab 条 */}
      <div className="at-subtabs">
        {SUB_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`at-subtab${sub === t.key ? " active" : ""}`}
            onClick={() => setSub(t.key)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 内容区 */}
      <div className="at-content">
        {promptId === null ? (
          <div style={{ padding: 24, textAlign: "center", color: "var(--text-tertiary)" }}>
            请在工具栏选择问题
          </div>
        ) : sub === "raw" ? (
          <RawAnswersPane
            projectId={projectId}
            promptId={promptId}
            project={project}
            competitors={competitors}
            onJumpToDetail={handleJumpToDetail}
          />
        ) : sub === "detail" ? (
          <AnswerDetailPane
            projectId={projectId}
            promptId={promptId}
            project={project}
            competitors={competitors}
            initialSubtaskId={initialSubtaskId}
          />
        ) : (
          <QualityOverviewPane />
        )}
      </div>

      <style>{`
        .at-shell {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .at-context { padding: 0 4px; }
        .at-subtabs {
          display: flex;
          gap: 4px;
          background: #fff;
          padding: 0 16px;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px 8px 0 0;
          border-bottom: 0;
        }
        .at-subtab {
          background: transparent;
          border: 0;
          padding: 12px 16px;
          font-size: 14px;
          color: var(--text-secondary, #4f4f4f);
          cursor: pointer;
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;
          font-family: inherit;
        }
        .at-subtab:hover { color: var(--brand-blue, #1a55e8); }
        .at-subtab.active {
          color: var(--brand-blue, #1a55e8);
          border-bottom-color: var(--brand-blue, #1a55e8);
          font-weight: 500;
        }
        .at-content { background: transparent; }
      `}</style>
    </div>
  );
}
