/**
 * 「自有文章引用分析」→ 顶层容器,2 个子 tab:
 *   - 自有文章列表  → ArticleList(原表格视图,导入 URL 列表按钮)
 *   - 自由文章提及状况 → PromptMatrix(per-prompt × per-period 矩阵,
 *                       文档「doc/信源分析.docx」需求 1)
 *
 * 设计要点:
 * - sub-tab 视觉沿用 SourcePreferencesTab 自写的 .sp-secondary-tabs 手写实现,
 *   不引入 antd Tabs 跟项目其它 tab 视觉保持一致。
 * - 子 tab 各自管理自己的过滤状态,不共用 ToolbarFilter(矩阵的 3 段日期
 *   与 ToolbarFilter 的单段日期是不同概念,PromptMatrix 内部用本地 state)。
 */

import { useState } from "react";
import ArticleList from "./ArticleList";
import PromptMatrix from "./PromptMatrix";

interface Props {
  projectId: number;
}

type SubTab = "list" | "matrix";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "list", label: "自有文章列表" },
  { key: "matrix", label: "自由文章提及状况" },
];

export default function SelfArticles({ projectId }: Props) {
  const [sub, setSub] = useState<SubTab>("list");

  return (
    <div className="sp-shell">
      <div className="sp-secondary-tabs">
        <div className="sp-secondary-tabs-left">
          {SUB_TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`sp-subtab${sub === t.key ? " active" : ""}`}
              onClick={() => setSub(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      <div className="sp-content">
        {sub === "list" && <ArticleList projectId={projectId} />}
        {sub === "matrix" && <PromptMatrix projectId={projectId} />}
      </div>

      <style>{`
        .sp-shell {
          display: flex;
          flex-direction: column;
          gap: 12px;
        }
        .sp-secondary-tabs {
          display: flex;
          align-items: center;
          justify-content: space-between;
          background: #fff;
          padding: 0 24px;
          border-radius: 8px 8px 0 0;
          border: 1px solid var(--border-light, #f0f0f0);
          border-bottom: 0;
          flex-shrink: 0;
        }
        .sp-secondary-tabs-left {
          display: flex;
          gap: 4px;
          flex-wrap: wrap;
        }
        .sp-subtab {
          background: transparent;
          border: 0;
          padding: 12px 16px;
          font-size: 14px;
          color: var(--text-secondary, #4f4f4f);
          cursor: pointer;
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;
          font-family: inherit;
          white-space: nowrap;
        }
        .sp-subtab:hover { color: var(--brand-blue, #1a55e8); }
        .sp-subtab.active {
          color: var(--brand-blue, #1a55e8);
          border-bottom-color: var(--brand-blue, #1a55e8);
          font-weight: 500;
        }
        .sp-content {
          background: transparent;
        }
      `}</style>
    </div>
  );
}
