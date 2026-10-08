/**
 * 「自有文章引用分析」—— 独立一级页面(顶层菜单项),表格视图。
 *
 * 7 列:文章(标题 + URL) / 发布日期 / 分发渠道 / 引用次数 / 引用模型 /
 * 最近引用 / 操作(修改、删除)。顶部面板头有「导入 URL 列表」按钮。
 *
 * 参照 docs/风球GEO监控平台UI/index.html:1293-1326 + js/app.js:3026-3055
 * (renderOwnArticles 函数)。
 *
 * 数据真源:
 * - 用户声明的自有 URL:`geo_own_articles` 表
 * - 实际被引用情况:join `geo_subtasks.reference_list_json`(全信源池口径),
 *   URL 经 normalize(小写 scheme+host + 去尾斜杠)后精确匹配
 *
 * 筛选逻辑跟 SourcePreferencesTab 同款:`effectiveModels` 在工具栏全选时
 * fallback 到项目配置的 platform 列表。
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { Button, Empty, Modal, Skeleton, Space, Table, Tag, message } from "antd";
import type { ColumnsType } from "antd/es/table";
import {
  CloudUploadOutlined,
  DeleteOutlined,
  EditOutlined,
} from "@ant-design/icons";
import {
  deleteOwnArticle,
  getOwnArticles,
  getProject,
  type OwnArticleOut,
  type ProjectPlatform,
} from "../../../api/projects";
import { platformColor, platformLabel, rowKeyOfPlatform } from "../platforms";
import { useToolbarFilter } from "../../../components/ToolbarFilterContext";
import OwnArticlesImportModal from "../../../components/OwnArticlesImportModal";
import OwnArticleEditModal from "../../../components/OwnArticleEditModal";

interface Props {
  projectId: number;
}

export default function SelfArticles({ projectId }: Props) {
  const [items, setItems] = useState<OwnArticleOut[]>([]);
  const [loading, setLoading] = useState(true);
  const [importOpen, setImportOpen] = useState(false);
  // 工具栏全选(= selectedModels 是 null)时,fallback 到项目配置的 platform
  // 列表传给后端,避免窗口内某模型 0 数据被悄悄忽略。
  const [projectPlatforms, setProjectPlatforms] = useState<ProjectPlatform[] | null>(null);
  const toolbar = useToolbarFilter();

  useEffect(() => {
    let cancelled = false;
    getProject(projectId)
      .then((d) => {
        if (!cancelled) setProjectPlatforms(d.platforms);
      })
      .catch(() => {
        if (!cancelled) setProjectPlatforms([]);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const effectiveModels = useMemo<string[] | null | undefined>(() => {
    if (toolbar.selectedModels !== null) return toolbar.selectedModels;
    if (projectPlatforms === null) return undefined;
    return projectPlatforms.map(rowKeyOfPlatform);
  }, [toolbar.selectedModels, projectPlatforms]);

  const dateQuery = useMemo(
    () => toolbar.selectedDateRange ?? { days: 15 },
    [toolbar.selectedDateRange],
  );
  const dateKey = useMemo(() => JSON.stringify(dateQuery), [dateQuery]);
  const promptsKey = useMemo(
    () =>
      toolbar.selectedPromptIds ? [...toolbar.selectedPromptIds].sort().join("|") : "all",
    [toolbar.selectedPromptIds],
  );

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const d = await getOwnArticles(projectId, {
        days: dateQuery.days,
        start: dateQuery.start,
        end: dateQuery.end,
        models: effectiveModels ?? undefined,
        prompts: toolbar.selectedPromptIds ?? undefined,
      });
      setItems(d.items);
    } catch (err) {
      message.error((err as Error).message || "自有文章加载失败");
    } finally {
      setLoading(false);
    }
  }, [
    projectId,
    effectiveModels,
    dateKey,
    promptsKey,
    toolbar.version,
    dateQuery.days,
    dateQuery.start,
    dateQuery.end,
    toolbar.selectedPromptIds,
  ]);

  useEffect(() => {
    if (effectiveModels === undefined) return;
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, toolbar.version, effectiveModels, dateKey, promptsKey]);

  const [editing, setEditing] = useState<OwnArticleOut | null>(null);

  const handleEdit = (record: OwnArticleOut) => {
    setEditing(record);
  };

  const handleDelete = useCallback(
    (record: OwnArticleOut) => {
      const label = record.title || record.url;
      Modal.confirm({
        title: "确认删除",
        content: `删除「${label}」?这不影响历史 citation 数据,只是不再纳入「自有文章引用分析」统计。`,
        okText: "删除",
        okType: "danger",
        cancelText: "取消",
        onOk: async () => {
          try {
            await deleteOwnArticle(projectId, record.id);
            message.success("已删除");
            reload();
          } catch (err) {
            const e = err as {
              response?: { data?: { detail?: unknown } };
              message?: string;
            };
            message.error(
              (typeof e?.response?.data?.detail === "string" &&
                e.response.data.detail) ||
                e?.message ||
                "删除失败",
            );
          }
        },
      });
    },
    [projectId, reload],
  );

  const columns = useMemo<ColumnsType<OwnArticleOut>>(
    () => [
      {
        title: "文章",
        dataIndex: "url",
        render: (_: string, r) => (
          <div style={{ minWidth: 240 }}>
            <div
              style={{
                fontSize: 13,
                fontWeight: 600,
                color: "var(--text-primary)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: 360,
              }}
              title={r.title || r.url}
            >
              {r.title || r.url}
            </div>
            <a
              href={r.url}
              target="_blank"
              rel="noreferrer"
              style={{
                fontSize: 12,
                color: "var(--text-tertiary)",
                display: "block",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: 360,
              }}
            >
              {r.url}
            </a>
          </div>
        ),
      },
      {
        title: "发布日期",
        dataIndex: "publish_date",
        width: 110,
        render: (d: string | null) => d ?? <span style={{ color: "var(--text-tertiary)" }}>—</span>,
      },
      {
        title: "分发渠道",
        dataIndex: "channel",
        width: 120,
        render: (c: string) =>
          c ? c : <span style={{ color: "var(--text-tertiary)" }}>—</span>,
      },
      {
        title: "引用次数",
        dataIndex: "cite_count",
        width: 100,
        render: (n: number) => <strong style={{ color: n > 0 ? "var(--brand-blue, #1a55e8)" : undefined }}>{n}</strong>,
      },
      {
        title: "引用模型",
        dataIndex: "cite_models",
        render: (models: string[]) =>
          models.length > 0 ? (
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {models.map((m) => (
                <Tag key={m} color={platformColor(m)} style={{ margin: 0 }}>
                  {platformLabel(m)}
                </Tag>
              ))}
            </div>
          ) : (
            <span style={{ color: "var(--text-tertiary)" }}>—</span>
          ),
      },
      {
        title: "最近引用",
        dataIndex: "last_cited",
        width: 170,
        render: (d: string) =>
          d && d !== "—" ? (
            <span style={{ fontVariantNumeric: "tabular-nums" }}>{d}</span>
          ) : (
            <span style={{ color: "var(--text-tertiary)" }}>—</span>
          ),
      },
      {
        title: "操作",
        key: "actions",
        width: 130,
        render: (_: unknown, r) => (
          <Space size={4}>
            <Button
              type="link"
              size="small"
              icon={<EditOutlined />}
              onClick={() => handleEdit(r)}
            >
              修改
            </Button>
            <Button
              type="link"
              size="small"
              danger
              icon={<DeleteOutlined />}
              onClick={() => handleDelete(r)}
            >
              删除
            </Button>
          </Space>
        ),
      },
    ],
    // handleDelete 依赖 reload,放进 deps 让 columns 跟着重算。
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [handleDelete],
  );

  if (loading && items.length === 0) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  return (
    <div className="oa-root">
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>自有文章引用分析</h3>
            <p>追踪品牌自有文章是否被 AI 引用、引用频率与模型分布,支持引用提醒</p>
          </div>
          <Button
            type="primary"
            icon={<CloudUploadOutlined />}
            onClick={() => setImportOpen(true)}
          >
            导入 URL 列表
          </Button>
        </div>
        <div className="panel-body">
          {items.length === 0 ? (
            <Empty
              description="尚未导入自有文章"
              style={{ padding: 40 }}
              children={
                <Button
                  type="primary"
                  icon={<CloudUploadOutlined />}
                  onClick={() => setImportOpen(true)}
                >
                  导入 URL 列表
                </Button>
              }
            />
          ) : (
            <Table<OwnArticleOut>
              rowKey="id"
              loading={loading}
              dataSource={items}
              columns={columns}
              pagination={{
                pageSize: 20,
                showTotal: (t) => `共 ${t} 条`,
                showSizeChanger: true,
              }}
              size="middle"
            />
          )}
        </div>
      </div>

      <OwnArticlesImportModal
        projectId={projectId}
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onImported={reload}
      />

      <OwnArticleEditModal
        projectId={projectId}
        article={editing}
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSaved={reload}
      />

      <style>{`
        .oa-root { padding: 12px 0; }
        .panel {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          display: flex;
          flex-direction: column;
        }
        .panel-header {
          padding: 14px 18px 10px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
        }
        .panel-header h3 {
          margin: 0;
          font-size: 15px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .panel-header p {
          margin: 4px 0 0;
          font-size: 12px;
          color: var(--text-tertiary);
        }
        .panel-body { padding: 16px 18px; }
      `}</style>
    </div>
  );
}
