/**
 * 「AI 回答原始内容」sub-pane ——
 * 严格参照 docs/风球GEO监控平台UI/index.html:1733-1782 + layout.css:1417-1593
 * 的 `.answer-merged-*` / `.hitrate-*` / `.rank-*` 样式。
 *
 * 结构对照:
 * - 左 1fr / 右 480px 两栏(grid 间距 16px)
 * - 左:一张大白卡(shadow-card / radius-lg),header + 可滚动 list
 *   - header h3「各模型 AI 回答原文」+ p「命中关键词已高亮,支持上下滚动...」
 *   - 每条 item:padding 20/24,border-bottom:last-child 去掉;header 模型名
 *     (彩点 + 文本)左对齐 + 日期右对齐;body 内容含 <span class="hl-...">;
 *     footer dashed 上边线,gap 16px,字号 xs,色 tertiary
 *   - 整个 list max-height = calc(100vh - 280px),overflow-y auto
 * - 右:hitrate panel + rank panel + brand-legend,全部圆角 9px,
 *   bg container,border-color 边;rank panel header 带 135° 蓝橙渐变
 *   浅色;brand-legend swatch 18×14 圆角 3px
 *
 * 数据真源:
 * - 回答列表:`GET /projects/{id}/prompts/{pid}/answers`,前端去重到
 *   「每个平台最新一条」
 * - 排名 / 图例:`GET /projects/{id}/questions/{pid}/competitor-analytics`
 *
 * 整体排名算法:mention_rate × 0.6 + (1 - avg_rank/10) × 0.4,avg_rank 缺
 * 失则降级用 mention_rate 自身。
 */

import { useEffect, useMemo, useState } from "react";
import { Empty, Skeleton, message } from "antd";
import dayjs from "dayjs";
import {
  getQuestionCompetitorAnalytics,
  listPromptAnswers,
  type CompetitorBrandStat,
  type CompetitorOut,
  type PromptAnswerOut,
  type ProjectDetailOut,
} from "../../../api/projects";
import { compoundKeyFor, modelNameFor, parseOverviewKey, platformLabel } from "../platforms";
import { useToolbarFilter } from "../../../components/ToolbarFilterContext";
import { buildHighlightGroups, renderAnswerHtml } from "../../../utils/answerHtml";

interface Props {
  projectId: number;
  promptId: number;
  project: ProjectDetailOut;
  competitors: CompetitorOut[];
  /** 切到 detail sub-tab 并预选某个模型 */
  onJumpToDetail: (subtaskId: string) => void;
}

function rankBucket(rank: number | null): "Top1" | "Top1-3" | "Top3-10" | "Top10+" | "—" {
  if (rank === null || rank === undefined) return "—";
  if (rank < 1) return "Top1";
  if (rank < 3) return "Top1-3";
  if (rank < 10) return "Top3-10";
  return "Top10+";
}

function bucketClass(b: ReturnType<typeof rankBucket>): string {
  switch (b) {
    case "Top1": return "hitrate-high";
    case "Top1-3": return "hitrate-mid";
    case "Top3-10": return "hitrate-low";
    default: return "";
  }
}

function compositeScore(b: CompetitorBrandStat): number {
  const mr = b.mention_rate;
  const ar = b.avg_rank;
  if (ar === null) return mr;
  const rankNorm = Math.max(0, 1 - ar / 10);
  return mr * 0.6 + rankNorm * 0.4;
}

export default function RawAnswersPane({
  projectId, promptId, project, competitors, onJumpToDetail,
}: Props) {
  const toolbar = useToolbarFilter();
  const dateQuery = toolbar.selectedDateRange ?? { days: 15 };
  const dateKey = useMemo(() => JSON.stringify(dateQuery), [dateQuery]);
  const modelsKey = useMemo(
    () => (toolbar.selectedModels ? [...toolbar.selectedModels].sort().join("|") : "all"),
    [toolbar.selectedModels],
  );

  const [answers, setAnswers] = useState<PromptAnswerOut[]>([]);
  const [answersLoading, setAnswersLoading] = useState(true);
  const [brands, setBrands] = useState<CompetitorBrandStat[]>([]);
  const [brandsLoading, setBrandsLoading] = useState(true);
  const [platforms, setPlatforms] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    setAnswersLoading(true);
    listPromptAnswers(projectId, promptId, {
      days: dateQuery.days,
      start: dateQuery.start,
      end: dateQuery.end,
      platforms: toolbar.selectedModels ?? undefined,
      preview_chars: 200,
    })
      .then((d) => {
        if (cancelled) return;
        setAnswers(d.items);
      })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "AI 回答加载失败");
      })
      .finally(() => {
        if (!cancelled) setAnswersLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, promptId, dateKey, modelsKey, toolbar.version]);

  useEffect(() => {
    let cancelled = false;
    setBrandsLoading(true);
    getQuestionCompetitorAnalytics(projectId, promptId, {
      days: dateQuery.days,
      start: dateQuery.start,
      end: dateQuery.end,
    })
      .then((d) => {
        if (cancelled) return;
        setBrands(d.brands);
        const ps = new Set<string>();
        d.brands.forEach((b) => Object.keys(b.model_ranks || {}).forEach((p) => ps.add(p)));
        const ordered = [...ps].sort((a, b) => {
          const ia = project.platforms.findIndex((pp) => pp.platform === a || pp.platform_code === a);
          const ib = project.platforms.findIndex((pp) => pp.platform === b || pp.platform_code === b);
          return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
        });
        setPlatforms(ordered);
      })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "竞品分析加载失败");
      })
      .finally(() => {
        if (!cancelled) setBrandsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, promptId, dateKey, modelsKey, toolbar.version]);

  const selfBrand = project.brand ?? null;
  const groups = useMemo(
    () =>
      buildHighlightGroups({
        selfBrand: project.brand,
        selfAliases: project.aliases,
        competitors: competitors.map((c) => ({ name: c.name, aliases: c.aliases })),
        keywords: project.keywords,
      }),
    [project, competitors],
  );

  // 全量回答按时间倒序 —— 同一平台多次执行也全部展示,不折叠到「最新一条」。
  // 顶部「各模型 AI 回答原文」语义就是该 prompt × 当前过滤条件下所有 AI
  // 跑出来的回答原文,折叠会让用户看不到历史快照(同平台跨时间的变化
  // 看不到,排查「为什么这次回答不一样」时没历史对照)。list 已经
  // max-height + overflow-y auto,长列表靠滚动。
  const sortedAnswers = useMemo(() => {
    return [...answers].sort((a, b) => {
      const ta = a.created_local_at ? dayjs(a.created_local_at).valueOf() : 0;
      const tb = b.created_local_at ? dayjs(b.created_local_at).valueOf() : 0;
      return tb - ta;
    });
  }, [answers]);

  const sortedBrands = useMemo(
    () => [...brands].sort((a, b) => compositeScore(b) - compositeScore(a)),
    [brands],
  );

  const loading = answersLoading && brandsLoading && sortedAnswers.length === 0 && brands.length === 0;
  if (loading) return <Skeleton active paragraph={{ rows: 8 }} />;

  return (
    <div className="answer-merged-layout">
      {/* ===== 左侧：所有模型回答合并滚动 ===== */}
      <div className="answer-merged-left">
        <div className="answer-merged-header">
          <h3>各模型 AI 回答原文</h3>
          <p>命中关键词已高亮标注，支持上下滚动浏览全部模型回答</p>
        </div>
        <div className="answer-merged-list" id="answer-merged-list">
          {sortedAnswers.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center" }}>
              <Empty description="该问题在当前窗口内暂无 AI 回答" />
            </div>
          ) : (
            sortedAnswers.map((a) => (
              <AnswerMergedItem
                key={a.subtask_id}
                ans={a}
                html={a.answer_content ? renderAnswerHtml(a.answer_content, groups) : ""}
                selfBrand={selfBrand}
                onOpenDetail={() => onJumpToDetail(a.subtask_id)}
              />
            ))
          )}
        </div>
      </div>

      {/* ===== 右侧：关心内容命中率 + 整体排名 + 品牌高亮图例 ===== */}
      <div className="answer-merged-right">
        {/* hitrate panel */}
        <div className="hitrate-panel">
          <div className="hitrate-header">
            <h3>关心内容命中率</h3>
            <p>每行 = 1 个品牌，cell = 该模型回答中的 Top 名次</p>
          </div>
          <div className="hitrate-table-wrap">
            {brandsLoading ? (
              <Skeleton active paragraph={{ rows: 4 }} />
            ) : brands.length === 0 || platforms.length === 0 ? (
              <Empty
                description="暂无竞品排名数据"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            ) : (
              <table className="hitrate-table">
                <thead>
                  <tr>
                    <th>品牌</th>
                    {platforms.map((p) => (
                      <th key={p} title={p}>{platformLabel(p)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {brands.map((b) => (
                    <tr key={b.brand}>
                      <td>
                        <span
                          className="brand-legend-swatch"
                          style={{ background: b.color, marginRight: 6 }}
                        />
                        {b.brand}
                        {b.is_self && <span className="brand-legend-tag">自身</span>}
                      </td>
                      {platforms.map((p) => {
                        const rank = b.model_ranks?.[p] ?? null;
                        const bucket = rankBucket(rank);
                        return (
                          <td key={p}>
                            <span className={`hitrate-cell ${bucketClass(bucket)}`}>
                              {rank === null || rank === undefined ? "—" : `No.${rank}`}
                            </span>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* rank panel —— 整体排名表格,4 列:品牌 / 提及率 / Top1 / 均位;
           表头淡灰底,数据行斑马纹,自身行蓝底高亮,数字列右对齐 + 品牌蓝
           加粗,Top1-3 用奖牌色编号,4+ 走灰色数字编号。 */}
        <div className="rank-panel">
          <div className="rank-panel-header">
            <h3>整体排名</h3>
            <p>系统按「Top1 提及率 × 权重 + 平均排名」综合排序</p>
          </div>
          {brandsLoading ? (
            <div className="rank-panel-body">
              <Skeleton active paragraph={{ rows: 3 }} />
            </div>
          ) : sortedBrands.length === 0 ? (
            <div className="rank-panel-body">
              <Empty
                description="暂无排名数据"
                image={Empty.PRESENTED_IMAGE_SIMPLE}
              />
            </div>
          ) : (
            <div className="rank-list">
              <div className="rank-list-header">
                <span className="rank-h-num">#</span>
                <span />
                <span>品牌</span>
                <span className="rank-h-num">提及率</span>
                <span className="rank-h-num">Top1</span>
                <span className="rank-h-num">均位</span>
              </div>
              {sortedBrands.map((b, idx) => {
                const medal = idx === 0 ? "🥇" : idx === 1 ? "🥈" : idx === 2 ? "🥉" : null;
                return (
                  <div
                    key={b.brand}
                    className={`rank-row${b.is_self ? " rank-row-self" : ""}`}
                  >
                    <span className="rank-num">{medal ?? idx + 1}</span>
                    <span className="rank-swatch" style={{ background: b.color }} />
                    <span className="rank-brand-name">
                      {b.brand}
                      {b.is_self && <span className="rank-self-tag">自身</span>}
                    </span>
                    <span className="rank-metric">{(b.mention_rate * 100).toFixed(1)}%</span>
                    <span className="rank-metric">{(b.top1_rate * 100).toFixed(1)}%</span>
                    <span className="rank-metric">
                      {b.avg_rank === null ? "—" : `No.${b.avg_rank.toFixed(1)}`}
                    </span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      <style>{`
        /* ===== 严格对照 index.html layout.css ===== */
        .answer-merged-layout {
          display: grid;
          grid-template-columns: 1fr 480px;
          gap: 16px;
          /* stretch 让右列与左列等高 —— 右侧 hitrate + rank 才能配合
             flex:1 把 rank 撑满左列剩余高度。 */
          align-items: stretch;
        }
        .answer-merged-left {
          background: white;
          border-radius: var(--radius-lg, 9px);
          box-shadow: var(--shadow-card, 0 1px 4px rgba(0,0,0,0.06));
          overflow: hidden;
        }
        .answer-merged-header {
          padding: 18px 24px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .answer-merged-header h3 {
          font-size: var(--fs-md, 16px);
          font-weight: 600;
          margin: 0 0 4px;
          color: var(--text-primary, rgba(0,0,0,0.88));
        }
        .answer-merged-header p {
          font-size: var(--fs-xs, 12px);
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          margin: 0;
        }
        .answer-merged-list {
          max-height: calc(100vh - 280px);
          overflow-y: auto;
        }

        /* ===== item 卡片 ===== */
        .answer-merged-item {
          padding: 20px 24px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .answer-merged-item:last-child { border-bottom: none; }
        .answer-merged-item-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          margin-bottom: 12px;
        }
        .answer-merged-item-model {
          display: flex;
          align-items: center;
          gap: 8px;
          font-weight: 600;
          font-size: var(--fs-sm, 14px);
          color: var(--text-primary, rgba(0,0,0,0.88));
        }
        .answer-merged-item-model .model-dot {
          width: 12px;
          height: 12px;
          border-radius: 50%;
          flex-shrink: 0;
        }
        .answer-merged-item-date {
          font-size: var(--fs-xs, 12px);
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          font-variant-numeric: tabular-nums;
        }
        .answer-merged-item-body {
          font-size: 13px;
          line-height: 1.7;
          color: var(--text-primary, rgba(0,0,0,0.88));
        }
        .answer-merged-item-body p { margin: 0 0 8px; }
        .answer-merged-item-body p:last-child { margin-bottom: 0; }
        /* Markdown 标题强制收敛到 body 字号的 1.0~1.15 倍 —— 不让浏览器默认
           的 h1=2em / h2=1.5em 在 13px body 里爆出大字号,把答案页面撑得
           参差不齐。LLM 经常返回 ## xxx / ### xxx 这种小节标题,视觉上
           应该是「略大 + 加粗」,不是「明显大一号」。 */
        .answer-merged-item-body h1 {
          font-size: 14px; margin: 12px 0 4px; font-weight: 600;
          line-height: 1.5;
        }
        .answer-merged-item-body h2 {
          font-size: 13px; margin: 10px 0 4px; font-weight: 600;
          line-height: 1.5;
        }
        .answer-merged-item-body h3,
        .answer-merged-item-body h4,
        .answer-merged-item-body h5,
        .answer-merged-item-body h6 {
          font-size: 13px; margin: 8px 0 4px; font-weight: 600;
          line-height: 1.5;
        }
        .answer-merged-item-body strong { font-weight: 600; }
        .answer-merged-item-body ul,
        .answer-merged-item-body ol {
          padding-left: 22px;
          margin: 4px 0 8px;
        }
        .answer-merged-item-body li { margin: 2px 0; }
        .answer-merged-item-body code {
          background: var(--bg-page, #fafafa);
          padding: 1px 6px;
          border-radius: 3px;
          font-size: 12px;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        .answer-merged-item-body pre {
          background: var(--bg-page, #fafafa);
          padding: 10px 12px;
          border-radius: 6px;
          font-size: 12px;
          overflow-x: auto;
        }
        .answer-merged-item-body blockquote {
          margin: 8px 0;
          padding: 4px 12px;
          border-left: 3px solid var(--brand-blue, #1a55e8);
          background: var(--bg-page, #fafafa);
          color: var(--text-secondary);
        }
        .answer-merged-item-body table {
          border-collapse: collapse;
          margin: 8px 0;
          font-size: 12px;
        }
        .answer-merged-item-body th,
        .answer-merged-item-body td {
          border: 1px solid var(--border-light, #e5e7eb);
          padding: 6px 10px;
        }
        .answer-merged-item-body mark,
        .answer-merged-item-body .hl-self,
        .answer-merged-item-body .hl-competitor,
        .answer-merged-item-body .hl-keyword {
          background: rgba(255, 107, 26, 0.2);
          color: var(--brand-orange-dark, #d8540f);
          padding: 0 3px;
          border-radius: 3px;
          font-weight: 500;
        }
        .answer-merged-item-footer {
          margin-top: 12px;
          padding-top: 8px;
          border-top: 1px dashed var(--border-light, #f0f0f0);
          display: flex;
          gap: 16px;
          font-size: var(--fs-xs, 12px);
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          align-items: center;
        }
        .answer-merged-item-footer .ra-card-detail-btn {
          margin-left: auto;
          background: transparent;
          border: 1px solid var(--border-light, #e5e7eb);
          border-radius: 4px;
          padding: 2px 10px;
          font-size: var(--fs-xs, 12px);
          color: var(--brand-blue, #1a55e8);
          cursor: pointer;
          font-family: inherit;
        }
        .answer-merged-item-footer .ra-card-detail-btn:hover {
          background: var(--bg-hover, #f0f4ff);
        }
        /* 本答案品牌位次(全品牌列表) —— 按 index.html 截图直接平铺
           「本答案品牌位次  #1 薇诺娜 自身  #2 珂润  #3 玉泽  ...」,
           每项一个 .answer-rank-item 横向排列;自有品牌(self)额外挂
           蓝底「自身」徽章 + 圆角胶囊高亮;Top1-3 奖牌色 .rank-pill.rank-N
           与整体排名面板配色一致。 */
        .answer-rankings-row {
          display: flex;
          flex-wrap: wrap;
          gap: 6px 14px;
          align-items: center;
          flex: 1;
          min-width: 0;
        }
        .answer-rankings-label {
          font-size: var(--fs-xs, 12px);
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          margin-right: 2px;
        }
        .answer-rank-item {
          display: inline-flex;
          align-items: center;
          gap: 5px;
          padding: 2px 8px;
          border-radius: 12px;
          background: var(--bg-secondary, #f5f5f5);
        }
        .answer-rank-item.answer-rank-item-self {
          background: rgba(43, 99, 255, 0.1);
          border: 1px solid rgba(43, 99, 255, 0.35);
        }
        .answer-rank-name {
          font-size: var(--fs-xs, 12px);
          color: var(--text-primary, rgba(0,0,0,0.88));
          font-weight: 500;
        }
        .answer-rank-self-tag {
          font-size: 11px;
          color: var(--brand-blue, #1a55e8);
          background: var(--brand-blue-soft, #e6efff);
          padding: 0 6px;
          border-radius: 8px;
          font-weight: 500;
        }
        .rank-pill {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          min-width: 30px;
          height: 18px;
          padding: 0 6px;
          border-radius: 9px;
          font-size: 11px;
          font-weight: 600;
          line-height: 1;
        }
        .rank-pill.rank-1 { background: linear-gradient(135deg, #faad14, #ffc069); color: white; }
        .rank-pill.rank-2 { background: linear-gradient(135deg, #d9d9d9, #f0f0f0); color: #595959; }
        .rank-pill.rank-3 { background: linear-gradient(135deg, #d48806, #e8b339); color: white; }
        .rank-pill.rank-other { background: #fafafa; color: #8c8c8c; border: 1px solid #f0f0f0; }
        /* 情感倾向 tag —— 复用 layout.css .tag-positive / .tag-negative /
           .tag-warn 的三色语义(绿=positive / 红=negative / 黄=warn/neutral) */
        .answer-sentiment-tag {
          display: inline-flex;
          align-items: center;
          gap: 3px;
          padding: 3px 10px;
          border-radius: 12px;
          font-size: var(--fs-xs, 12px);
          font-weight: 500;
        }
        .answer-sentiment-tag.tag-positive {
          background: var(--color-success-light, #e6f7ee);
          color: var(--color-success, #2ba471);
        }
        .answer-sentiment-tag.tag-negative {
          background: var(--color-danger-light, #fff1f0);
          color: var(--color-danger, #d54941);
        }
        .answer-sentiment-tag.tag-warn {
          background: var(--color-warning-light, #fff7e6);
          color: var(--color-warning, #faad14);
        }
        .answer-merged-item-error {
          font-size: var(--fs-sm, 14px);
          color: var(--color-danger, #d54941);
          background: var(--color-danger-light, #fff1f0);
          padding: 8px 10px;
          border-radius: 4px;
        }
        .answer-merged-item-empty {
          font-size: var(--fs-sm, 14px);
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          padding: 12px 0;
        }
        .answer-merged-item-status-failed {
          color: var(--color-danger, #d54941);
          font-weight: 500;
        }

        /* ===== right column panels —— 右列与左列等高,hitrate 自然高,
           rank-panel 用 flex:1 撑满剩余空间。 ===== */
        .answer-merged-right {
          display: flex;
          flex-direction: column;
          gap: 12px;
          min-height: 0;
        }
        .hitrate-panel {
          background: var(--td-bg-color-container, #fff);
          border: 1px solid var(--border-color, #f0f0f0);
          border-radius: var(--radius-lg, 9px);
          overflow: hidden;
          flex-shrink: 0;
        }
        .hitrate-header {
          padding: 12px 14px;
          border-bottom: 1px solid var(--border-color, #f0f0f0);
        }
        .hitrate-header h3 {
          font-size: var(--fs-md, 16px);
          font-weight: 600;
          margin: 0 0 4px;
        }
        .hitrate-header p {
          font-size: var(--fs-xs, 12px);
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          margin: 0;
        }
        .hitrate-table-wrap {
          padding: 8px 14px 14px;
          overflow-x: auto;
        }
        .hitrate-table {
          width: 100%;
          border-collapse: collapse;
          font-size: var(--fs-xs, 12px);
        }
        .hitrate-table th {
          padding: 8px 6px;
          font-weight: 500;
          color: var(--text-secondary, rgba(0,0,0,0.65));
          text-align: center;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          white-space: nowrap;
          max-width: 80px;
          overflow: hidden;
          text-overflow: ellipsis;
        }
        .hitrate-table th:first-child {
          text-align: left;
          max-width: 120px;
        }
        .hitrate-table td {
          padding: 8px 6px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          text-align: center;
          color: var(--text-primary, rgba(0,0,0,0.88));
        }
        .hitrate-table td:first-child {
          text-align: left;
          white-space: nowrap;
          max-width: 130px;
          overflow: hidden;
          text-overflow: ellipsis;
          font-weight: 500;
        }
        .hitrate-cell {
          display: inline-block;
          padding: 2px 8px;
          border-radius: 9px;
          font-variant-numeric: tabular-nums;
          font-weight: 500;
        }
        .hitrate-high { background: var(--color-success-light, #e7f7ed); color: var(--color-success, #2ba471); }
        .hitrate-mid { background: var(--color-warning-light, #fff3e0); color: var(--color-warning, #e37318); }
        .hitrate-low { background: var(--color-danger-light, #fff1f0); color: var(--color-danger, #d54941); }

        /* ===== rank panel —— 4 列简单列表(# / 品牌 / 提及率+Top1+均位)。
           flex:1 + min-height:0 让 panel 撑满右列剩余高度;overflow:hidden
           + .rank-list 的 overflow-y:auto 让品牌行多时走内部滚动,而不是把
           panel 顶出视口。 ===== */
        .rank-panel {
          border: 1px solid var(--border-color, #f0f0f0);
          border-radius: var(--radius-lg, 9px);
          background: var(--td-bg-color-container, #fff);
          overflow: hidden;
          flex: 1;
          min-height: 0;
          display: flex;
          flex-direction: column;
        }
        .rank-panel-header {
          padding: 10px 14px;
          border-bottom: 1px solid var(--border-color, #f0f0f0);
        }
        .rank-panel-header h3 {
          font-size: var(--fs-sm, 14px);
          margin: 0 0 2px;
          font-weight: 600;
        }
        .rank-panel-header p {
          font-size: 11px;
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          margin: 0;
        }
        .rank-panel-body {
          padding: 14px;
        }
        /* .rank-list 是 panel 内部的「表头 + 数据行」容器,flex:1 + 内部滚动
           让 panel 撑满右列高度时,品牌多到溢出也不会顶破 viewport,而是
           在 panel 内滚动。 */
        .rank-list {
          flex: 1;
          min-height: 0;
          overflow-y: auto;
        }
        /* 表头 + 数据行统一走 6 列 grid:# / 色块 / 品牌名 / 提及率 / Top1 / 均位 */
        .rank-list-header,
        .rank-row {
          display: grid;
          grid-template-columns: 24px 14px 1fr 64px 64px 64px;
          align-items: center;
          gap: 8px;
          padding: 8px 14px;
        }
        .rank-list-header {
          font-size: 11px;
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          background: var(--bg-secondary, #fafafa);
          border-bottom: 1px solid var(--border-color, #f0f0f0);
        }
        .rank-list-header .rank-h-num {
          text-align: right;
        }
        .rank-row {
          font-size: 13px;
          border-bottom: 1px dashed var(--border-color, #f0f0f0);
        }
        .rank-row:last-child {
          border-bottom: none;
        }
        /* 自身品牌行:整行淡蓝底,与其它行拉开层次,不引入斑马纹/Top1 高亮。 */
        .rank-row.rank-row-self {
          background: rgba(26, 85, 232, 0.06);
        }
        .rank-num {
          text-align: right;
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary, rgba(0,0,0,0.88));
        }
        .rank-swatch {
          width: 12px;
          height: 12px;
          border-radius: 3px;
          flex-shrink: 0;
          display: inline-block;
        }
        .rank-brand-name {
          font-weight: 500;
          color: var(--text-primary, rgba(0,0,0,0.88));
          display: inline-flex;
          align-items: center;
          gap: 6px;
          min-width: 0;
        }
        .rank-self-tag {
          font-size: 11px;
          color: var(--brand-blue, #1a55e8);
          background: rgba(26, 85, 232, 0.1);
          padding: 0 6px;
          border-radius: 8px;
          font-weight: 500;
          line-height: 16px;
          flex-shrink: 0;
        }
        .rank-metric {
          text-align: right;
          color: var(--brand-blue, #1a55e8);
          font-weight: 600;
          font-variant-numeric: tabular-nums;
          font-size: 13px;
        }

        /* ===== 工具类:仍被 hitrate panel 复用的 swatch + 自身 tag ===== */
        .brand-legend-swatch {
          width: 12px;
          height: 12px;
          border-radius: 3px;
          flex-shrink: 0;
          display: inline-block;
        }
        .brand-legend-tag {
          font-size: 11px;
          color: var(--brand-blue, #1a55e8);
          background: rgba(26, 85, 232, 0.1);
          padding: 0 6px;
          border-radius: 8px;
          font-weight: 500;
          line-height: 16px;
          margin-left: 6px;
          vertical-align: middle;
        }
      `}</style>
    </div>
  );
}

interface AnswerMergedItemProps {
  ans: PromptAnswerOut;
  html: string;
  /** 项目自有品牌名(``project.brand``)—— 用于在排名列表里给自身一行挂
   *  「自身」徽章 + Top 颜色高亮。无 brand 时按字符串相等不做高亮。 */
  selfBrand: string | null;
  onOpenDetail: () => void;
}

function AnswerMergedItem({ ans, html, selfBrand, onOpenDetail }: AnswerMergedItemProps) {
  const failed = ans.status && /failed|error|stopped/i.test(ans.status);
  const dotColor =
    ans.status === "success"
      ? "var(--color-success, #2ba471)"
      : failed
        ? "var(--color-danger, #d54941)"
        : "var(--text-tertiary, #9ca3af)";
  // 模型名 + 终端 chip + 模式 chip —— 与工具栏 dropdown 卡片完全一致
  // (复用 .gt-model-dot / .gt-model-delivery / .gt-model-thinking CSS,样式在
  // AppLayout.css 全局可见)。compoundKeyFor 拆出 delivery / thinking 维度。
  // 头部文本只显示模型名(千问),终端 / 模式由 chip 承担 —— 避免「千问-网页-快速 网页版 快速」
  // 重复两遍后缀的视觉冗余。
  const compound = parseOverviewKey(compoundKeyFor(ans.platform, ans.mode));
  const name = modelNameFor(ans.platform, ans.mode);
  return (
    <div className="answer-merged-item">
      <div className="answer-merged-item-header">
        <div className="answer-merged-item-model">
          <span className="model-dot" style={{ background: dotColor }} />
          <span>{name}</span>
          {compound && (
            <>
              <span
                className="gt-model-delivery"
                data-delivery={compound.delivery}
              >
                {compound.delivery === "mobile" ? "移动版" : "网页版"}
              </span>
              <span
                className="gt-model-thinking"
                data-thinking={compound.thinking}
              >
                {compound.thinking === "think" ? "思考" : "快速"}
              </span>
            </>
          )}
        </div>
        <span className="answer-merged-item-date">
          {ans.created_local_at
            ? dayjs(ans.created_local_at).format("YYYY-MM-DD HH:mm")
            : ""}
        </span>
      </div>

      {ans.error_message ? (
        <div className="answer-merged-item-error">{ans.error_message}</div>
      ) : html ? (
        <div
          className="answer-merged-item-body"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      ) : (
        <div className="answer-merged-item-empty">(此回答无文本内容)</div>
      )}

      <div className="answer-merged-item-footer">
        {/* 情感倾向 tag(取自 LLM 抽取返回的 polarity,见
            BrandMention.sentiment)。positive=绿 / negative=红 / 中性或缺失
            不渲染,避免给空数据画一个误导性徽章。 */}
        {ans.self_sentiment === "positive" && (
          <span className="answer-sentiment-tag tag-positive">
            情感倾向 · 正面
          </span>
        )}
        {ans.self_sentiment === "negative" && (
          <span className="answer-sentiment-tag tag-negative">
            情感倾向 · 负面
          </span>
        )}
        {ans.self_sentiment === "neutral" && (
          <span className="answer-sentiment-tag tag-warn">
            情感倾向 · 中性
          </span>
        )}
        {/* 本答案品牌位次 —— 直接按 LLM ``allRankings`` 顺序展开完整列表,
            每项 ``#N 品牌名``,Top1-3 用奖牌色高亮;项目自有品牌(selfBrand)
            所在那一行额外挂一个「自身」蓝徽章。无 allRankings 数据时不渲染
            整块(后端 _extract_all_rankings 已经过滤脏数据)。 */}
        {ans.all_rankings && ans.all_rankings.length > 0 && (
          <span className="answer-rankings-row">
            <span className="answer-rankings-label">本答案品牌位次</span>
            {ans.all_rankings.map((r) => {
              const isSelf = !!selfBrand && r.name === selfBrand;
              const rankCls =
                r.rank === 1
                  ? "rank-pill rank-1"
                  : r.rank === 2
                    ? "rank-pill rank-2"
                    : r.rank === 3
                      ? "rank-pill rank-3"
                      : "rank-pill rank-other";
              return (
                <span
                  key={`${r.rank}-${r.name}`}
                  className={`answer-rank-item${isSelf ? " answer-rank-item-self" : ""}`}
                >
                  <span className={rankCls}>#{r.rank}</span>
                  <span className="answer-rank-name">{r.name}</span>
                  {isSelf && <span className="answer-rank-self-tag">自身</span>}
                </span>
              );
            })}
          </span>
        )}
        {/* 失败状态保留显示(给操作员一个明显的失败信号);``success`` /
            ``completed`` / ``pending`` 等噪声状态不再展示,避免「本答案品牌
            位次」和成功二字挤在同一行干扰阅读。 */}
        {failed && (
          <span className="answer-merged-item-status-failed">{ans.status}</span>
        )}
        <button type="button" className="ra-card-detail-btn" onClick={onOpenDetail}>
          查看详情
        </button>
      </div>
    </div>
  );
}
