/**
 * 差异化分析 tab 顶层组件(v3.2 重写)。
 *
 * 数据来源是 ``CompetitorAnalysisOut.diff_brand``(后端 ``_compute_diff_brand``
 * 已算好 head_value / pc_rate / mobile_rate),结构是 3 指标 × (1+ |competitors|) 张
 * 品牌卡。toolbar 模型筛选变化时后端会重算 rows(按 selected_codes 收窄),行
 * 数与项目配置的 platform 数会动态联动;关闭状态通过 useDiffPanelVisibility
 * 持久化在 localStorage。
 *
 * 区头部 / 工具条 / KPI / 表格 / 端侧差异条的样式全部内嵌在底部 <style> 块里
 * (沿用父级 CompetitorAnalysisTab 的 <style> 内嵌惯例);这里只写差异化分析
 * 专用的 .diff-* 选择器,跟 OverviewTab / TrendFullPane 的样式不冲突。
 */

import { useCallback, useEffect, useMemo } from "react";
import { Empty } from "antd";
import type { CompetitorAnalysisOut, DiffBrandCard, DiffBrandMetric } from "../../../api/projects";
import { useToolbarFilter } from "../../../components/ToolbarFilterContext";
import DiffZone from "./DiffZone";
import { useDiffPanelVisibility } from "./useDiffPanelVisibility";

interface Props {
  data: CompetitorAnalysisOut;
}

export default function DiffPane({ data }: Props) {
  const toolbar = useToolbarFilter();
  const { diff_brand } = data;

  // 空态 1:项目未配监控品牌(self_brand_canonical == null)
  if (diff_brand.self_brand_canonical == null) {
    return <Empty description="请先在项目设置中配置监控品牌" style={{ padding: 32 }} />;
  }

  // 空态 2:toolbar 显式空选(用户全清了下拉)。全选(null)跟显式空选([])在
  // 后端是不同语义,前端按用户意图区分 —— toolbar 拿到的「空选」会到这里的
  // 渲染分支(因为没有 rows 可以画)。
  if (toolbar.selectedModels !== null && toolbar.selectedModels !== undefined
      && toolbar.selectedModels.length === 0) {
    return <Empty description="请至少选择 1 个模型" style={{ padding: 32 }} />;
  }

  // 当前有效的「关闭 key」全集 = 3 × (1 + |competitors|) 个,用作
  // useDiffPanelVisibility 的 validKeys;切项目 / 数据变化时 effect 自动清脏
  // key,无需这里手动同步。
  const validKeys = useMemo(() => {
    const set = new Set<string>();
    for (const c of diff_brand.cards) {
      set.add(`${c.metric}::${c.brand_canonical}`);
    }
    return set;
  }, [diff_brand.cards]);

  const { panels, persist, reset } = useDiffPanelVisibility(validKeys);

  // panels 里的元素 = 「该 card 当前关闭」(沿用原型 App.diffPanels 语义)。
  // 切项目时 validKeys 变 → effect 自动把脏 key 过滤掉,这里只是读取用。
  const isOpen = useCallback(
    (card: DiffBrandCard) => !panels.includes(`${card.metric}::${card.brand_canonical}`),
    [panels],
  );

  // 关闭(加入 panels)/ 展开(从 panels 移除)
  const closeCard = useCallback(
    (card: DiffBrandCard) => {
      const k = `${card.metric}::${card.brand_canonical}`;
      if (panels.includes(k)) return;
      persist([...panels, k]);
    },
    [panels, persist],
  );
  const openCard = useCallback(
    (card: DiffBrandCard) => {
      const k = `${card.metric}::${card.brand_canonical}`;
      persist(panels.filter((x) => x !== k));
    },
    [panels, persist],
  );

  // 整区 / 整面「全部展开 / 全部收起 / 恢复默认」三个动作
  const expandAll = useCallback(() => persist([]), [persist]);
  const collapseAll = useCallback(() => persist([...validKeys]), [persist, validKeys]);

  // 「整区展开 / 收起」:把本 metric 下所有 key 一次性 set / unset
  const expandMetric = useCallback(
    (metric: DiffBrandMetric) => {
      const set = new Set(panels);
      for (const c of diff_brand.cards) {
        if (c.metric === metric) set.delete(`${c.metric}::${c.brand_canonical}`);
      }
      persist([...set]);
    },
    [panels, persist, diff_brand.cards],
  );
  const collapseMetric = useCallback(
    (metric: DiffBrandMetric) => {
      const set = new Set(panels);
      for (const c of diff_brand.cards) {
        if (c.metric === metric) set.add(`${c.metric}::${c.brand_canonical}`);
      }
      persist([...set]);
    },
    [panels, persist, diff_brand.cards],
  );

  // 按 metric 分组 + 找自身卡(同 metric 下 is_self=true)
  const grouped = useMemo(() => {
    const out: Record<DiffBrandMetric, DiffBrandCard[]> = { mention: [], top1: [], top3: [] };
    let selfByMetric: Record<DiffBrandMetric, DiffBrandCard | null> = {
      mention: null,
      top1: null,
      top3: null,
    };
    for (const c of diff_brand.cards) {
      out[c.metric].push(c);
      if (c.is_self) selfByMetric[c.metric] = c;
    }
    return { cards: out, selfByMetric };
  }, [diff_brand.cards]);

  // 顶部说明条 + 工具条计数文案(实时跟随 toolbar)
  const noteText = useMemo(() => buildNoteText(toolbar.selectedDateRange,
    toolbar.selectedModels, toolbar.selectedPromptIds), [
    toolbar.selectedDateRange,
    toolbar.selectedModels,
    toolbar.selectedPromptIds,
  ]);
  const visibleCount = validKeys.size - panels.length;
  const totalCount = validKeys.size;

  // 数据变化 / 切项目时若 localStorage 残留了别的项目 key,hook 内部 effect
  // 已经把它们清掉;这里再补一道「外部 panels 变化时同步写回 localStorage」
  // 的兜底(useEffect 监听 panels → persist 由 hook 内部 useState 完成,这里
  // 不用再写)。这段注释保留防止后人误删。

  // 阻止首次挂载的 useEffect 双写:本组件无外部写入口,persist 已在 hook 内
  // 同步 setState,无需在此处重复。
  useEffect(() => { /* hook 已自管 persist */ }, [panels]);

  return (
    <div className="diff-pane-root">
      {/* 顶部说明条 —— 「当前口径: <日期> · <模型> · <问题>;...」 */}
      <div className="diff-note">
        <span className="diff-note-icon">ⓘ</span>
        <span>当前口径:{noteText};</span>
        <span>每张卡片为单个品牌的完整明细,卡内可按模型与终端拆分</span>
      </div>

      {/* 顶部工具条 —— 计数 + 全部展开 / 全部收起 / 恢复默认 */}
      <div className="diff-toolbar">
        <div className="diff-toolbar-left">
          <span className="diff-toolbar-label">差异化分析</span>
          <span className="diff-toolbar-count">
            已显示 {visibleCount} / {totalCount} 项
          </span>
        </div>
        <div className="diff-toolbar-actions">
          <button type="button" className="diff-tb-btn" onClick={expandAll}>
            全部展开
          </button>
          <button type="button" className="diff-tb-btn" onClick={collapseAll}>
            全部收起
          </button>
          <button
            type="button"
            className="diff-tb-btn diff-tb-btn-primary"
            onClick={reset}
          >
            恢复默认
          </button>
        </div>
      </div>

      {/* 3 个指标区 */}
      {diff_brand.metrics.map((m) => (
        <DiffZone
          key={m.id}
          metric={m}
          brandCards={grouped.cards[m.id as DiffBrandMetric] ?? []}
          selfCard={grouped.selfByMetric[m.id as DiffBrandMetric]}
          isCardOpen={isOpen}
          onOpenCard={openCard}
          onCloseCard={closeCard}
          onExpandAll={() => expandMetric(m.id as DiffBrandMetric)}
          onCollapseAll={() => collapseMetric(m.id as DiffBrandMetric)}
        />
      ))}

      <style>{`
        .diff-pane-root { padding: 4px 0 16px; }

        /* ---- 顶部说明条 ---- */
        .diff-note {
          display: flex;
          align-items: center;
          gap: 8px;
          background: #f5f8ff;
          border: 1px solid #dcdcdc;
          border-left: 3px solid #1a55e8;
          border-radius: 8px;
          padding: 10px 16px;
          font-size: 12px;
          color: var(--text-secondary, #4f4f4f);
          margin-bottom: 16px;
          line-height: 1.6;
          flex-wrap: wrap;
        }
        .diff-note-icon {
          color: #1a55e8;
          font-weight: 600;
        }

        /* ---- 工具条 ---- */
        .diff-toolbar {
          display: flex;
          align-items: center;
          justify-content: space-between;
          gap: 12px;
          padding: 10px 14px;
          margin-bottom: 16px;
          background: #fff;
          border: 1px solid #dcdcdc;
          border-radius: 8px;
        }
        .diff-toolbar-left {
          display: flex;
          align-items: center;
          gap: 10px;
          min-width: 0;
        }
        .diff-toolbar-label {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary, #1f1f1f);
          white-space: nowrap;
        }
        .diff-toolbar-count {
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
          font-variant-numeric: tabular-nums;
        }
        .diff-toolbar-actions {
          display: flex;
          gap: 8px;
          flex-shrink: 0;
        }
        .diff-tb-btn {
          height: 28px;
          padding: 0 12px;
          border: 1px solid #dcdcdc;
          border-radius: 6px;
          background: #f5f6f8;
          font-family: inherit;
          font-size: 12px;
          color: var(--text-secondary, #4f4f4f);
          cursor: pointer;
          white-space: nowrap;
          transition: all 0.15s;
        }
        .diff-tb-btn:hover {
          border-color: #1a55e8;
          color: #1a55e8;
          background: #fff;
        }
        .diff-tb-btn-primary {
          border-color: #1a55e8;
          color: #1a55e8;
        }

        /* ---- 指标区 ---- */
        .diff-zone + .diff-zone { margin-top: 20px; }
        .diff-zone-head {
          display: flex;
          align-items: flex-end;
          justify-content: space-between;
          gap: 12px;
          padding: 0 2px 10px;
          border-bottom: 1px solid #f0f0f0;
          margin-bottom: 12px;
        }
        .diff-zone-title h3 {
          margin: 0;
          font-size: 15px;
          font-weight: 600;
          color: var(--text-primary, #1f1f1f);
        }
        .diff-zone-title p {
          margin: 2px 0 0;
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
        }
        .diff-zone-tools {
          display: flex;
          align-items: center;
          gap: 8px;
          flex-shrink: 0;
        }
        .diff-zone-count {
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
          font-variant-numeric: tabular-nums;
          margin-right: 4px;
        }

        /* ---- 品牌卡网格 ---- */
        .diff-zone-body {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(430px, 1fr));
          gap: 14px;
        }
        @media (max-width: 1400px) {
          .diff-zone-body { grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); }
        }

        /* ---- 关闭占位条 ---- */
        .diff-card.is-closed {
          display: flex;
          align-items: center;
          align-self: start;
          min-height: 44px;
          padding: 10px 14px;
          background: #f5f6f8;
          border: 1px dashed #dcdcdc;
          border-radius: 8px;
          cursor: pointer;
          transition: all 0.15s;
        }
        .diff-card.is-closed:hover {
          border-color: #1a55e8;
          background: #fff;
        }
        .diff-card-closed-inner {
          display: flex;
          align-items: center;
          gap: 8px;
          width: 100%;
          min-width: 0;
        }
        .diff-card-closed-name {
          font-size: 13px;
          font-weight: 500;
          color: var(--text-secondary, #4f4f4f);
        }
        .diff-card-closed-metric {
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
          padding: 1px 6px;
          background: #fff;
          border-radius: 3px;
        }
        .diff-card-open-hint {
          margin-left: auto;
          font-size: 12px;
          color: #1a55e8;
          white-space: nowrap;
        }

        /* ---- 展开卡片 ---- */
        .diff-card {
          background: #fff;
          border: 1px solid #dcdcdc;
          border-radius: 8px;
          overflow: hidden;
          transition: box-shadow 0.15s;
        }
        .diff-card:hover { box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06); }
        .diff-card-head {
          display: flex;
          align-items: center;
          gap: 10px;
          padding: 10px 12px 10px 14px;
          border-left: 3px solid var(--brand-color, #1a55e8);
          background: #f5f6f8;
          border-bottom: 1px solid #f0f0f0;
        }
        .diff-card-id {
          display: flex;
          align-items: center;
          gap: 6px;
          min-width: 0;
        }
        .diff-card-name {
          font-size: 14px;
          font-weight: 600;
          color: var(--text-primary, #1f1f1f);
          white-space: nowrap;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .diff-card-tag {
          padding: 1px 6px;
          border-radius: 3px;
          font-size: 11px;
          line-height: 16px;
          background: #f5f8ff;
          color: #1a55e8;
          flex-shrink: 0;
        }
        .diff-card-metric {
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
          white-space: nowrap;
        }
        .diff-card-close {
          margin-left: auto;
          width: 22px;
          height: 22px;
          flex-shrink: 0;
          border: none;
          border-radius: 4px;
          background: transparent;
          color: var(--text-tertiary, #8c8c8c);
          font-size: 13px;
          line-height: 1;
          cursor: pointer;
          transition: all 0.15s;
        }
        .diff-card-close:hover {
          background: #fdecea;
          color: #d54941;
        }

        /* ---- KPI ---- */
        .diff-card-summary {
          display: flex;
          align-items: baseline;
          gap: 12px;
          padding: 12px 14px 10px;
        }
        .diff-card-kpi {
          display: flex;
          flex-direction: column;
          gap: 1px;
        }
        .diff-card-kpi-val {
          font-size: 24px;
          font-weight: 700;
          line-height: 1.1;
          color: var(--brand-color, #1a55e8);
          font-variant-numeric: tabular-nums;
        }
        .diff-card-kpi-unit {
          font-size: 13px;
          font-weight: 500;
          margin-left: 1px;
        }
        .diff-card-kpi-label {
          font-size: 11px;
          color: var(--text-tertiary, #8c8c8c);
        }
        .diff-card-gap {
          font-size: 12px;
          font-weight: 600;
          padding: 2px 8px;
          border-radius: 10px;
          white-space: nowrap;
        }
        .diff-card-gap.is-up {
          background: #fdecea;
          color: #d54941;
        }
        .diff-card-gap.is-down {
          background: #e6f4ea;
          color: #16a34a;
        }

        /* ---- 表格 ---- */
        .diff-card-table-wrap {
          padding: 0 6px 6px;
          overflow-x: auto;
        }
        .diff-card-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 12px;
        }
        .diff-card-table thead th {
          padding: 6px 8px;
          text-align: left;
          font-weight: 500;
          font-size: 11px;
          color: var(--text-tertiary, #8c8c8c);
          background: #f5f6f8;
          border-bottom: 1px solid #f0f0f0;
          white-space: nowrap;
        }
        .diff-card-table thead th.is-num { text-align: right; }
        .diff-card-table thead th:first-child { border-top-left-radius: 4px; }
        .diff-card-table thead th:last-child { border-top-right-radius: 4px; }
        .diff-card-table tbody td {
          padding: 6px 8px;
          border-bottom: 1px solid #f5f6f8;
          color: var(--text-secondary, #4f4f4f);
          white-space: nowrap;
        }
        .diff-card-table tbody tr:last-child td { border-bottom: none; }
        .diff-card-table tbody tr:hover td { background: #f5f6f8; }
        .diff-td-model {
          display: flex;
          align-items: center;
          gap: 6px;
          font-weight: 500;
          color: var(--text-primary, #1f1f1f);
        }
        .diff-td-num {
          text-align: right;
          font-variant-numeric: tabular-nums;
        }
        .diff-td-overall {
          font-weight: 600;
          color: var(--text-primary, #1f1f1f);
        }
        .diff-td-gap.is-up { color: #d54941; font-weight: 600; }
        .diff-td-gap.is-down { color: #16a34a; font-weight: 600; }
        .diff-td-dev { width: 108px; }
        .diff-dev-bar {
          display: inline-block;
          vertical-align: middle;
          width: 34px;
          height: 5px;
          margin-right: 6px;
          border-radius: 3px;
          background: #f0f0f0;
          position: relative;
        }
        .diff-dev-bar::after {
          content: '';
          position: absolute;
          top: -2px;
          left: 50%;
          width: 2px;
          height: 9px;
          border-radius: 1px;
          background: #1a55e8;
          transform: translateX(calc(var(--dev, 0) * 15px - 1px));
        }
        .diff-dev-txt {
          font-size: 11px;
          color: var(--text-tertiary, #8c8c8c);
          font-variant-numeric: tabular-nums;
        }
        .diff-td-empty {
          text-align: center;
          padding: 20px 8px !important;
          color: var(--text-tertiary, #8c8c8c) !important;
        }

        /* 共用:模型色点 —— 沿用 NewProjectWizard / QuestionTab 同款尺寸 */
        .model-dot {
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          flex-shrink: 0;
        }
      `}</style>
    </div>
  );
}

/** 顶部说明条:日期窗口 + 模型数 + 问题数,跟 toolbar 实时联动。 */
function buildNoteText(
  range: { days?: number; start?: string; end?: string } | null,
  models: string[] | null,
  prompts: number[] | null,
): string {
  const datePart = rangeLabel(range);
  const modelPart = models == null
    ? "全部模型"
    : models.length === 0
      ? "模型 0 个"
      : `模型 ${models.length} 个`;
  const promptPart = prompts == null
    ? "全部问题"
    : prompts.length === 0
      ? "问题 0 个"
      : `问题 ${prompts.length} 个`;
  return `${datePart} · ${modelPart} · ${promptPart}`;
}

function rangeLabel(range: { days?: number; start?: string; end?: string } | null): string {
  if (!range) return "默认窗口";
  if (range.days != null) return `近 ${range.days} 天`;
  if (range.start && range.end) return `${range.start} ~ ${range.end}`;
  return "默认窗口";
}
