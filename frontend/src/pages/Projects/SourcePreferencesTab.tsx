/**
 * 「信源偏好」tab —— 4 sub-tab 容器:
 *   - 全部信源      → AllSources(原视图)
 *   - 信源明细      → SourceDetail(30/70 分屏:左侧列表 + 右侧 iframe)
 *   - 视频类信源    → VideoSources(平台卡片网格 + 按模型 ranking)
 *   - 网站分类      → Placeholder(敬请期待)
 *
 * 注:「自有文章引用分析」已拆为顶层菜单项(数据洞察组,与「信源偏好」平级),
 * 不再放在本 tab 内。
 *
 * 右上角「导入官方媒体字典」按钮 —— super_admin 才显示。
 * 点击打开 MediaDictionaryImportModal,xlsx 上传 + 预览 + 确认导入;
 * 完成后回调刷新 dictTotal,按钮旁显示「已导入 N 条」。
 *
 * sub-tab 视觉参照 CitationAnalysisTab 的 .qt-secondary-tabs 手写实现,
 * 不引入 antd Tabs(避免与项目内其它 tab 视觉不一致)。
 */

import { useEffect, useState } from "react";
import { Button } from "antd";
import { CloudUploadOutlined } from "@ant-design/icons";
import { listMediaDictionary, type MediaDictionaryImportResult } from "../../api/admin";
import { useAuth } from "../../auth/AuthProvider";
import MediaDictionaryImportModal from "../../components/MediaDictionaryImportModal";
import AllSources from "./sourcePreferences/AllSources";
import Placeholder from "./sourcePreferences/Placeholder";
import SourceDetail from "./sourcePreferences/SourceDetail";
import VideoSources from "./sourcePreferences/VideoSources";

interface Props {
  projectId: number;
}

type SubTab = "all" | "detail" | "category" | "video";

const SUB_TABS: { key: SubTab; label: string }[] = [
  { key: "all", label: "全部信源" },
  { key: "detail", label: "信源明细" },
  { key: "category", label: "网站分类" },
  { key: "video", label: "视频类信源" },
];

export default function SourcePreferencesTab({ projectId }: Props) {
  const { user } = useAuth();
  const isSuper = user?.role === "super_admin";

  const [sub, setSub] = useState<SubTab>("all");
  const [dictTotal, setDictTotal] = useState<number | null>(null);
  const [importOpen, setImportOpen] = useState(false);

  // mount-once:拉一次字典总数,作为按钮旁的「已导入 N 条」提示。
  useEffect(() => {
    if (!isSuper) return;
    listMediaDictionary()
      .then((d) => setDictTotal(d.total))
      .catch(() => setDictTotal(null));
  }, [isSuper]);

  const handleImported = (result: MediaDictionaryImportResult) => {
    setDictTotal(result.total_in_dictionary);
  };

  return (
    <div className="sp-shell">
      {/* 顶部 sub-tab bar + 字典导入按钮 */}
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
        {isSuper && (
          <div className="sp-secondary-tabs-right">
            <Button
              type="default"
              icon={<CloudUploadOutlined />}
              onClick={() => setImportOpen(true)}
            >
              导入官方媒体字典
              {dictTotal !== null && dictTotal > 0 && (
                <span className="sp-dict-pill">已导入 {dictTotal} 条</span>
              )}
            </Button>
          </div>
        )}
      </div>

      {/* 内容区 */}
      <div className="sp-content">
        {sub === "all" && <AllSources projectId={projectId} />}
        {sub === "detail" && <SourceDetail projectId={projectId} />}
        {sub === "category" && <Placeholder label="网站分类" />}
        {sub === "video" && <VideoSources projectId={projectId} />}
      </div>

      {/* 导入 modal —— 内部已完成 toast,父组件只更新 dictTotal */}
      <MediaDictionaryImportModal
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={handleImported}
      />

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
        .sp-secondary-tabs-right {
          display: flex;
          align-items: center;
          gap: 8px;
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
        .sp-dict-pill {
          margin-left: 8px;
          padding: 1px 8px;
          font-size: 11px;
          color: var(--brand-blue, #1a55e8);
          background: rgba(26, 85, 232, 0.08);
          border-radius: 999px;
          font-weight: 500;
        }
        .sp-content {
          background: transparent;
        }
      `}</style>
    </div>
  );
}
