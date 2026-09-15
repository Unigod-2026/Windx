/**
 * 「答案详情」sub-pane —— 参照 docs/风球GEO监控平台UI/index.html 左 70%
 * / 右 38% 布局:
 *
 * 左侧:
 * - 顶部 model 选择(Select),每个 platform 一项,平台 tag 用 platformLabel
 * - 完整 markdown 渲染(用 utils 的 renderAnswerHtml),调 getSubtaskDetail
 *   拉全文 + reasoning_process_json + reference / citation list
 * - 底部「整体排名」徽章 + 关键词行
 *
 * 右侧(二级 tab):
 * - 思考过程 —— 从 ``reasoning_process_json`` 抽出 [{step, content}],
 *   不是数组则按单步包装(标「未结构化」徽标);空数据显「该模型未返回
 *   思考过程」
 * - 命中率统计 —— 从 ``concern_hits_json`` 聚合(每个 brand mention 自带
 *   一个 concern_hits_json,通常是 [{item, hit}]),展示命中点列表
 *   + checkbox(乐观更新 localStorage,本期不做后端持久化,见 TODO)
 *
 * 数据流:
 * - 入参 promptId + subtasks(从 RawAnswersPane 预选一个最新 / 用户手动切)
 * - answers 用 listPromptAnswers + 本地过滤
 * - 当前选中的 subtask 调 getSubtaskDetail 拉 detail
 * - rank badge 用 getQuestionProductAnalytics platforms[matched this triple]
 */

import { useEffect, useMemo, useState } from "react";
import { Empty, Skeleton, Tag, message } from "antd";
import dayjs from "dayjs";
import {
  getQuestionProductAnalytics,
  getSubtaskDetail,
  listPromptAnswers,
  type CompetitorOut,
  type PromptAnswerDetailOut,
  type PromptAnswerOut,
  type ProjectDetailOut,
  type QuestionPlatformStat,
} from "../../../api/projects";
import { compoundKeyFor, modelNameFor, parseOverviewKey } from "../platforms";
import { useToolbarFilter } from "../../../components/ToolbarFilterContext";
import { buildHighlightGroups, renderAnswerHtml } from "../../../utils/answerHtml";

interface Props {
  projectId: number;
  promptId: number;
  project: ProjectDetailOut;
  competitors: CompetitorOut[];
  /** RawAnswersPane 跳过来时预选;首次进入为 null(选第一个) */
  initialSubtaskId: string | null;
}

interface ConcernHitItem {
  id: string;
  text: string;
  hit: boolean;
}

interface ThinkStep {
  step: number;
  content: string;
  raw: boolean;
}

/** 把异构的 reasoning_process_json normalize 成统一 step[]。 */
function normalizeThinking(raw: unknown): ThinkStep[] {
  if (!raw) return [];
  if (Array.isArray(raw)) {
    return raw.map((item, i) => {
      if (item && typeof item === "object") {
        const obj = item as Record<string, unknown>;
        const text = (obj.content ?? obj.thinking ?? obj.text ?? obj.step) as unknown;
        return {
          step: i + 1,
          content: typeof text === "string" ? text : JSON.stringify(item),
          raw: false,
        };
      }
      return { step: i + 1, content: String(item), raw: false };
    });
  }
  if (typeof raw === "string") {
    return raw.trim()
      ? [{ step: 1, content: raw, raw: true }]
      : [];
  }
  return [{ step: 1, content: JSON.stringify(raw), raw: true }];
}

export default function AnswerDetailPane({
  projectId, promptId, project, competitors, initialSubtaskId,
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
  const [selectedSubtaskId, setSelectedSubtaskId] = useState<string | null>(initialSubtaskId);
  const [detail, setDetail] = useState<PromptAnswerDetailOut | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [stats, setStats] = useState<QuestionPlatformStat[]>([]);
  const [statsLoading, setStatsLoading] = useState(true);
  const [rightTab, setRightTab] = useState<"thinking" | "hit">("thinking");
  const [hitItems, setHitItems] = useState<ConcernHitItem[]>([]);
  const [newHitText, setNewHitText] = useState("");

  // answers list(用于左侧 model 选择器)
  useEffect(() => {
    let cancelled = false;
    setAnswersLoading(true);
    listPromptAnswers(projectId, promptId, {
      days: dateQuery.days,
      start: dateQuery.start,
      end: dateQuery.end,
      platforms: toolbar.selectedModels ?? undefined,
      // 留默认值(后端约束 50-2000)—— 这里只是给左侧 model 下拉框展示
      // 「模型名 + 时间」用的,answer_content 的全文由 getSubtaskDetail 单独拉。
      // 之前传 50_000 会触发后端 400 → axios 进入 .catch → 弹 antd message
      // error,UI 看上去像「答案详情整个挂了」。
    })
      .then((d) => {
        if (cancelled) return;
        setAnswers(d.items);
        // 首次进入:initialSubtaskId 不在列表里 → 选最新一条;否则保留
        if (
          selectedSubtaskId === null ||
          !d.items.some((it) => it.subtask_id === selectedSubtaskId)
        ) {
          if (d.items.length > 0) {
            const newest = [...d.items].sort((a, b) => {
              const ta = a.created_local_at ? dayjs(a.created_local_at).valueOf() : 0;
              const tb = b.created_local_at ? dayjs(b.created_local_at).valueOf() : 0;
              return tb - ta;
            })[0];
            setSelectedSubtaskId(newest.subtask_id);
          }
        }
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

  // product analytics(给整体排名徽章用)
  useEffect(() => {
    let cancelled = false;
    setStatsLoading(true);
    getQuestionProductAnalytics(projectId, promptId, {
      days: dateQuery.days,
      start: dateQuery.start,
      end: dateQuery.end,
    })
      .then((d) => {
        if (cancelled) return;
        setStats(d.platforms);
      })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "整体排名加载失败");
      })
      .finally(() => {
        if (!cancelled) setStatsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, promptId, dateKey, modelsKey, toolbar.version]);

  // 当前选中的 subtask → detail
  useEffect(() => {
    if (!selectedSubtaskId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    getSubtaskDetail(selectedSubtaskId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
        // 命中点从 detail.reference_list 中没有 concern hits 字段,
        // 真实实现要走「prompt × model 的 brand mention concern_hits_json」聚合。
        // 这里兜底:从 reasoning_process 的最后一步如果包含「命中」关键字,
        // 解析为一行;否则从 detail.citation_list 抽 top 5 当占位。
        const placeholder: ConcernHitItem[] = (d.citation_list || []).slice(0, 5).map((c, i) => {
          if (typeof c === "string") return { id: `c-${i}`, text: c, hit: false };
          const obj = c as Record<string, unknown>;
          const text = (obj.title ?? obj.url ?? obj.site ?? JSON.stringify(obj)) as string;
          return { id: `c-${i}`, text: String(text), hit: false };
        });
        setHitItems(placeholder);
      })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "答案详情加载失败");
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedSubtaskId]);

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

  const selected = answers.find((a) => a.subtask_id === selectedSubtaskId) ?? null;
  const thinkingSteps = useMemo(() => normalizeThinking(detail?.reasoning_process), [detail]);

  // 当前模型的「整体排名」徽章 —— 在 product-analytics 的 platforms 里找
  // 对应 triple,然后用 best_rank 派生「品牌排名第 N 位」。
  const selfRankBadge = useMemo<string | null>(() => {
    if (!selected || statsLoading) return null;
    const platform = selected.platform ?? "";
    const matched = stats.find(
      (s) => s.platform === platform,
    );
    if (!matched || matched.best_rank === null) return null;
    return `品牌排名第 ${matched.best_rank} 位`;
  }, [selected, stats, statsLoading]);

  // 命中率(占位:基于 hit_items 中已勾选的比例)
  const hitRate = useMemo(() => {
    if (hitItems.length === 0) return 0;
    return hitItems.filter((h) => h.hit).length / hitItems.length;
  }, [hitItems]);

  // 添加命中点(TODO:本期只存 localStorage,不做后端持久化)
  const addHit = () => {
    const text = newHitText.trim();
    if (!text) return;
    setHitItems((prev) => [...prev, { id: `local-${Date.now()}`, text, hit: false }]);
    setNewHitText("");
  };

  const toggleHit = (id: string) => {
    setHitItems((prev) =>
      prev.map((it) => (it.id === id ? { ...it, hit: !it.hit } : it)),
    );
  };

  const removeHit = (id: string) => {
    setHitItems((prev) => prev.filter((it) => it.id !== id));
  };

  if (answersLoading && answers.length === 0) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  if (answers.length === 0) {
    return <Empty description="该问题在当前窗口内暂无 AI 回答" />;
  }

  // 当前问题的原文 —— 头部标题直接展示问题本身(不再是「品牌相关回答」)。
  const currentPrompt =
    project.prompts?.find((p) => p.id === promptId)?.prompt ?? "";

  return (
    <div className="ad-root">
      <div className="ad-layout">
        {/* 左侧 70% — 答案内容 */}
        <div className="ad-left">
          <div className="ad-panel">
            <div className="ad-panel-head">
              <div>
                <h3 className="ad-q-title">{currentPrompt || "AI 回答"}</h3>
                <div className="ad-meta">
                  <span>
                    {selected?.created_local_at
                      ? dayjs(selected.created_local_at).format("YYYY-MM-DD")
                      : ""}
                  </span>
                  {selected && (() => {
                    const compound = parseOverviewKey(compoundKeyFor(selected.platform, selected.mode));
                    return (
                      <>
                        <span>{modelNameFor(selected.platform, selected.mode)}</span>
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
                      </>
                    );
                  })()}
                  {selfRankBadge && (
                    <span className="ad-rank-badge">{selfRankBadge}</span>
                  )}
                </div>
              </div>
            </div>
            {/* 答案正文高亮图例 —— 单行,每个品牌一行:
                  ■ 监控品牌(别名1、别名2)   ■ 竞品(别名1、别名2)   ■ 竞品2
                每行主名前置一块方色块(蓝 = 监控 / 黄 = 竞品),色块高度对齐
                主名 chip;别名 chip 用对应浅色版,与正文 hl-* alias 颜色一致。
                视觉上扫一眼色块就能区分监控 vs 竞品。别名用半角 ();跟
                中文 chip 同行时视觉更紧凑。 */}
            <div className="ad-hl-legend">
              {project.brand && (
                <span className="ad-hl-row ad-hl-row-self">
                  <span className="ad-hl-stripe ad-hl-stripe-self" />
                  <span className="ad-hl-token hl-self">{project.brand}</span>
                  {project.aliases && project.aliases.length > 0 && (
                    <span className="ad-hl-aliases">
                      (
                      {project.aliases.map((a, i) => (
                        <span key={a}>
                          {i > 0 && "、"}
                          <span className="ad-hl-token hl-self-alias">{a}</span>
                        </span>
                      ))}
                      )
                    </span>
                  )}
                </span>
              )}
              {competitors
                .filter((c) => c.status === "confirmed")
                .map((c) => (
                  <span key={c.id} className="ad-hl-row ad-hl-row-comp">
                    <span className="ad-hl-stripe ad-hl-stripe-comp" />
                    <span className="ad-hl-token hl-competitor">{c.name}</span>
                    {c.aliases && c.aliases.length > 0 && (
                      <span className="ad-hl-aliases">
                        (
                        {c.aliases.map((a, i) => (
                          <span key={a}>
                            {i > 0 && "、"}
                            <span className="ad-hl-token hl-competitor-alias">{a}</span>
                          </span>
                        ))}
                        )
                      </span>
                    )}
                  </span>
                ))}
            </div>
            <div className="ad-body">
              {detailLoading ? (
                <Skeleton active paragraph={{ rows: 6 }} />
              ) : detail?.answer_content ? (
                <div
                  className="ad-content"
                  dangerouslySetInnerHTML={{
                    __html: renderAnswerHtml(detail.answer_content, groups),
                  }}
                />
              ) : (
                <div className="ad-empty">该回答无文本内容</div>
              )}
            </div>
          </div>

          {/* 关键词行 */}
          <div className="ad-keywords">
            <span className="ad-kw-label">输入关键词</span>
            {project.keywords && project.keywords.length > 0 ? (
              <div className="ad-kw-tags">
                {project.keywords.map((k) => (
                  <Tag key={k} color="orange" style={{ margin: 0 }}>
                    {k}
                  </Tag>
                ))}
              </div>
            ) : (
              <span style={{ color: "var(--text-tertiary)", fontSize: 12 }}>
                (该项目未配置关键词)
              </span>
            )}
          </div>
        </div>

        {/* 右侧 38% — 思考过程 / 命中率 */}
        <div className="ad-right">
          <div className="ad-right-tabs">
            <button
              type="button"
              className={`ad-rtab${rightTab === "thinking" ? " active" : ""}`}
              onClick={() => setRightTab("thinking")}
            >
              思考过程
            </button>
            <button
              type="button"
              className={`ad-rtab${rightTab === "hit" ? " active" : ""}`}
              onClick={() => setRightTab("hit")}
            >
              命中率统计
            </button>
          </div>

          {rightTab === "thinking" ? (
            <div className="ad-rtab-pane">
              <div className="ad-panel">
                <div className="ad-panel-head slim">
                  <h4>思考过程</h4>
                  {selected?.mode === "search" || selected?.mode === "web" || selected?.mode === "reasoning" ? (
                    <Tag color="purple" style={{ margin: 0 }}>思考模式</Tag>
                  ) : (
                    <Tag style={{ margin: 0 }}>快速模式</Tag>
                  )}
                </div>
                <div className="ad-body">
                  {thinkingSteps.length === 0 ? (
                    <div className="ad-empty">
                      {selected?.mode === "standard"
                        ? "当前为快速模式,模型直接输出结论,不返回推理过程"
                        : "该模型未返回思考过程"}
                    </div>
                  ) : (
                    <ol className="ad-think-chain">
                      {thinkingSteps.map((s) => (
                        <li key={s.step} className="ad-think-step">
                          <div className="ad-think-head">
                            <span className="ad-think-num">#{s.step}</span>
                            {s.raw && <Tag style={{ margin: 0 }}>未结构化</Tag>}
                          </div>
                          <div className="ad-think-body">{s.content}</div>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              </div>
              <div className="ad-tip">
                <strong>提示</strong>
                <p>思考过程是模型生成答案时的中间推理链,可用于分析它的推荐逻辑与品牌排序成因。快速模式下模型直接输出结论,不返回推理过程。</p>
              </div>
            </div>
          ) : (
            <div className="ad-rtab-pane">
              <div className="ad-panel">
                <div className="ad-panel-head slim">
                  <h4>命中率统计</h4>
                  <span className="ad-hit-rate">
                    {(hitRate * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="ad-body">
                  <ul className="ad-hit-list">
                    {hitItems.map((h) => (
                      <li key={h.id} className="ad-hit-row">
                        <input
                          type="checkbox"
                          checked={h.hit}
                          onChange={() => toggleHit(h.id)}
                        />
                        <span className={h.hit ? "hit" : ""}>{h.text}</span>
                        <button
                          type="button"
                          className="ad-hit-del"
                          onClick={() => removeHit(h.id)}
                          aria-label="删除命中点"
                        >
                          ×
                        </button>
                      </li>
                    ))}
                  </ul>
                  <div className="ad-hit-add">
                    <input
                      type="text"
                      placeholder="输入需要关注的命中点"
                      value={newHitText}
                      onChange={(e) => setNewHitText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") addHit();
                      }}
                    />
                    <button type="button" className="ad-hit-add-btn" onClick={addHit}>
                      添加
                    </button>
                  </div>
                  <p className="ad-hit-todo">
                    TODO:命中点列表本期仅本地维护,下个版本将持久化到 quality_concern_hits 表。
                  </p>
                </div>
              </div>
              <div className="ad-tip">
                <strong>提示</strong>
                <p>命中点用于核对该答案是否包含您关注的结构或知识点。勾选即表示该答案已命中,右侧命中率会自动计算。</p>
              </div>
            </div>
          )}
        </div>
      </div>

      <style>{`
        .ad-root { padding: 4px 0; }
        .ad-layout {
          display: grid;
          grid-template-columns: minmax(0, 7fr) minmax(0, 4fr);
          gap: 16px;
          align-items: start;
        }
        .ad-left, .ad-right { min-width: 0; display: flex; flex-direction: column; gap: 12px; }
        .ad-panel {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          overflow: hidden;
        }
        .ad-panel-head {
          padding: 12px 16px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 12px;
        }
        .ad-panel-head.slim { padding: 10px 14px; }
        .ad-panel-head h3 { margin: 0 0 4px; font-size: 15px; font-weight: 600; }
        .ad-panel-head h4 { margin: 0; font-size: 13px; font-weight: 600; }
        .ad-q-title { color: var(--text-primary); }
        .ad-meta { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--text-tertiary); flex-wrap: wrap; }
        .ad-rank-badge {
          background: linear-gradient(90deg, #fef3c7, #fde68a);
          color: #92400e;
          padding: 2px 10px;
          border-radius: 999px;
          font-weight: 600;
        }
        .ad-body { padding: 14px 16px; }
        .ad-content {
          font-size: 13px;
          line-height: 1.8;
          color: var(--text-primary);
        }
        .ad-content p { margin: 0 0 12px; }
        /* 与 RawAnswersPane 同款收敛 —— 不让浏览器默认的 h1=2em / h2=1.5em
           在 13px body 里爆出大字号,把页面撑得参差不齐。 */
        .ad-content h1 { font-size: 15px; margin: 16px 0 8px; font-weight: 600; line-height: 1.5; }
        .ad-content h2 { font-size: 14px; margin: 14px 0 6px; font-weight: 600; line-height: 1.5; }
        .ad-content h3,
        .ad-content h4,
        .ad-content h5,
        .ad-content h6 { font-size: 13px; margin: 12px 0 6px; font-weight: 600; line-height: 1.5; }
        .ad-content strong { font-weight: 600; }
        .ad-content code {
          background: var(--bg-page, #fafafa);
          padding: 1px 6px;
          border-radius: 3px;
          font-size: 12px;
          font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        }
        .ad-content pre {
          background: var(--bg-page, #fafafa);
          padding: 10px 12px;
          border-radius: 6px;
          font-size: 12px;
          overflow-x: auto;
        }
        .ad-content ul, .ad-content ol { padding-left: 22px; margin: 6px 0 10px; }
        .ad-content li { margin: 2px 0; }
        .ad-content blockquote {
          margin: 8px 0; padding: 4px 12px;
          border-left: 3px solid var(--brand-blue, #1a55e8);
          background: var(--bg-page, #fafafa);
          color: var(--text-secondary);
        }
        .ad-content table { border-collapse: collapse; margin: 8px 0; font-size: 12px; }
        .ad-content th, .ad-content td {
          border: 1px solid var(--border-light, #e5e7eb);
          padding: 6px 10px;
        }
        .ad-empty { color: var(--text-tertiary); font-size: 13px; padding: 20px 0; }
        /* 答案正文里的「监控品牌 / 监控品牌别名 / 竞品 / 竞品别名」四色高亮
           —— 与 utils/answerHtml.ts 拆出的 4 个 hl-* group 一一对应。颜色
           与 raw sub-tab 卡片正文共用一套,保证两边视觉一致。 */
        .ad-content .hl-self {
          background: #dbeafe;
          color: #1d4ed8;
          padding: 0 3px;
          border-radius: 3px;
          font-weight: 500;
        }
        .ad-content .hl-self-alias {
          background: #e0f2fe;
          color: #0369a1;
          padding: 0 3px;
          border-radius: 3px;
        }
        .ad-content .hl-competitor {
          background: #fef3c7;
          color: #a16207;
          padding: 0 3px;
          border-radius: 3px;
          font-weight: 500;
        }
        .ad-content .hl-competitor-alias {
          background: #fef9c3;
          color: #854d0e;
          padding: 0 3px;
          border-radius: 3px;
        }
        .ad-content .hl-keyword {
          background: #d9f99d;
          color: #3f6212;
          padding: 0 3px;
          border-radius: 3px;
        }
        /* 高亮图例 —— 单行 flex:每个品牌一行,主名前置一块方色块(蓝 =
           监控 / 黄 = 竞品)作为组语义锚点;主名 chip 主色 + 别名 chip
           浅色,与正文 hl-* 1:1 对应;整行套对应组的轻底色,横向一眼能
           区分监控 vs 竞品。 */
        .ad-hl-legend {
          display: flex;
          flex-wrap: wrap;
          align-items: center;
          gap: 6px 14px;
          padding: 8px 14px;
          background: var(--bg-secondary, #fafafa);
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          font-size: 12px;
          line-height: 1.6;
        }
        .ad-hl-row {
          display: inline-flex;
          align-items: stretch;
          gap: 4px;
          flex-wrap: wrap;
          padding: 2px 8px 2px 4px;
          border-radius: 4px;
        }
        /* 行底色按组上色 —— 监控 = 淡蓝、竞品 = 淡黄,色块高度顶满 chip */
        .ad-hl-row-self { background: rgba(29, 78, 216, 0.06); }
        .ad-hl-row-comp { background: rgba(202, 138, 4, 0.06); }
        /* 主名前的方色块 —— 蓝 / 黄,与组语义对齐;高度顶满主名 chip */
        .ad-hl-stripe {
          display: inline-block;
          width: 4px;
          border-radius: 2px;
          align-self: stretch;
          flex-shrink: 0;
        }
        .ad-hl-stripe-self { background: #1d4ed8; }
        .ad-hl-stripe-comp { background: #ca8a04; }
        .ad-hl-token {
          display: inline-flex;
          align-items: center;
          padding: 0 6px;
          border-radius: 3px;
          font-size: 12px;
          font-weight: 500;
          line-height: 1.7;
        }
        /* 图例区域内的 hl-* chip 配色 —— 与正文 (.ad-content) 走同一套蓝 /
           黄主色 + 同色系浅色别名。注意:这套规则只覆盖图例;正文 hl-* 由
           上面 .ad-content 选择器管,两套 CSS 颜色必须严格一致,否则同一
           token 在图例 vs 正文里颜色会不一致。 */
        .ad-hl-legend .hl-self {
          background: #dbeafe;
          color: #1d4ed8;
        }
        .ad-hl-legend .hl-self-alias {
          background: #e0f2fe;
          color: #0369a1;
        }
        .ad-hl-legend .hl-competitor {
          background: #fef3c7;
          color: #a16207;
        }
        .ad-hl-legend .hl-competitor-alias {
          background: #fef9c3;
          color: #854d0e;
        }
        .ad-hl-aliases {
          color: var(--text-tertiary, rgba(0,0,0,0.45));
          font-size: 12px;
          display: inline-flex;
          align-items: baseline;
          flex-wrap: wrap;
        }
        .ad-hl-aliases .ad-hl-token {
          margin: 0 1px;
        }
        .ad-keywords {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          padding: 10px 14px;
          display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
        }
        .ad-kw-label { font-size: 12px; color: var(--text-tertiary); }
        .ad-kw-tags { display: flex; gap: 6px; flex-wrap: wrap; }
        .ad-right-tabs {
          display: flex; gap: 0;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .ad-rtab {
          background: transparent; border: 0; padding: 10px 16px;
          font-size: 13px; color: var(--text-secondary); cursor: pointer;
          border-bottom: 2px solid transparent; margin-bottom: -1px;
          font-family: inherit;
        }
        .ad-rtab.active {
          color: var(--brand-blue, #1a55e8);
          border-bottom-color: var(--brand-blue, #1a55e8);
          font-weight: 500;
        }
        .ad-rtab-pane { display: flex; flex-direction: column; gap: 12px; }
        .ad-think-chain { list-style: none; padding: 0; margin: 0; display: flex; flex-direction: column; gap: 8px; }
        .ad-think-step {
          background: var(--bg-page, #fafafa);
          border-radius: 6px;
          padding: 8px 12px;
          font-size: 13px;
          line-height: 1.6;
          color: var(--text-primary);
        }
        .ad-think-head {
          display: flex; align-items: center; gap: 8px;
          margin-bottom: 4px;
        }
        .ad-think-num {
          font-weight: 600;
          color: var(--brand-blue, #1a55e8);
        }
        .ad-think-body { white-space: pre-wrap; word-break: break-word; }
        .ad-hit-list { list-style: none; padding: 0; margin: 0 0 12px; display: flex; flex-direction: column; gap: 6px; }
        .ad-hit-row {
          display: flex; align-items: center; gap: 8px;
          font-size: 13px;
          padding: 6px 8px;
          border-radius: 4px;
          background: var(--bg-page, #fafafa);
        }
        .ad-hit-row .hit { text-decoration: line-through; color: var(--text-tertiary); }
        .ad-hit-del {
          margin-left: auto;
          background: transparent; border: 0; cursor: pointer;
          color: var(--text-tertiary);
          font-size: 16px;
          line-height: 1;
        }
        .ad-hit-add {
          display: flex; gap: 6px;
        }
        .ad-hit-add input {
          flex: 1;
          padding: 6px 10px;
          border: 1px solid var(--border-light, #e5e7eb);
          border-radius: 4px;
          font-size: 13px;
          font-family: inherit;
        }
        .ad-hit-add-btn {
          background: var(--brand-blue, #1a55e8);
          color: #fff;
          border: 0;
          padding: 6px 14px;
          border-radius: 4px;
          font-size: 13px;
          cursor: pointer;
        }
        .ad-hit-rate {
          font-size: 18px;
          font-weight: 700;
          color: var(--brand-blue, #1a55e8);
          font-variant-numeric: tabular-nums;
        }
        .ad-hit-todo {
          margin: 8px 0 0;
          font-size: 11px;
          color: var(--text-tertiary);
          font-style: italic;
        }
        .ad-tip {
          background: var(--bg-page, #fafafa);
          border-radius: 6px;
          padding: 10px 14px;
          font-size: 12px;
          color: var(--text-secondary);
        }
        .ad-tip strong { color: var(--text-primary); margin-right: 4px; }
        .ad-tip p { margin: 4px 0 0; line-height: 1.5; }
      `}</style>
    </div>
  );
}
