import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { DatePicker, Empty, Modal, Skeleton, Spin, Tag, message } from "antd";
import { LinkOutlined, SearchOutlined } from "@ant-design/icons";
import dayjs, { type Dayjs } from "dayjs";
import { useSearchParams } from "react-router-dom";
import {
  getQuestionCompetitorAnalytics,
  getQuestionProductAnalytics,
  getQuestionStatusChanges,
  getQuestionSummary,
  getSubtaskDetail,
  listCompetitors,
  listPromptAnswers,
  type CompetitorBrandStat,
  type CompetitorOut,
  type PlatformExcerpt,
  type PromptAnswerDetailOut,
  type PromptAnswerOut,
  type ProjectDetailOut,
  type ProjectPlatform,
  type QuestionCompetitorAnalyticsOut,
  type QuestionPlatformStat,
  type QuestionPrevStat,
  type QuestionProductAnalyticsOut,
  type QuestionStatusChangesOut,
  type QuestionSummaryOut,
} from "../../api/projects";
import { cachedFetch, cacheKey } from "./questionTabCache";
import { platformColor, platformLabel } from "./platforms";

interface Props {
  projectId: number;
  detail: ProjectDetailOut;
}

type RankFilter = "all" | "top1" | "top3" | "top10";
type RangeKey = "7" | "15" | "30" | "60" | "custom";

const TIME_RANGES: { key: RangeKey; label: string }[] = [
  { key: "7", label: "7 天" },
  { key: "15", label: "15 天" },
  { key: "30", label: "30 天" },
  { key: "60", label: "2 个月" },
  { key: "custom", label: "自定义" },
];

interface PrevWindow {
  mentionRate: number;
  top1Rate: number;
  top3Rate: number;
  rankAvg: number | null;
}

// Adapter shape the inner panes (QuestionDetail / CompetitorDetail)
// consume. The legacy /questions/analytics endpoint is gone, so this
// is built locally from per-prompt product / competitor analytics
// responses instead of coming from the API surface.
interface QuestionAnalyticsItem {
  prompt_id: number;
  prompt: string;
  category: string | null;
  status: string;
  total: number;
  matched: number;
  top1_rate: number;
  top3_rate: number;
  mention_rate: number;
  rank_avg: number | null;
  coverage: number;
  platforms: QuestionPlatformStat[];
  prev: QuestionPrevStat | null;
  long_prev: QuestionPrevStat | null;
  excerpts: Record<string, PlatformExcerpt | null>;
}

interface QuestionStat {
  // Mirrors ``QuestionAnalyticsItem.prompt_id`` (ProjectPrompt.id)
  // so the UI can call ``listPromptAnswers`` with a numeric id.
  promptId: number;
  prompt: string;
  category: string | null;
  status: string;
  totalMentions: number;
  coverage: number;
  top1Rate: number;
  top3Rate: number;
  mentionRate: number;
  rankAvg: number | null;
  models: QuestionAnalyticsItem["platforms"];
  prev: PrevWindow | null;
}

// Lightweight conversion from the per-prompt product detail ``prev``
// block into the ``PrevWindow`` shape the right pane consumes.
function toPrevWindow(prev: QuestionPrevStat | null): PrevWindow | null {
  if (!prev) return null;
  return {
    mentionRate: prev.mention_rate,
    top1Rate: prev.top1_rate,
    top3Rate: prev.top3_rate,
    rankAvg: prev.rank_avg,
  };
}

const RANK_FILTER_LABEL: Record<RankFilter, string> = {
  all: "全部排名",
  top1: "Top1",
  top3: "Top3",
  top10: "Top10",
};

const CATEGORY_COLORS = ["blue", "green", "purple", "orange", "cyan", "yellow", "red", "magenta", "volcano", "geekblue"];

function colorFor(category: string | null): string {
  if (!category) return "default";
  let h = 0;
  for (let i = 0; i < category.length; i++) h = (h * 31 + category.charCodeAt(i)) | 0;
  return CATEGORY_COLORS[Math.abs(h) % CATEGORY_COLORS.length];
}

function pct(v: number): string {
  return `${(v * 100).toFixed(1)}%`;
}

function num(v: number): string {
  return v.toLocaleString("zh-CN");
}

interface HighlightGroup {
  /** Tokens to highlight with this group. Order is irrelevant; the
   *  regex picks the first match at any given position. Tokens that
   *  are empty / whitespace-only are dropped up front. */
  tokens: string[];
  /** CSS class applied to <span> wrappers around each match. */
  cls: string;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/**
 * Wrap tokens from successive groups with class-bearing spans.
 *
 * Iterative split — first group wins: a token already wrapped by
 * an earlier (higher-priority) group won't be re-matched by a later
 * one. The order in ``groups`` is therefore the visual priority:
 * 监控品牌 > 竞争品牌 > 关键词.
 */
function highlightText(text: string, groups: HighlightGroup[]): ReactNode {
  if (!text) return text;
  const usable = groups.filter((g) => g.tokens.length > 0);
  if (usable.length === 0) return text;
  let parts: (string | ReactNode)[] = [text];
  usable.forEach((g, gi) => {
    const re = new RegExp(`(${g.tokens.map(escapeRegex).join("|")})`, "g");
    const next: (string | ReactNode)[] = [];
    parts.forEach((p, pi) => {
      if (typeof p !== "string") {
        next.push(p);
        return;
      }
      const segs = p.split(re);
      segs.forEach((seg, si) => {
        if (si % 2 === 1) {
          next.push(
            <span key={`g${gi}-${pi}-${si}`} className={g.cls}>
              {seg}
            </span>,
          );
        } else if (seg) {
          next.push(seg);
        }
      });
    });
    parts = next;
  });
  return parts;
}

/** Token placeholder: a single private-use-area Unicode char that the
 *  upstream Markdown parser (marked) treats as ordinary text. We use
 *  this to stash each highlighted token's position in the source string
 *  while the Markdown parser is running, then swap the placeholder back
 *  out for a ``<span class="hl-...">`` wrapper in the produced HTML.
 *
 *  Inserting the ``<span>`` *before* ``marked.parse`` would break the
 *  parser's ``**...**`` strong-em delimiter pairing — a token sitting
 *  between two ``**`` markers (e.g. ``**伊速达**``) would get its span
 *  cut in half and the surrounding bold markup would swallow adjacent
 *  prose. The placeholder sidesteps that entirely. */
const HL_PLACEHOLDER = "";

/** Render ``answer_content`` (mixed Markdown + HTML from the upstream
 *  LLM) into a sanitized HTML string suitable for
 *  ``dangerouslySetInnerHTML``. Pipeline:
 *
 *  1. Walk ``groups`` in priority order (hl-self > hl-competitor >
 *     hl-keyword) and swap each token for a private-use Unicode
 *     placeholder, recording its class. Tokens already replaced are
 *     not re-matched because the placeholder isn't a token.
 *  2. ``marked.parse`` turns the Markdown into HTML; placeholders are
 *     ordinary characters so ``**`` / ``##`` / etc. delimiters pair
 *     cleanly across token boundaries.
 *  3. Swap placeholders back out for ``<span class="hl-...">`` wrappers
 *     in the produced HTML. Order doesn't matter here because each
 *     placeholder is unique.
 *  4. ``DOMPurify.sanitize`` strips anything dangerous (``<script>``,
 *     ``on*`` handlers, ``javascript:`` URLs) but keeps ``<span>``,
 *     ``<table>``, ``<ul>``, ``<blockquote>``, and yuanbao's
 *     ``<div class="media-*">`` video cards.
 */
function renderAnswerHtml(content: string, groups: HighlightGroup[]): string {
  const usable = groups.filter((g) => g.tokens.length > 0);
  if (!content || usable.length === 0) {
    return DOMPurify.sanitize(marked.parse(content) as string);
  }
  const tokens: Array<{ token: string; cls: string }> = [];
  let pre = content;
  usable.forEach((g) => {
    const re = new RegExp(`(${g.tokens.map(escapeRegex).join("|")})`, "g");
    pre = pre.replace(re, (match) => {
      const idx = tokens.length;
      tokens.push({ token: match, cls: g.cls });
      return `${HL_PLACEHOLDER}${idx}${HL_PLACEHOLDER}`;
    });
  });
  let html = marked.parse(pre) as string;
  tokens.forEach((entry, i) => {
    const ph = `${HL_PLACEHOLDER}${i}${HL_PLACEHOLDER}`;
    html = html.split(ph).join(`<span class="${entry.cls}">${entry.token}</span>`);
  });
  return DOMPurify.sanitize(html);
}

const PREVIEW_CHARS = 100;

/**
 * "较上一周期" delta row under each metric card.
 *
 * - ``format="rate"`` treats the values as fractions (0-1) and
 *   reports the percentage-point change.
 * - ``format="rank"`` treats them as ranks (1 is best) and reports
 *   the *improvement* in positions (e.g. No.5 → No.3 → "↑ 2 位").
 *   For rank, "lower is better", so we invert the sign when computing
 *   improvement.
 *
 * Renders nothing when either side is missing so the empty case is
 * clean (no awkward "vs —" placeholder).
 */
function DeltaRow({
  current,
  prev,
  format,
}: {
  current: number | null;
  prev: number | null | undefined;
  format: "rate" | "rank";
}) {
  if (current === null || current === undefined) {
    return <div className="qt-metric-change">跨模型平均</div>;
  }
  if (prev === null || prev === undefined) {
    return (
      <div className="qt-metric-change">
        {format === "rank" ? "跨模型平均" : "上一周期无数据"}
      </div>
    );
  }
  if (format === "rate") {
    const pp = (current - prev) * 100;
    const up = pp >= 0;
    const sign = up ? "+" : "";
    return (
      <div className={`qt-metric-change ${up ? "delta-up" : "delta-down"}`}>
        <span className="delta-arrow">{up ? "↑" : "↓"}</span>
        <span>
          较上一周期 {sign}
          {pp.toFixed(1)} pp
        </span>
      </div>
    );
  }
  // rank: lower is better, so improvement = prev - current.
  const improvement = prev - current;
  if (Math.abs(improvement) < 0.05) {
    return <div className="qt-metric-change">与上期持平</div>;
  }
  const up = improvement > 0;
  const sign = up ? "" : "-";
  return (
    <div className={`qt-metric-change ${up ? "delta-up" : "delta-down"}`}>
      <span className="delta-arrow">{up ? "↑" : "↓"}</span>
      <span>
        较上一周期 {sign}
        {Math.abs(improvement).toFixed(1)} 位
      </span>
    </div>
  );
}

function rankClass(rank: number | null): string {
  if (rank === null) return "qt-rank-other";
  if (rank <= 1) return "qt-rank-1";
  if (rank <= 3) return "qt-rank-3";
  if (rank <= 10) return "qt-rank-10";
  return "qt-rank-other";
}

/**
 * 问题提及分析 —— 按 docs/ui-sample/index.html 的 #tab-question 重建:
 *   顶部: 二级 Tab(全部问题 / 引流感 / 场景类 / ...) + 右上角时间选择器(默认 15 天)
 *   左侧: 搜索 + 模型筛选 + 排名筛选 + 问题列表(按 prompt 聚合 brand-mentions)
 *   右侧: 4 张 metric + 模型对比表(每模型一行: 排名 / 提及次数 / 情感 / 推荐)
 *        「查看原文」打开弹窗,展示当前问题在所选时间窗内的全部 AI 回答
 *        (跨模型 — 不是只列单模型)
 *   右侧卡片自带内部滚动条,页面整体不会滚动
 */
export default function QuestionTab({ projectId, detail }: Props) {
  const [platforms, setPlatforms] = useState<ProjectPlatform[]>([]);
  // Layered analytics loads — replaced the single ``analytics`` blob in
  // 2026-08-18 so the left list shows instantly and each pane fetches its
  // own detail lazily:
  //   - ``summary`` always loads on project / window change
  //   - ``productDetail`` loads when product pane is active (or the
  //     previously-selected prompt needs an update)
  //   - ``competitorDetail`` loads ONLY on the competitor pane
  //   - ``stableChanges`` loads ONLY on the stable pane
  const [summary, setSummary] = useState<QuestionSummaryOut | null>(null);
  const [productDetail, setProductDetail] =
    useState<QuestionProductAnalyticsOut | null>(null);
  const [competitorDetail, setCompetitorDetail] =
    useState<QuestionCompetitorAnalyticsOut | null>(null);
  const [stableChanges, setStableChanges] = useState<QuestionStatusChangesOut | null>(
    null,
  );
  const [competitors, setCompetitors] = useState<CompetitorOut[]>([]);
  // True while project + summary are both in flight for the first time —
  // gates the full-screen skeleton so the UI doesn't flash an empty
  // state mid-load. Per-pane refetches don't flip this.
  const [loading, setLoading] = useState(true);

  const [keyword, setKeyword] = useState("");
  const [modelFilter, setModelFilter] = useState<string>("all");
  const [rankFilter, setRankFilter] = useState<RankFilter>("all");
  const [selectedPromptId, setSelectedPromptId] = useState<number | null>(null);
  // Project-level category roll-up from the analytics endpoint, used by
  // the 「下钻分析」 chip strip. Empty when the project has no prompts.
  const [categorySummary, setCategorySummary] = useState<
    import("../../api/projects").CategoryStat[]
  >([]);
  // Top-right time selector — mirrors OverviewTab's range buttons so the
  // "查看原文" modal pulls answers from the same window the operator just
  // saw on screen. Default is 15 天 per the spec.
  const [range, setRange] = useState<RangeKey>("15");
  const [custom, setCustom] = useState<[Dayjs, Dayjs]>(() => [
    dayjs().subtract(14, "day"),
    dayjs(),
  ]);

  // Top-level sub-pane switcher. URL-synced via ``?sub=product|competitor|
  // stable`` so a deep link / refresh keeps the operator where they were.
  // The default is "product" (自品牌分析) per the spec.
  type PaneTab = "product" | "competitor" | "stable";
  const PANE_TABS: { key: PaneTab; label: string }[] = [
    { key: "product", label: "产品分析" },
    { key: "competitor", label: "竞品分析" },
    { key: "stable", label: "稳定与掉落" },
  ];
  const [searchParams, setSearchParams] = useSearchParams();
  const rawSub = searchParams.get("sub");
  const paneTab: PaneTab =
    rawSub === "competitor" || rawSub === "stable" ? rawSub : "product";
  const setPaneTab = (next: PaneTab) => {
    const np = new URLSearchParams(searchParams);
    np.set("sub", next);
    setSearchParams(np, { replace: true });
  };
  // Stable pane has its own server round-trip; cached alongside the
  // analytics fetch so the time selector invalidates both at once.

  const dateQuery = useMemo(
    () =>
      range === "custom"
        ? {
            start: custom[0].format("YYYY-MM-DD"),
            end: custom[1].format("YYYY-MM-DD"),
          }
        : { days: Number(range) },
    [range, custom],
  );

  // The window that "current" gets compared against: the same-length
  // window ending the day before the current window starts. For a
  // 7-day window [end-6, end] the comparison window is
  // [end-13, end-7] — no overlap, contiguous. The backend computes
  // this server-side, but we echo the range string under each metric
  // card so the operator can tell at a glance which window is being
  // compared.
  const prevWindowLabel = useMemo(() => {
    const lengthDays =
      range === "custom"
        ? custom[1].diff(custom[0], "day") + 1
        : Number(range);
    let prevEnd: Dayjs;
    let prevStart: Dayjs;
    if (range !== "custom") {
      const today = dayjs();
      prevEnd = today.subtract(lengthDays, "day");
      prevStart = prevEnd.subtract(lengthDays - 1, "day");
    } else {
      prevEnd = custom[0].subtract(1, "day");
      prevStart = prevEnd.subtract(lengthDays - 1, "day");
    }
    return `${prevStart.format("YYYY-MM-DD")} ~ ${prevEnd.format("YYYY-MM-DD")}`;
  }, [range, custom]);

  // Long prev window — same length as the current window, but offset
  // 30 days further back. Drives the 「本月 vs 上月」 card. The offset
  // is fixed at 30 days regardless of the chosen range — for short
  // ranges the two windows are spaced 30 days apart, for long ranges
  // they still touch one month back. None of this is configurable; if
  // we need per-window "this month vs same month last year" the
  // backend would need a second offset param.
  const prevLongLabel = useMemo(() => {
    const lengthDays =
      range === "custom"
        ? custom[1].diff(custom[0], "day") + 1
        : Number(range);
    let anchor: Dayjs;
    if (range !== "custom") {
      anchor = dayjs().subtract(lengthDays, "day");
    } else {
      anchor = custom[0].subtract(1, "day");
    }
    const prevLongEnd = anchor.subtract(30, "day");
    const prevLongStart = prevLongEnd.subtract(lengthDays - 1, "day");
    return `${prevLongStart.format("YYYY-MM-DD")} ~ ${prevLongEnd.format("YYYY-MM-DD")}`;
  }, [range, custom]);

  // Stable key for the time window — keeps the cache stable when only
  // object identity differs (``dateQuery`` is recreated by useMemo every
  // render). Used by every effect that depends on the window.
  const dateQueryKey = useMemo(() => JSON.stringify(dateQuery), [dateQuery]);

  // Competitor list — independent of the analytics endpoints. The project
  // detail itself is provided as a prop by Detail.tsx (which already
  // fetched it), so we only need to populate platforms (sync, from the
  // prop) and the competitor list (async, re-fetched when projectId
  // changes).
  useEffect(() => {
    setPlatforms(detail.platforms ?? []);
  }, [detail]);

  useEffect(() => {
    const ac = new AbortController();
    cachedFetch<{ items: CompetitorOut[] }>(
      cacheKey(["competitors", projectId]),
      () => listCompetitors(projectId),
    )
      .then((competitorsRes) => {
        if (ac.signal.aborted) return;
        setCompetitors(competitorsRes.items);
      })
      .catch((err: Error) => {
        if (ac.signal.aborted) return;
        message.error(err.message || "竞品加载失败");
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort();
  }, [projectId]);

  // ``summary`` — left list + category drill-down. Always loaded on
  // project / window change; cheap (one row per prompt, no per-model
  // breakdown).
  useEffect(() => {
    const ac = new AbortController();
    setLoading(true);
    cachedFetch<QuestionSummaryOut>(
      cacheKey(["summary", projectId, dateQueryKey]),
      () => getQuestionSummary(projectId, dateQuery),
    )
      .then((data) => {
        if (ac.signal.aborted) return;
        setSummary(data);
        setCategorySummary(data.category_summary ?? []);
        if (data.items.length && selectedPromptId === null) {
          setSelectedPromptId(data.items[0].prompt_id);
        }
      })
      .catch((err: Error) => {
        if (ac.signal.aborted) return;
        message.error(err.message || "问题摘要加载失败");
        setSummary(null);
      })
      .finally(() => {
        if (!ac.signal.aborted) setLoading(false);
      });
    return () => ac.abort();
    // ``selectedPromptId`` is read for the auto-select default; not
    // listed so changing the selection doesn't refetch summary.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId, dateQueryKey]);

  // ``productDetail`` — single-prompt KPIs + model breakdown + excerpts.
  // Fires when the product pane is active AND a prompt is selected.
  // Falls through to selectedPromptId-driven re-runs so switching
  // prompts reloads.
  useEffect(() => {
    if (!selectedPromptId || paneTab !== "product") return;
    const ac = new AbortController();
    cachedFetch<QuestionProductAnalyticsOut>(
      cacheKey(["product", projectId, selectedPromptId, dateQueryKey]),
      () => getQuestionProductAnalytics(projectId, selectedPromptId, dateQuery),
    )
      .then((data) => {
        if (ac.signal.aborted) return;
        setProductDetail(data);
      })
      .catch((err: Error) => {
        if (ac.signal.aborted) return;
        message.error(err.message || "产品视角数据加载失败");
        setProductDetail(null);
      });
    return () => ac.abort();
  }, [paneTab, selectedPromptId, projectId, dateQueryKey]);

  // ``competitorDetail`` — single-prompt competitor brands breakdown.
  // Fires ONLY on the competitor pane, otherwise the round-trip is
  // skipped (spec calls for self/competitor view isolation).
  useEffect(() => {
    if (!selectedPromptId || paneTab !== "competitor") return;
    const ac = new AbortController();
    cachedFetch<QuestionCompetitorAnalyticsOut>(
      cacheKey(["competitor", projectId, selectedPromptId, dateQueryKey]),
      () => getQuestionCompetitorAnalytics(projectId, selectedPromptId, dateQuery),
    )
      .then((data) => {
        if (ac.signal.aborted) return;
        setCompetitorDetail(data);
      })
      .catch((err: Error) => {
        if (ac.signal.aborted) return;
        message.error(err.message || "竞品视角数据加载失败");
        setCompetitorDetail(null);
      });
    return () => ac.abort();
  }, [paneTab, selectedPromptId, projectId, dateQueryKey]);

  // ``stableChanges`` — 2×2 grid quadrants. Fires ONLY on the stable
  // pane.
  useEffect(() => {
    if (paneTab !== "stable") return;
    const ac = new AbortController();
    cachedFetch<QuestionStatusChangesOut>(
      cacheKey(["stable", projectId, dateQueryKey]),
      () => getQuestionStatusChanges(projectId, dateQuery),
    )
      .then((data) => {
        if (ac.signal.aborted) return;
        setStableChanges(data);
      })
      .catch((err: Error) => {
        if (ac.signal.aborted) return;
        message.error(err.message || "稳定与掉落数据加载失败");
        setStableChanges(null);
      });
    return () => ac.abort();
  }, [paneTab, projectId, dateQueryKey]);

  // Per-platform ``QuestionPlatformStat`` for the currently-selected
  // prompt. Sourced from ``productDetail.platforms`` (which is the only
  // place we have per-model breakdown under the layered split). Other
  // prompts in the list keep an empty ``models`` array — only the
  // selected prompt's model table renders, so this is fine.
  const productPlatforms = useMemo(
    () => productDetail?.platforms ?? [],
    [productDetail],
  );

  // Convert the lightweight ``QuestionSummaryItem`` rows into the
  // ``QuestionStat`` shape the list + detail UI consume. Per-prompt
  // platform breakdown is only present for the currently-selected
  // prompt (via ``productPlatforms``); the model's table in the right
  // pane filters down from there.
  const stats = useMemo<QuestionStat[]>(
    () =>
      (summary?.items ?? []).map((a) => {
        // Inject per-model breakdown only for the selected prompt so
        // the right pane's model table can render the filtered rows.
        const sourcePlatforms =
          a.prompt_id === selectedPromptId ? productPlatforms : [];
        const filteredModels = sourcePlatforms.filter((m) => {
          if (modelFilter !== "all" && m.platform !== modelFilter) return false;
          if (rankFilter === "top1" && m.best_rank !== 1) return false;
          if (rankFilter === "top3" && (m.best_rank === null || m.best_rank > 3)) return false;
          if (rankFilter === "top10" && (m.best_rank === null || m.best_rank > 10)) return false;
          return true;
        });
        return {
          promptId: a.prompt_id,
          prompt: a.prompt,
          category: a.category,
          status: a.status,
          totalMentions: a.matched,
          coverage: a.coverage,
          top1Rate: a.top1_rate,
          top3Rate: a.top3_rate,
          mentionRate: a.mention_rate,
          rankAvg: a.rank_avg,
          models: filteredModels.sort((x, y) => (x.best_rank ?? 99) - (y.best_rank ?? 99)),
          // prev comes from the per-prompt product detail. Other
          // prompts in the list (non-selected) have ``prev = null``
          // because we never had the window-pair data for them. They
          // aren't shown in the right pane anyway, only the selected
          // prompt's detail page.
          prev: productDetail && a.prompt_id === selectedPromptId
            ? toPrevWindow(productDetail.prev)
            : null,
        };
      }),
    [summary, productPlatforms, selectedPromptId, modelFilter, rankFilter, productDetail],
  );

  // Apply keyword filter only — category subtabs were removed in
  // 2026-08-18 cleanup; prompts are no longer sliced by category here.
  const visibleStats = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    return stats.filter((s) => {
      if (k && !s.prompt.toLowerCase().includes(k)) return false;
      return true;
    });
  }, [stats, keyword]);

  const selected = visibleStats.find((s) => s.promptId === selectedPromptId) ?? visibleStats[0] ?? null;

  // Project the per-prompt detail endpoints into the
  // ``QuestionAnalyticsItem`` shape that the right pane (QuestionDetail
  // / CompetitorDetail) consumes. They only read ``excerpts`` and
  // ``long_prev.mention_rate`` from ``item``; both are present on
  // ``QuestionProductAnalyticsOut`` and ``QuestionCompetitorAnalyticsOut``
  // under the same keys.
  const effectiveProductItem = useMemo<QuestionAnalyticsItem | null>(() => {
    if (!productDetail) return null;
    if (!selected) return null;
    return {
      ...productDetail,
      prompt_id: selected.promptId,
      prompt: selected.prompt,
      category: selected.category,
      status: selected.status,
      total: selected.totalMentions,
      matched: selected.totalMentions,
      top1_rate: selected.top1Rate,
      top3_rate: selected.top3Rate,
      mention_rate: selected.mentionRate,
      rank_avg: selected.rankAvg,
      coverage: selected.coverage,
      platforms: productDetail.platforms,
      prev: productDetail.prev,
      long_prev: productDetail.long_prev,
      excerpts: productDetail.excerpts as Record<string, PlatformExcerpt | null>,
    };
  }, [productDetail, selected]);

  const effectiveCompetitorItem = useMemo<QuestionAnalyticsItem | null>(() => {
    if (!competitorDetail) return null;
    if (!selected) return null;
    return {
      ...competitorDetail,
      prompt_id: selected.promptId,
      prompt: selected.prompt,
      category: selected.category,
      status: selected.status,
      total: selected.totalMentions,
      matched: selected.totalMentions,
      top1_rate: selected.top1Rate,
      top3_rate: selected.top3Rate,
      mention_rate: selected.mentionRate,
      rank_avg: selected.rankAvg,
      coverage: selected.coverage,
      platforms: [],
      prev: null,
      long_prev: null,
      excerpts: competitorDetail.excerpts as Record<string, PlatformExcerpt | null>,
    };
  }, [competitorDetail, selected]);

  // Tokens used by the 查看原文 modal to colour-code brand / competitor /
  // keyword hits in the answer body. Order is the visual priority.
  const highlightGroups = useMemo<HighlightGroup[]>(() => {
    const cleanTokens = (xs: Array<string | null | undefined>): string[] => {
      const out: string[] = [];
      const seen = new Set<string>();
      xs.forEach((x) => {
        if (!x) return;
        const t = x.trim();
        if (!t) return;
        const k = t.toLowerCase();
        if (seen.has(k)) return;
        seen.add(k);
        out.push(t);
      });
      return out;
    };
    const groups: HighlightGroup[] = [];
    const selfTokens = cleanTokens([
      detail?.brand ?? null,
      ...(detail?.aliases ?? []),
    ]);
    if (selfTokens.length > 0) {
      groups.push({ tokens: selfTokens, cls: "hl-self" });
    }
    const competitorTokens: string[] = [];
    competitors.forEach((c) => {
      if (c.name) competitorTokens.push(c.name);
      (c.aliases ?? []).forEach((a) => a && competitorTokens.push(a));
    });
    const compClean = cleanTokens(competitorTokens);
    if (compClean.length > 0) {
      groups.push({ tokens: compClean, cls: "hl-competitor" });
    }
    const kwClean = cleanTokens(detail?.keywords ?? []);
    if (kwClean.length > 0) {
      groups.push({ tokens: kwClean, cls: "hl-keyword" });
    }
    return groups;
  }, [detail, competitors]);

  // Answers modal — opened from each model row's "查看原文" link. The modal
  // fetches on demand (not preloaded) so the listing isn't held open while
  // the operator browses different models. Re-fetches when the date range
  // changes so the window stays in sync with the page-level selector.
  const [answersOpen, setAnswersOpen] = useState(false);
  const [answersTarget, setAnswersTarget] = useState<{
    promptId: number;
    platform: string;
  } | null>(null);
  const [answers, setAnswers] = useState<PromptAnswerOut[]>([]);
  const [answersLoading, setAnswersLoading] = useState(false);
  // Nested "full-content" modal — when the operator clicks 展开全部 on
  // an AnswerCard we pop a second Modal on top of the list modal so they
  // can read the long answer with thinking / images / citations without
  // the list getting pushed offscreen.
  const [fullOpen, setFullOpen] = useState(false);
  const [fullTarget, setFullTarget] = useState<PromptAnswerDetailOut | null>(null);
  const [fullLoading, setFullLoading] = useState(false);

  useEffect(() => {
    if (!answersOpen || !answersTarget) return;
    let cancelled = false;
    setAnswersLoading(true);
    listPromptAnswers(projectId, answersTarget.promptId, {
      ...dateQuery,
      platform: answersTarget.platform,
    })
      .then((res) => {
        if (cancelled) return;
        // Pending/processing rows show "此回答无文本内容" and aren't useful
        // for reading the AI's actual answer; drop them so the modal only
        // lists finished answers.
        //
        // ``completed`` is the historical value (legacy mock data), while
        // ``success`` is what ``RunStatus.SUCCESS`` writes through the real
        // sync pipeline — see backend/app/models/enums.py. Accept both
        // so old fixture projects and production-synced projects render
        // the same modal.
        setAnswers(
          res.items.filter(
            (a) => a.status === "completed" || a.status === "success",
          ),
        );
      })
      .catch((err: Error) => {
        if (cancelled) return;
        message.error(err.message || "加载原文失败");
      })
      .finally(() => {
        if (!cancelled) setAnswersLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [answersOpen, answersTarget, projectId, dateQuery]);

  const openAnswers = (promptId: number, platform: string) => {
    setAnswersTarget({ promptId, platform });
    setAnswersOpen(true);
  };

  const openFullAnswer = (a: PromptAnswerOut) => {
    // List rows carry a truncated preview; fetch the full payload before
    // opening the modal so the user actually sees the untruncated text,
    // page screenshot, reasoning trace, references, citations, and
    // recommended questions. While the request is in flight we open the
    // modal with a loading state instead of jumping the user in front of
    // a half-rendered card.
    setFullOpen(true);
    setFullLoading(true);
    getSubtaskDetail(a.subtask_id)
      .then((detail) => {
        setFullTarget(detail);
      })
      .catch((err: Error) => {
        message.error(err.message || "加载完整回答失败");
        setFullOpen(false);
      })
      .finally(() => {
        setFullLoading(false);
      });
  };

  if (loading) {
    return <Skeleton active paragraph={{ rows: 10 }} />;
  }

  if ((summary?.items ?? []).length === 0) {
    return (
      <div
        style={{
          background: "#fff",
          borderRadius: 8,
          padding: "60px 24px",
          textAlign: "center",
          border: "1px solid var(--border-light, #f0f0f0)",
        }}
      >
        <Empty description="该监控项目还没有配置任何问题 — 在「问题管理」或项目编辑弹窗中添加后,这里会按问题维度展示提及分析" />
      </div>
    );
  }

  return (
    <div className="qt-root">
      {/* 顶部子面板 Tab(产品分析 / 竞品分析 / 稳定与掉落)+ 共享时间选择器
         —— 「产品分析」与「竞品分析」共用下面的左列表 + 右详情布局,
         区别仅是后端的 view 参数。「稳定与掉落」换成一个独立的 2x2
         四宫格视图,不再需要左列表。 */}
      <div className="qt-pane-tabs">
        {PANE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`qt-pane-tab${paneTab === t.key ? " active" : ""}`}
            onClick={() => setPaneTab(t.key)}
          >
            {t.label}
          </button>
        ))}
        <div className="qt-pane-tabs-right">
          <div className="qt-time-selector">
            {TIME_RANGES.map((r) => (
              <button
                key={r.key}
                type="button"
                className={`qt-time-btn${range === r.key ? " active" : ""}`}
                onClick={() => setRange(r.key)}
              >
                {r.label}
              </button>
            ))}
          </div>
          {range === "custom" && (
            <DatePicker.RangePicker
              size="small"
              value={custom}
              allowClear={false}
              onChange={(v) => {
                if (v && v[0] && v[1]) setCustom([v[0], v[1]]);
              }}
              style={{ marginLeft: 8, width: 240 }}
            />
          )}
        </div>
      </div>

      {paneTab === "stable" ? (
        <StablePane
          data={stableChanges}
          loading={loading}
          platformLabel={platformLabel}
        />
      ) : (
      <>
      <div className="qt-split">
        {/* 左侧:问题列表 */}
        <div className="qt-split-left">
          <div className="qt-search-bar">
            <div className="qt-search-input-wrap">
              <SearchOutlined style={{ color: "var(--text-quaternary)" }} />
              <input
                type="text"
                placeholder="搜索问题..."
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
            </div>
            <select
              className="qt-select"
              value={modelFilter}
              onChange={(e) => setModelFilter(e.target.value)}
            >
              <option value="all">全模型</option>
              {platforms.map((p) => (
                <option key={p.platform} value={p.platform}>
                  {p.platform}
                </option>
              ))}
            </select>
            <select
              className="qt-select"
              value={rankFilter}
              onChange={(e) => setRankFilter(e.target.value as RankFilter)}
            >
              {(Object.keys(RANK_FILTER_LABEL) as RankFilter[]).map((k) => (
                <option key={k} value={k}>
                  {RANK_FILTER_LABEL[k]}
                </option>
              ))}
            </select>
          </div>
          <div className="qt-list">
            {visibleStats.length === 0 ? (
              <Empty description="无匹配问题" style={{ padding: 32 }} />
            ) : (
              visibleStats.map((s) => {
                const active = selected?.promptId === s.promptId;
                return (
                  <button
                    key={s.promptId}
                    type="button"
                    className={`qt-list-item${active ? " active" : ""}`}
                    onClick={() => setSelectedPromptId(s.promptId)}
                  >
                    <div className="qt-list-title">{s.prompt}</div>
                    <div className="qt-list-meta">
                      {s.category && (
                        <Tag color={colorFor(s.category)} style={{ margin: 0 }}>
                          {s.category}
                        </Tag>
                      )}
                      <span>{num(s.totalMentions)} 次提及</span>
                      <span>
                        {s.coverage}/{platforms.length || 7} 模型覆盖
                      </span>
                    </div>
                    <div className="qt-list-metrics">
                      <div className="qt-list-metric">
                        提及率 <strong>{pct(s.mentionRate)}</strong>
                      </div>
                      <div className="qt-list-metric">
                        Top1 <strong>{pct(s.top1Rate)}</strong>
                      </div>
                      <div className="qt-list-metric">
                        Top3 <strong>{pct(s.top3Rate)}</strong>
                      </div>
                    </div>
                  </button>
                );
              })
            )}
          </div>
        </div>

        {/* 右侧:问题详情 */}
        <div className="qt-split-right">
          {selected ? (
            paneTab === "competitor" ? (
              <CompetitorDetail
                stat={selected}
                item={effectiveCompetitorItem}
                brands={competitorDetail?.brands ?? []}
                platforms={platforms.map((entry) => entry.platform)}
              />
            ) : (
              <QuestionDetail
                stat={selected}
                item={effectiveProductItem}
                totalPlatforms={platforms.length}
                onViewOriginal={openAnswers}
                prevWindowLabel={prevWindowLabel}
                prevLongLabel={prevLongLabel}
                categorySummary={categorySummary}
                view="self"
              />
            )
          ) : (
            <Empty description="请选择左侧问题查看详情" style={{ padding: 60 }} />
          )}
        </div>
      </div>
      </>
      )}

      {/* 查看原文 弹窗 —— 列出当前问题在所选时间窗内的所有回答。

      {/* 查看原文 弹窗 —— 列出当前问题在所选时间窗内的所有回答。
          用 ``100vh`` 计算 maxHeight 而不是写死 768px,避免窄屏
          (例如 1366×768 笔记本)上 modal 撑破视口、触发 body 滚动
          条。Modal 顶到距视口顶 24px,内容在 body 内滚动,外层
          页面始终静止。
          NOTE: ``.ant-modal-wrap`` (antd's full-viewport modal
          wrapper) has ``overflow: auto`` by default. If the modal
          itself is even 1px taller than the wrap (which is 100vh),
          the wrap picks up a vertical scrollbar at the rightmost
          edge of the viewport. The fix is to cap the *content*
          (not just the body) at ``100vh - 24px`` and let the body
          use ``flex: 1`` to fill the remaining vertical space —
          that way the modal exactly fits inside the wrap and any
          internal overflow stays inside the body rather than
          spilling into the wrap. The flex-based approach is more
          robust than subtracting magic numbers off the body because
          it doesn't need to know antd's internal padding values. */}
      <Modal
        open={answersOpen}
        onCancel={() => setAnswersOpen(false)}
        footer={null}
        width={1024}
        centered={false}
        style={{ top: 24 }}
        styles={{
          wrapper: { overflow: "hidden" },
          content: {
            maxHeight: "calc(100vh - 24px)",
            display: "flex",
            flexDirection: "column",
          },
          body: {
            flex: 1,
            minHeight: 0,
            overflowY: "auto",
            padding: 16,
          },
        }}
        title={
          <div>
            <div style={{ fontSize: 16, fontWeight: 600 }}>
              查看原文
              {answersTarget && (
                <Tag color="blue" style={{ marginLeft: 8 }}>
                  {platformLabel(answersTarget.platform)}
                </Tag>
              )}
            </div>
            {answersTarget && (
              <div
                style={{
                  marginTop: 6,
                  fontSize: 12,
                  color: "var(--text-tertiary)",
                  fontWeight: 400,
                }}
              >
                {summary?.items.find((a) => a.prompt_id === answersTarget.promptId)?.prompt}
              </div>
            )}
          </div>
        }
        destroyOnClose
      >
        {answersLoading ? (
          <div style={{ textAlign: "center", padding: 48 }}>
            <Spin />
          </div>
        ) : answers.length === 0 ? (
          <Empty description="所选时间窗内暂无回答记录" />
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {answers.map((a) => (
              <AnswerCard
                key={a.subtask_id}
                ans={a}
                groups={highlightGroups}
                onOpenFull={openFullAnswer}
              />
            ))}
          </div>
        )}
      </Modal>

      {/* 嵌套的"完整原文"弹窗 —— 显示 answer_content + thinking +
          媒体 + 引用源 + 推荐问题。长回答 / 多图环境里把全文塞进
          list modal 会把列表挤出去,所以单独一层 modal。 */}
      {fullOpen && (
        <FullAnswerModal
          ans={fullTarget}
          groups={highlightGroups}
          loading={fullLoading}
          onClose={() => setFullOpen(false)}
        />
      )}

      <style>{`
        /* Root fills the visible area below the AppLayout header. The parent
           .project-detail-page is sized to .app-content content box (which
           already excludes the 24+24 px padding via box-sizing: border-box),
           so .qt-root just takes 100% of that. The earlier minus-48 offset
           was only correct when .qt-root was a direct child of .app-content;
           now that there is an intermediate wrapper, that subtraction would
           double-count the padding. */
        .qt-root {
          display: flex;
          flex-direction: column;
          gap: 12px;
          height: 100%;
          /* Clipping at the root absorbs any sub-pixel overflow from flex
             children so it does not re-light .app-content right-edge
             scrollbar. */
          overflow: hidden;
        }
        /* Time selector (top-right) — mirrors .time-selector in OverviewTab
           so the two pages feel consistent. */
        .qt-time-selector {
          display: inline-flex;
          background: var(--bg-page, #f5f6f8);
          border-radius: 6px;
          padding: 2px;
          gap: 2px;
        }
        .qt-time-btn {
          background: transparent;
          border: 0;
          padding: 4px 12px;
          font-size: 13px;
          color: var(--text-secondary, #4f4f4f);
          cursor: pointer;
          border-radius: 4px;
          font-family: inherit;
        }
        .qt-time-btn:hover { color: var(--brand-blue, #1a55e8); }
        .qt-time-btn.active {
          background: #fff;
          color: var(--brand-blue, #1a55e8);
          font-weight: 500;
          box-shadow: 0 1px 2px rgba(0,0,0,0.06);
        }

        .qt-split {
          display: grid;
          grid-template-columns: minmax(320px, 1fr) minmax(0, 2fr);
          gap: 12px;
          flex: 1;
          min-height: 0;
        }
        @media (max-width: 1100px) {
          .qt-split { grid-template-columns: 1fr; }
        }

        .qt-split-left {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          display: flex;
          flex-direction: column;
          overflow: hidden;
          min-height: 0;
        }
        .qt-search-bar {
          display: flex;
          gap: 8px;
          padding: 10px 12px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          flex-wrap: wrap;
        }
        .qt-search-input-wrap {
          flex: 1;
          min-width: 140px;
          display: flex;
          align-items: center;
          gap: 6px;
          padding: 4px 10px;
          border: 1px solid var(--border-light, #e5e7eb);
          border-radius: 4px;
          background: var(--bg-page, #fafafa);
        }
        .qt-search-input-wrap input {
          flex: 1;
          border: 0;
          outline: none;
          background: transparent;
          font-size: 13px;
          font-family: inherit;
        }
        .qt-select {
          padding: 4px 8px;
          border: 1px solid var(--border-light, #e5e7eb);
          border-radius: 4px;
          background: #fff;
          font-size: 13px;
          color: var(--text-primary);
          font-family: inherit;
          cursor: pointer;
        }

        .qt-list {
          flex: 1;
          overflow-y: auto;
          padding: 8px;
          display: flex;
          flex-direction: column;
          gap: 6px;
          min-height: 0;
        }
        .qt-list-item {
          background: transparent;
          border: 1px solid transparent;
          padding: 10px 12px;
          border-radius: 6px;
          text-align: left;
          cursor: pointer;
          font-family: inherit;
        }
        .qt-list-item:hover { background: var(--bg-hover, #fafafa); }
        .qt-list-item.active {
          background: var(--brand-blue-50, #e8f0fe);
          border-color: var(--brand-blue, #1a55e8);
        }
        .qt-list-title {
          font-size: 14px;
          font-weight: 500;
          color: var(--text-primary);
          margin-bottom: 6px;
        }
        .qt-list-meta {
          display: flex;
          gap: 8px;
          align-items: center;
          font-size: 12px;
          color: var(--text-tertiary);
          margin-bottom: 8px;
          flex-wrap: wrap;
        }
        .qt-list-metrics {
          display: flex;
          gap: 12px;
          font-size: 12px;
          color: var(--text-tertiary);
        }
        .qt-list-metric strong {
          color: var(--text-primary);
          margin-left: 2px;
        }

        /* Right card scrolls internally. flex-direction: column plus
           min-height: 0 lets the .qt-detail-body node take the remaining
           space and own its own overflow. */
        .qt-split-right {
          background: #fff;
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          display: flex;
          flex-direction: column;
          min-height: 0;
          overflow: hidden;
        }
        /* Plain block layout — every section (KPI row / 模型对比 /
           AI 摘录 / 时间对比 / 下钻) keeps its natural height and
           stacks top-to-bottom. The previous flex-column + table-wrap
           flex:1 design forced the model-compare table into a flex slot
           that <table> cannot shrink into, so the table collapsed and
           its rows visually overlapped the AI excerpt grid that came
           right after. Letting the body block-scroll avoids the
           flex/table height contract entirely. */
        .qt-detail-body {
          padding: 18px 20px;
          overflow-y: auto;
          flex: 1;
          min-height: 0;
        }
        .qt-detail-header h2 {
          margin: 0 0 6px;
          font-size: 18px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .qt-detail-meta {
          display: flex;
          gap: 12px;
          flex-wrap: wrap;
          align-items: center;
          font-size: 12px;
          color: var(--text-tertiary);
          margin-bottom: 16px;
        }
        .qt-metric-row {
          display: grid;
          grid-template-columns: repeat(4, 1fr);
          gap: 10px;
          margin-bottom: 18px;
        }
        @media (max-width: 720px) {
          .qt-metric-row { grid-template-columns: repeat(2, 1fr); }
        }
        .qt-metric-card {
          background: var(--bg-page, #f5f6f8);
          border-radius: 6px;
          padding: 12px 14px;
        }
        .qt-metric-label { font-size: 12px; color: var(--text-tertiary); margin-bottom: 4px; }
        .qt-metric-value {
          font-size: 22px;
          font-weight: 600;
          color: var(--text-primary);
          line-height: 1.2;
        }
        .qt-metric-change {
          font-size: 12px;
          color: var(--text-tertiary);
          margin-top: 2px;
          display: flex;
          align-items: center;
          gap: 4px;
        }
        .qt-metric-change.delta-up { color: var(--color-success, #16a34a); }
        .qt-metric-change.delta-down { color: var(--color-danger, #dc2626); }
        .qt-metric-change .delta-arrow { font-weight: 600; }
        .qt-detail-compare {
          font-size: 11px;
          color: var(--text-tertiary);
          margin: -10px 0 12px;
          padding-left: 2px;
        }
        .qc-detail-header p {
          margin: 0 0 16px;
          color: var(--text-tertiary);
          font-size: 13px;
        }
        .qc-overview {
          display: grid;
          grid-template-columns: repeat(5, minmax(0, 1fr));
          gap: 12px;
          margin-bottom: 16px;
        }
        .qc-overview-item {
          border: 1px solid var(--border-light, #f0f0f0);
          border-top: 3px solid var(--accent, #1a55e8);
          border-radius: 8px;
          padding: 12px;
          background: #fff;
        }
        .qc-overview-item.qc-self {
          box-shadow: 0 0 0 2px rgba(26, 85, 232, 0.12);
        }
        .qc-name {
          min-height: 22px;
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary);
          display: flex;
          align-items: center;
          gap: 4px;
          flex-wrap: wrap;
        }
        .qc-self-tag {
          display: inline-flex;
          align-items: center;
          height: 20px;
          padding: 0 7px;
          border-radius: 4px;
          background: rgba(26, 85, 232, 0.1);
          color: #1a55e8;
          font-size: 11px;
          font-weight: 500;
          white-space: nowrap;
        }
        .qc-num {
          font-size: 26px;
          font-weight: 700;
          color: var(--accent, #1a55e8);
          margin: 6px 0 2px;
        }
        .qc-label {
          font-size: 12px;
          color: var(--text-tertiary);
        }
        .qc-sub {
          font-size: 12px;
          color: var(--text-secondary);
          margin-top: 2px;
          white-space: nowrap;
        }
        .qc-panel {
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          background: #fff;
          margin-top: 16px;
          overflow: hidden;
        }
        .qc-panel-header {
          padding: 14px 16px 10px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .qc-panel-header h3 {
          margin: 0;
          color: var(--text-primary);
          font-size: 14px;
          font-weight: 600;
        }
        .qc-panel-header p {
          margin: 4px 0 0;
          color: var(--text-tertiary);
          font-size: 12px;
        }
        .qc-table-scroll {
          overflow-x: auto;
        }
        .qc-rank-table {
          min-width: 680px;
        }
        .qc-rank-table th:not(:first-child),
        .qc-rank-table td:not(:first-child) {
          text-align: center;
        }
        .qc-brand-cell {
          display: inline-flex;
          align-items: center;
          gap: 6px;
          white-space: nowrap;
        }
        .qc-brand-dot {
          width: 10px;
          height: 10px;
          border-radius: 50%;
          flex: 0 0 10px;
        }
        .qc-rank {
          display: inline-flex;
          min-width: 24px;
          height: 24px;
          align-items: center;
          justify-content: center;
          border-radius: 6px;
          background: var(--bg-page, #f5f6f8);
          color: var(--text-secondary);
          font-weight: 600;
          font-size: 13px;
        }
        .qc-rank.qc-rank-top {
          background: rgba(26, 85, 232, 0.1);
          color: #1a55e8;
        }
        .qc-answer-list {
          padding: 0 16px;
        }
        .qc-answer-brief {
          padding: 8px 0;
          border-bottom: 1px dashed var(--border-light, #f0f0f0);
          font-size: 13px;
          color: var(--text-secondary);
          line-height: 1.7;
        }
        .qc-answer-brief:last-child {
          border-bottom: none;
        }
        .qc-model-dot {
          display: inline-block;
          width: 8px;
          height: 8px;
          border-radius: 50%;
          margin-right: 6px;
        }
        @media (max-width: 1280px) {
          .qc-overview { grid-template-columns: repeat(3, minmax(0, 1fr)); }
        }
        @media (max-width: 720px) {
          .qc-overview { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        .qt-section { margin-top: 18px; }
        .qt-section h3 {
          margin: 0 0 10px;
          font-size: 14px;
          font-weight: 600;
          color: var(--text-primary);
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .qt-section h3 .badge {
          background: var(--bg-page, #f5f6f8);
          color: var(--text-secondary);
          font-size: 12px;
          font-weight: 500;
          padding: 1px 8px;
          border-radius: 4px;
        }
        .qt-table {
          width: 100%;
          border-collapse: collapse;
          font-size: 13px;
        }
        .qt-table th,
        .qt-table td {
          padding: 10px 12px;
          text-align: left;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
        }
        .qt-table th {
          background: var(--bg-page, #fafafa);
          color: var(--text-secondary);
          font-weight: 500;
          font-size: 12px;
        }
        .qt-rank-pill {
          display: inline-block;
          padding: 2px 10px;
          border-radius: 12px;
          font-size: 12px;
          font-weight: 600;
        }
        .qt-rank-1  { background: #fef3c7; color: #d97706; }
        .qt-rank-3  { background: #dbeafe; color: #1d4ed8; }
        .qt-rank-10 { background: #e0e7ff; color: #4338ca; }
        .qt-rank-other { background: #f3f4f6; color: #6b7280; }
        .qt-status {
          display: inline-block;
          padding: 1px 8px;
          border-radius: 4px;
          font-size: 12px;
          font-weight: 500;
        }
        .qt-status-on { color: #16a34a; background: #dcfce7; }
        .qt-status-pause { color: #6b7280; background: #f3f4f6; }
        .qt-link-btn {
          background: transparent;
          border: 0;
          color: var(--brand-blue, #1a55e8);
          font-size: 13px;
          cursor: pointer;
          padding: 0;
          font-family: inherit;
        }

        /* 查看原文 modal 内的答案高亮 — 蓝/橙/绿对应监控品牌 / 竞品 / 关键词
           (优先级: 监控品牌 > 竞品 > 关键词;前者胜出时不会重复上色)。 */
        .hl-self {
          background: #dbeafe;
          color: #1d4ed8;
          padding: 0 2px;
          border-radius: 3px;
        }
        .hl-competitor {
          background: #fed7aa;
          color: #c2410c;
          padding: 0 2px;
          border-radius: 3px;
        }
        .hl-keyword {
          background: #d9f99d;
          color: #3f6212;
          padding: 0 2px;
          border-radius: 3px;
        }
        /* Markdown rendering of answer_content (via marked → DOMPurify).
           Browser defaults for <table>/<ul>/<blockquote> are too tight
           against the 14px body font, so restore reasonable spacing. */
        .qt-answer-content h1,
        .qt-answer-content h2,
        .qt-answer-content h3,
        .qt-answer-content h4 {
          margin: 18px 0 8px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .qt-answer-content h1 { font-size: 18px; }
        .qt-answer-content h2 { font-size: 16px; }
        .qt-answer-content h3 { font-size: 15px; }
        .qt-answer-content h4 { font-size: 14px; }
        .qt-answer-content p { margin: 6px 0; }
        .qt-answer-content ul,
        .qt-answer-content ol { margin: 6px 0; padding-left: 22px; }
        .qt-answer-content li { margin: 2px 0; }
        .qt-answer-content blockquote {
          margin: 8px 0;
          padding: 6px 12px;
          border-left: 3px solid var(--border-light, #e5e7eb);
          background: var(--bg-page, #fafafa);
          color: var(--text-secondary, #374151);
        }
        .qt-answer-content table {
          border-collapse: collapse;
          margin: 10px 0;
          font-size: 13px;
        }
        .qt-answer-content th,
        .qt-answer-content td {
          border: 1px solid var(--border-light, #e5e7eb);
          padding: 6px 10px;
          text-align: left;
        }
        .qt-answer-content th {
          background: var(--bg-page, #fafafa);
          font-weight: 600;
        }
        .qt-answer-content code {
          background: var(--bg-page, #f5f6f8);
          padding: 0 4px;
          border-radius: 3px;
          font-size: 13px;
        }
        .qt-answer-content img {
          max-width: 100%;
          height: auto;
        }

        /* ----------------------------------------------------------------
         * 2026-08-18 refactor — 顶部子面板 tab + 3 个新右栏段 + 稳定 2x2
         * ---------------------------------------------------------------- */
        .qt-pane-tabs {
          display: flex;
          align-items: center;
          gap: 4px;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          padding: 0 4px;
        }
        .qt-pane-tab {
          padding: 10px 16px;
          font-size: 14px;
          color: var(--text-secondary, #4f4f4f);
          cursor: pointer;
          border-bottom: 2px solid transparent;
          margin-bottom: -1px;
          background: transparent;
          border-left: 0;
          border-right: 0;
          border-top: 0;
        }
        .qt-pane-tab:hover { color: var(--brand-blue, #1a55e8); }
        .qt-pane-tab.active {
          color: var(--brand-blue, #1a55e8);
          border-bottom-color: var(--brand-blue, #1a55e8);
          font-weight: 500;
        }
        .qt-pane-tabs-right {
          margin-left: auto;
          display: flex;
          align-items: center;
        }

        /* AI 摘录 2 列 grid(6 张 = 3 行 × 2 列) */
        .qt-ai-excerpts-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
          margin-top: 12px;
        }
        @media (max-width: 1100px) {
          .qt-ai-excerpts-grid { grid-template-columns: 1fr; }
        }
        .qt-ai-excerpt-card {
          background: var(--bg-page, #f5f6f8);
          border-radius: 6px;
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          gap: 8px;
          min-height: 140px;
        }
        .qt-ai-excerpt-head {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .qt-ai-excerpt-dot {
          width: 8px;
          height: 8px;
          border-radius: 50%;
          display: inline-block;
        }
        .qt-ai-excerpt-name {
          font-weight: 600;
          font-size: 13px;
          color: var(--text-primary, #181818);
        }
        .qt-ai-excerpt-rank {
          margin-left: auto;
          font-size: 12px;
          color: var(--color-success, #52c41a);
          font-weight: 500;
        }
        .qt-ai-excerpt-rank.muted {
          color: var(--text-tertiary, #8c8c8c);
        }
        .qt-ai-excerpt-body {
          font-size: 12.5px;
          line-height: 1.55;
          color: var(--text-secondary, #4f4f4f);
          flex: 1;
          overflow: hidden;
          display: -webkit-box;
          -webkit-line-clamp: 5;
          -webkit-box-orient: vertical;
        }
        .qt-ai-excerpt-empty {
          color: var(--text-tertiary, #8c8c8c);
          font-style: italic;
        }
        .qt-ai-excerpt-link {
          align-self: flex-end;
          background: transparent;
          border: 0;
          color: var(--brand-blue, #1a55e8);
          font-size: 12px;
          cursor: pointer;
          padding: 0;
        }
        .qt-ai-excerpt-link:disabled {
          color: var(--text-tertiary, #8c8c8c);
          cursor: not-allowed;
        }

        /* 时间维度对比 — 2 张卡横向 */
        .qt-time-compare-row {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 12px;
          margin-top: 12px;
        }
        @media (max-width: 1100px) {
          .qt-time-compare-row { grid-template-columns: 1fr; }
        }
        .qt-time-card {
          background: var(--bg-page, #f5f6f8);
          border-radius: 6px;
          padding: 14px 16px;
        }
        .qt-time-card-title {
          font-size: 13px;
          font-weight: 600;
          color: var(--text-primary, #181818);
        }
        .qt-time-card-hint {
          font-size: 11px;
          color: var(--text-tertiary, #8c8c8c);
          margin-top: 2px;
        }
        .qt-time-card-body {
          margin-top: 10px;
          display: flex;
          align-items: baseline;
          gap: 8px;
        }
        .qt-time-card-prev {
          font-size: 14px;
          color: var(--text-tertiary, #8c8c8c);
          text-decoration: line-through;
        }
        .qt-time-card-arrow { color: var(--text-tertiary, #8c8c8c); }
        .qt-time-card-cur {
          font-size: 22px;
          font-weight: 700;
          color: var(--text-primary, #181818);
        }
        .qt-time-card-delta {
          font-size: 12px;
          font-weight: 600;
          margin-left: auto;
        }
        .qt-time-card-delta.up { color: var(--color-success, #52c41a); }
        .qt-time-card-delta.down { color: var(--color-danger, #ff4d4f); }
        .qt-time-card-empty {
          margin-top: 10px;
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
        }

        /* 下钻分析 — chip 网格 */
        .qt-drill-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
          gap: 12px;
          margin-top: 12px;
        }
        .qt-drill-chip {
          background: var(--bg-page, #f5f6f8);
          border: 1px solid var(--border-light, #e8e9ec);
          border-radius: 8px;
          padding: 12px 14px;
          display: flex;
          flex-direction: column;
          align-items: flex-start;
          gap: 4px;
          font-family: inherit;
        }
        .qt-drill-chip-name {
          font-size: 14px;
          font-weight: 600;
          color: var(--text-primary, #181818);
        }
        .qt-drill-chip-count {
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
        }
        .qt-drill-chip-rate {
          font-size: 12px;
          color: var(--color-success, #52c41a);
          font-weight: 500;
        }

        /* 稳定与掉落 2x2 网格 */
        .qt-stable-pane {
          padding: 16px 0 0;
        }
        .qt-stable-filter {
          display: flex;
          align-items: center;
          margin-bottom: 12px;
        }
        .qt-stable-filter-hint {
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
          margin-left: auto;
        }
        .qt-stable-grid {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 16px;
        }
        @media (max-width: 1100px) {
          .qt-stable-grid { grid-template-columns: 1fr; }
        }
        .qt-stable-quad {
          background: #fff;
          border-radius: 8px;
          box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 2px 8px rgba(0,0,0,0.04);
          padding: 16px 18px 14px;
          border-top: 3px solid;
          min-height: 240px;
          display: flex;
          flex-direction: column;
        }
        .qt-stable-quad-green { border-top-color: #52c41a; }
        .qt-stable-quad-orange { border-top-color: #faad14; }
        .qt-stable-quad-gray { border-top-color: #8c8c8c; }
        .qt-stable-quad-blue { border-top-color: #1a55e8; }
        .qt-stable-quad-head {
          display: flex;
          align-items: center;
          gap: 8px;
        }
        .qt-stable-quad-head h3 {
          margin: 0;
          font-size: 15px;
          font-weight: 600;
          color: var(--text-primary, #181818);
        }
        .qt-stable-quad-count {
          font-size: 12px;
          font-weight: 600;
          color: var(--brand-blue, #1a55e8);
          background: rgba(26, 85, 232, 0.08);
          border-radius: 12px;
          padding: 2px 10px;
        }
        .qt-stable-quad-caption {
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
          margin-top: 4px;
        }
        .qt-stable-quad-list {
          margin-top: 12px;
          flex: 1;
          overflow-y: auto;
          min-height: 0;
        }
        .qt-stable-quad-item {
          padding: 6px 0;
          border-bottom: 1px solid var(--border-light, #f0f0f0);
          display: flex;
          flex-direction: column;
          gap: 2px;
        }
        .qt-stable-quad-item:last-child { border-bottom: 0; }
        .qt-stable-quad-item-label {
          font-size: 13px;
          color: var(--text-primary, #181818);
        }
        .qt-stable-quad-item-sub {
          font-size: 11px;
          color: var(--text-tertiary, #8c8c8c);
        }
        .qt-stable-quad-empty {
          font-size: 12px;
          color: var(--text-tertiary, #8c8c8c);
          font-style: italic;
          padding: 16px 0;
          text-align: center;
        }
      `}</style>
    </div>
  );
}

/* -------------------------------------------------------------------------
 * 3 new right-panel sections added in 2026-08-18 refactor:
 *   - AiExcerptsGrid: 6 platform cards × 200 chars each, with a
 *     「查看完整原文」 link that opens the existing 查看原文 modal.
 *   - TimeCompareCard: shows prev% → current% + green ↑ +X% delta.
 *   - DrillDownGrid: project-level category roll-up; read-only —
 *     chips are pure display after the 2026-08-18 cleanup removed
 *     the category sub-tabs.
 * ---------------------------------------------------------------------- */

function AiExcerptsGrid({
  excerpts,
  platforms,
  onOpenFull,
}: {
  excerpts: Record<string, PlatformExcerpt | null>;
  platforms: string[];
  onOpenFull: (platform: string, runId: string | null) => void;
}) {
  if (platforms.length === 0) {
    return (
      <Empty
        description="该项目暂未配置任何模型"
        style={{ padding: 24 }}
      />
    );
  }
  return (
    <div className="qt-ai-excerpts-grid">
      {platforms.map((plat) => {
        const ex = excerpts[plat] ?? null;
        return (
          <div key={plat} className="qt-ai-excerpt-card">
            <div className="qt-ai-excerpt-head">
              <i
                className="qt-ai-excerpt-dot"
                style={{ background: platformColor(plat) }}
              />
              <span className="qt-ai-excerpt-name">{platformLabel(plat)}</span>
              {ex?.rank !== null && ex?.rank !== undefined ? (
                <span className="qt-ai-excerpt-rank">排名 No.{ex.rank}</span>
              ) : (
                <span className="qt-ai-excerpt-rank muted">未上榜</span>
              )}
            </div>
            <div className="qt-ai-excerpt-body">
              {ex?.excerpt ? (
                ex.excerpt
              ) : (
                <span className="qt-ai-excerpt-empty">暂无原文</span>
              )}
            </div>
            <button
              type="button"
              className="qt-ai-excerpt-link"
              onClick={() => onOpenFull(plat, ex?.run_id ?? null)}
              disabled={!ex?.run_id}
            >
              查看完整原文 →
            </button>
          </div>
        );
      })}
    </div>
  );
}

function TimeCompareCard({
  title,
  hint,
  current,
  prev,
}: {
  title: string;
  hint: string;
  current: number;
  prev: number | null;
}) {
  // Delta = (current - prev) / prev. Pct points (not relative) when
  // both are rates: the design mockup shows `+3.2%` style numbers,
  // not a relative growth — that matches what an operator wants to
  // see on a 0-100% KPI.
  const hasPrev = prev !== null && prev !== undefined;
  const delta = hasPrev ? current - (prev as number) : null;
  const up = delta !== null && delta >= 0;
  return (
    <div className="qt-time-card">
      <div className="qt-time-card-title">{title}</div>
      <div className="qt-time-card-hint">{hint}</div>
      {hasPrev ? (
        <div className="qt-time-card-body">
          <span className="qt-time-card-prev">{pct(prev as number)}</span>
          <span className="qt-time-card-arrow">→</span>
          <span className="qt-time-card-cur">{pct(current)}</span>
          <span className={`qt-time-card-delta ${up ? "up" : "down"}`}>
            {up ? "↑" : "↓"} {Math.abs((delta as number) * 100).toFixed(1)}%
          </span>
        </div>
      ) : (
        <div className="qt-time-card-empty">该窗口暂无数据,无法对比</div>
      )}
    </div>
  );
}

function DrillDownGrid({
  categorySummary,
}: {
  categorySummary: import("../../api/projects").CategoryStat[];
}) {
  if (categorySummary.length === 0) {
    return (
      <Empty
        description="该时间窗口内没有分类数据"
        style={{ padding: 24 }}
      />
    );
  }
  return (
    <div className="qt-drill-grid">
      {categorySummary.map((s) => {
        const label = s.category ?? "未分类";
        return (
          <div
            key={label}
            className="qt-drill-chip"
          >
            <span className="qt-drill-chip-name">{label}</span>
            <span className="qt-drill-chip-count">{s.prompt_count} 个问题</span>
            <span className="qt-drill-chip-rate">提及率 {pct(s.mention_rate)}</span>
          </div>
        );
      })}
    </div>
  );
}

/* -------------------------------------------------------------------------
 * StablePane — 2×2 四宫格视图,每个宫显示一类问题列表。
 * 标题纯展示,不绑 onClick(用户确认不需要跳转)。
 * ---------------------------------------------------------------------- */

function StablePane({
  data,
  loading,
  platformLabel: _platformLabel,
}: {
  data: QuestionStatusChangesOut | null;
  loading: boolean;
  platformLabel: (raw: string) => string;
}) {
  if (loading) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }
  if (!data) {
    return <Empty description="暂无数据" style={{ padding: 60 }} />;
  }

  return (
    <div className="qt-stable-pane">
      <div className="qt-stable-filter">
        <span className="qt-stable-filter-hint">
          判定窗口 {data.start} ~ {data.end};「上榜」= 窗口内被任一模型提及过
        </span>
      </div>

      <div className="qt-stable-grid">
        <StableQuadrant
          tone="green"
          title="稳定的问题"
          caption="连续 2 个窗口都至少被 1 个模型提及"
          items={data.stable.map((it) => ({
            key: `stable-${it.prompt_id}`,
            label: it.prompt,
            sub: it.platforms.map(_platformLabel).join(" · "),
          }))}
        />
        <StableQuadrant
          tone="orange"
          title="掉落分析"
          caption="上一窗口被提及,本窗口掉出 Top3 或消失(按事件)"
          items={data.drops.map((d) => ({
            key: `drop-${d.prompt_id}-${d.platform}-${d.dropped_day}`,
            label: d.prompt,
            sub: `${_platformLabel(d.platform)} · ${d.dropped_day} · ${d.reason ?? ""}`,
          }))}
        />
        <StableQuadrant
          tone="gray"
          title="从未上榜"
          caption="两个窗口内都未被任何模型提及"
          items={data.never_listed.map((it) => ({
            key: `never-${it.prompt_id}`,
            label: it.prompt,
            sub: it.category ?? "未分类",
          }))}
        />
        <StableQuadrant
          tone="blue"
          title="上榜的提及问题"
          caption="本窗口内被至少 1 个模型提过(不含 dropped)"
          items={data.listed.map((it) => ({
            key: `listed-${it.prompt_id}`,
            label: it.prompt,
            sub: it.platforms.map(_platformLabel).join(" · "),
          }))}
        />
      </div>
    </div>
  );
}

function StableQuadrant({
  tone,
  title,
  caption,
  items,
}: {
  tone: "green" | "orange" | "gray" | "blue";
  title: string;
  caption: string;
  items: { key: string; label: string; sub: string }[];
}) {
  return (
    <div className={`qt-stable-quad qt-stable-quad-${tone}`}>
      <div className="qt-stable-quad-head">
        <h3>{title}</h3>
        <span className="qt-stable-quad-count">{items.length}</span>
      </div>
      <div className="qt-stable-quad-caption">{caption}</div>
      <div className="qt-stable-quad-list">
        {items.length === 0 ? (
          <div className="qt-stable-quad-empty">窗口内暂无相关问题</div>
        ) : (
          items.map((it) => (
            <div key={it.key} className="qt-stable-quad-item">
              <span className="qt-stable-quad-item-label">{it.label}</span>
              {it.sub && <span className="qt-stable-quad-item-sub">{it.sub}</span>}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function CompetitorDetail({
  stat,
  item,
  brands,
  platforms,
}: {
  stat: QuestionStat;
  item: QuestionAnalyticsItem | null;
  brands: CompetitorBrandStat[];
  platforms: string[];
}) {
  const modelColumns = useMemo(() => {
    const keys = new Set(platforms);
    brands.forEach((brand) => {
      Object.keys(brand.model_ranks).forEach((platform) => keys.add(platform));
    });
    return Array.from(keys);
  }, [brands, platforms]);
  const rankedBrands = useMemo(
    () =>
      [...brands].sort(
        (left, right) => (left.avg_rank ?? 99) - (right.avg_rank ?? 99),
      ),
    [brands],
  );
  const summaries = modelColumns
    .map((platform) => ({ platform, excerpt: item?.excerpts[platform]?.excerpt }))
    .filter((entry) => entry.excerpt);

  return (
    <div className="qt-detail-body qc-detail">
      <div className="qt-detail-header qc-detail-header">
        <h2>{stat.prompt}</h2>
        <p>自身品牌 vs 竞品在各模型回答中的提及率与推荐位次</p>
      </div>

      {brands.length === 0 ? (
        <Empty description="该问题暂无自身品牌与竞品对比数据" style={{ padding: 48 }} />
      ) : (
        <>
          <div className="qc-overview">
            {brands.map((brand) => (
              <div
                key={brand.brand_canonical}
                className={`qc-overview-item${brand.is_self ? " qc-self" : ""}`}
                style={{ "--accent": brand.color } as CSSProperties}
              >
                <div className="qc-name">
                  {brand.brand_canonical}
                  {brand.is_self && <span className="qc-self-tag">自身</span>}
                </div>
                <div className="qc-num">{pct(brand.mention_rate)}</div>
                <div className="qc-label">提及率</div>
                <div className="qc-sub">
                  Top1 {pct(brand.top1_rate)} · Top3 {pct(brand.top3_rate)}
                </div>
                <div className="qc-sub">
                  平均位次 {brand.avg_rank === null ? "—" : `No.${brand.avg_rank.toFixed(1)}`}
                </div>
              </div>
            ))}
          </div>

          <div className="qc-panel">
            <div className="qc-panel-header">
              <h3>各模型中的品牌位次</h3>
              <p>数字为该模型答案中品牌的推荐名次</p>
            </div>
            <div className="qc-table-scroll">
              <table className="qt-table qc-rank-table">
                <thead>
                  <tr>
                    <th>品牌</th>
                    {modelColumns.map((platform) => (
                      <th key={platform}>{platformLabel(platform)}</th>
                    ))}
                    <th>综合位次</th>
                  </tr>
                </thead>
                <tbody>
                  {rankedBrands.map((brand) => (
                    <tr key={brand.brand_canonical}>
                      <td>
                        <span className="qc-brand-cell">
                          <span
                            className="qc-brand-dot"
                            style={{ background: brand.color }}
                          />
                          <strong>{brand.brand_canonical}</strong>
                          {brand.is_self && <span className="qc-self-tag">自身</span>}
                        </span>
                      </td>
                      {modelColumns.map((platform) => {
                        const rank = brand.model_ranks[platform];
                        return (
                          <td key={platform}>
                            <span className={`qc-rank${rank === 1 ? " qc-rank-top" : ""}`}>
                              {rank ?? "—"}
                            </span>
                          </td>
                        );
                      })}
                      <td>
                        <strong>
                          {brand.avg_rank === null ? "—" : `No.${brand.avg_rank.toFixed(1)}`}
                        </strong>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="qc-panel">
            <div className="qc-panel-header">
              <h3>答案摘要</h3>
              <p>该问题下各模型对品牌的推荐表述</p>
            </div>
            <div className="qc-answer-list">
              {summaries.length === 0 ? (
                <Empty description="暂无答案摘要" style={{ padding: 24 }} />
              ) : (
                summaries.map(({ platform, excerpt }, index) => (
                  <div key={platform} className="qc-answer-brief">
                    <span
                      className="qc-model-dot"
                      style={{ background: platformColor(platform, index) }}
                    />
                    <strong>{platformLabel(platform)}</strong> — {excerpt}
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function QuestionDetail({
  stat,
  item,
  totalPlatforms,
  onViewOriginal,
  prevWindowLabel,
  prevLongLabel,
  categorySummary,
  view,
}: {
  stat: QuestionStat;
  item: QuestionAnalyticsItem | null;
  totalPlatforms: number;
  onViewOriginal: (promptId: number, platform: string) => void;
  prevWindowLabel: string;
  prevLongLabel: string;
  categorySummary: import("../../api/projects").CategoryStat[];
  view: "self" | "competitor";
}) {
  // Platforms to render AI excerpt cards for. The user spec calls for
  // "6 models each" — the actual count comes from whichever platforms
  // produced an excerpt for this prompt in the current window, not the
  // project's configured platforms (which can be smaller). Sorted for
  // stable order so the same card layout shows up across reloads.
  const excerptPlatforms = Object.keys(item?.excerpts ?? {}).sort();
  return (
    <div className="qt-detail-body">
      <div className="qt-detail-header">
        <h2>{stat.prompt}</h2>
        <div className="qt-detail-meta">
          {stat.category && <Tag color={colorFor(stat.category)}>{stat.category}</Tag>}
          <span>
            共 {num(stat.totalMentions)} 次提及 · 覆盖 {stat.coverage}/{totalPlatforms || 7} 个模型
          </span>
          <span>状态:{stat.status}</span>
        </div>
        <div className="qt-detail-compare">较上一周期 {prevWindowLabel}</div>
      </div>

      <div className="qt-metric-row">
        <div className="qt-metric-card">
          <div className="qt-metric-label">{view === "competitor" ? "竞品提及率" : "提及率"}</div>
          <div className="qt-metric-value">{pct(stat.mentionRate)}</div>
          <DeltaRow
            current={stat.mentionRate}
            prev={stat.prev?.mentionRate}
            format="rate"
          />
        </div>
        <div className="qt-metric-card">
          <div className="qt-metric-label">{view === "competitor" ? "竞品 Top1 率" : "Top1 率"}</div>
          <div className="qt-metric-value">{pct(stat.top1Rate)}</div>
          <DeltaRow
            current={stat.top1Rate}
            prev={stat.prev?.top1Rate}
            format="rate"
          />
        </div>
        <div className="qt-metric-card">
          <div className="qt-metric-label">{view === "competitor" ? "竞品 Top3 率" : "Top3 率"}</div>
          <div className="qt-metric-value">{pct(stat.top3Rate)}</div>
          <DeltaRow
            current={stat.top3Rate}
            prev={stat.prev?.top3Rate}
            format="rate"
          />
        </div>
        <div className="qt-metric-card">
          <div className="qt-metric-label">{view === "competitor" ? "竞品平均排名" : "平均排名"}</div>
          <div className="qt-metric-value">
            {stat.rankAvg !== null ? `No.${stat.rankAvg.toFixed(1)}` : "—"}
          </div>
          <DeltaRow
            current={stat.rankAvg}
            prev={stat.prev?.rankAvg}
            format="rank"
          />
        </div>
      </div>

      <div className="qt-section qt-table-wrap">
        <h3>
          模型对比
          <span className="badge">{stat.models.length} 个模型</span>
        </h3>
        {stat.models.length === 0 ? (
          <Empty description="该问题暂未被任何模型提及" style={{ padding: 24 }} />
        ) : (
          <table className="qt-table">
            <thead>
              <tr>
                <th>大模型</th>
                <th>排名位置</th>
                <th>提及次数</th>
                <th>情感倾向</th>
                <th>推荐状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {stat.models.map((m) => {
                const sc = m.avg_sentiment;
                // avg_sentiment comes from the API as the float average of
                // the Molizhishu sentiment labels (positive=1.0, neutral=0.5,
                // negative=0.0). Translate back to a label so the operator
                // sees the discrete verdict rather than a number.
                const sLabel =
                  sc === null
                    ? "—"
                    : sc >= 0.66
                    ? "正面"
                    : sc >= 0.33
                    ? "中性"
                    : "负面";
                const sColor =
                  sc === null
                    ? "var(--text-tertiary)"
                    : sc >= 0.66
                    ? "#059669"
                    : sc >= 0.33
                    ? "#64748B"
                    : "#DC2626";
                return (
                  <tr key={m.platform}>
                    <td>
                      {m.platform}
                      {view === "competitor" && m.brand_canonical && (
                        <Tag color="orange" style={{ marginLeft: 6 }}>
                          {m.brand_canonical}
                        </Tag>
                      )}
                    </td>
                    <td>
                      <span className={`qt-rank-pill ${rankClass(m.best_rank)}`}>
                        {m.best_rank !== null ? `No.${m.best_rank}` : "未提及"}
                      </span>
                    </td>
                    <td>
                      <strong>{m.matched}</strong>
                      <span style={{ color: "var(--text-tertiary)", marginLeft: 4 }}>
                        / {m.total} 次提及
                      </span>
                    </td>
                    <td style={{ color: sColor, fontWeight: 600 }}>
                      {sLabel}
                    </td>
                    <td>
                      {m.recommend_yes ? (
                        <span className="qt-status qt-status-on">推荐</span>
                      ) : (
                        <span className="qt-status qt-status-pause">未推荐</span>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className="qt-link-btn"
                        onClick={() => onViewOriginal(stat.promptId, m.platform)}
                      >
                        查看原文
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="qt-section qt-ai-excerpts" style={{ marginTop: 18 }}>
        <h3>
          AI 回答原文摘录
          <span className="badge">{excerptPlatforms.length} 个模型 · 截取前 200 字</span>
        </h3>
        <AiExcerptsGrid
          excerpts={item?.excerpts ?? {}}
          platforms={excerptPlatforms}
          onOpenFull={(platform, runId) => {
            if (!runId) {
              message.info("暂无完整原文可查看");
              return;
            }
            onViewOriginal(stat.promptId, platform);
          }}
        />
      </div>

      <div className="qt-section qt-time-compare" style={{ marginTop: 18 }}>
        <h3>时间维度对比</h3>
        <div className="qt-time-compare-row">
          <TimeCompareCard
            title="本周 vs 上周"
            hint={prevWindowLabel}
            current={stat.mentionRate}
            prev={stat.prev?.mentionRate ?? null}
          />
          <TimeCompareCard
            title="本月 vs 上月"
            hint={prevLongLabel}
            current={stat.mentionRate}
            prev={item?.long_prev?.mention_rate ?? null}
          />
        </div>
      </div>

      <div className="qt-section qt-drill" style={{ marginTop: 18 }}>
        <h3>下钻分析</h3>
        <DrillDownGrid categorySummary={categorySummary} />
      </div>
    </div>
  );
}

/** One AI answer inside the 查看原文 list modal.
 *
 *  - 短回答(<= PREVIEW_CHARS)直接展示,高亮常驻
 *  - 长回答默认截断到 PREVIEW_CHARS,点「展开全部(N 字)」弹出
 *    嵌套的 FullAnswerModal 来读全文 + thinking + 图片 + 引用
 *    —— 不就地展开,因为真实环境抓回来的内容会很长(动辄上千字
 *    + 多张图片 + 引用源),就地展开会把列表卡撑得没法用。
 */
function AnswerCard({
  ans,
  groups,
  onOpenFull,
}: {
  ans: PromptAnswerOut;
  groups: HighlightGroup[];
  onOpenFull: (ans: PromptAnswerOut) => void;
}) {
  const failed = ans.status && /failed|error|stopped/i.test(ans.status);
  const content = ans.answer_content ?? "";
  const isLong = content.length > PREVIEW_CHARS;
  const display = isLong ? content.slice(0, PREVIEW_CHARS) + "…" : content;

  return (
    <div
      style={{
        background: "#fff",
        border: "1px solid var(--border-light, #e5e7eb)",
        borderRadius: 6,
        padding: 12,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 12,
          color: "var(--text-tertiary)",
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <Tag color="blue" style={{ margin: 0 }}>
          {platformLabel(ans.platform ?? "?")}
        </Tag>
        <Tag style={{ margin: 0 }}>{ans.mode ?? "?"}</Tag>
        <span>
          {ans.created_local_at
            ? dayjs(ans.created_local_at).format("MM-DD HH:mm")
            : ""}
        </span>
        {ans.status && (
          <span
            style={{
              color: failed ? "#dc2626" : "var(--text-tertiary)",
              fontWeight: 500,
            }}
          >
            {ans.status}
          </span>
        )}
      </div>
      {ans.error_message ? (
        <div
          style={{
            fontSize: 13,
            color: "#dc2626",
            background: "#fef2f2",
            padding: "8px 10px",
            borderRadius: 4,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {ans.error_message}
        </div>
      ) : ans.answer_content ? (
        <>
          <div
            style={{
              fontSize: 13,
              lineHeight: 1.6,
              color: "var(--text-primary)",
              whiteSpace: "pre-wrap",
              wordBreak: "break-word",
              background: "var(--bg-page, #fafafa)",
              padding: "10px 12px",
              borderRadius: 4,
            }}
          >
            {isLong ? display : highlightText(display, groups)}
          </div>
          {isLong && (
            <button
              type="button"
              className="qt-link-btn"
              onClick={() => onOpenFull(ans)}
              style={{ marginTop: 6, fontSize: 12 }}
            >
              展开全部
            </button>
          )}
        </>
      ) : (
        <div style={{ fontSize: 13, color: "var(--text-tertiary)" }}>
          (此回答无文本内容)
        </div>
      )}
    </div>
  );
}

/* -------------------------------------------------------------------------- */
/* Full-answer modal                                                          */
/* -------------------------------------------------------------------------- */

function pickString(value: unknown, ...keys: string[]): string | null {
  if (!value || typeof value !== "object") return null;
  const obj = value as Record<string, unknown>;
  for (const k of keys) {
    const v = obj[k];
    if (typeof v === "string" && v.trim()) return v;
  }
  return null;
}

/** Walk an arbitrary JSON value and collect every "thinking-like" string.
 *
 *  Used to flatten the per-platform ``reasoning_process`` shape — Molizhishu
 *  gives us ``{steps: [{content: "..."}]}`` while the LLM-mode tool path may
 *  return a flat string or a list of strings. We don't try to be clever; we
 *  just hoist anything that reads like prose. */
function flattenReasoning(node: unknown, out: string[] = []): string[] {
  if (node == null) return out;
  if (typeof node === "string") {
    const t = node.trim();
    if (t) out.push(t);
    return out;
  }
  if (Array.isArray(node)) {
    node.forEach((n) => flattenReasoning(n, out));
    return out;
  }
  if (typeof node === "object") {
    const obj = node as Record<string, unknown>;
    [
      "content",
      "text",
      "reasoning",
      "thinking",
      "message",
      "delta",
    ].forEach((k) => {
      if (k in obj) flattenReasoning(obj[k], out);
    });
  }
  return out;
}

function pickMediaUrl(item: Record<string, unknown>): string | null {
  return pickString(item, "url", "src", "imageUrl", "image_url");
}

function pickRecommendedText(item: string | Record<string, unknown>): string {
  if (typeof item === "string") return item;
  const s = pickString(item, "question", "text", "title", "content");
  if (s) return s;
  // Last resort — pretty-print the object so the operator at least sees
  // the shape; better than dropping the entry on the floor.
  try {
    return JSON.stringify(item, null, 2);
  } catch {
    return String(item);
  }
}

/** Full-content modal: renders the verbatim answer as sanitized HTML
 *  (yuanbao in particular embeds <div class="media-*"> cards for videos
 *  / images / links the operator wants to see) plus everything the
 *  upstream platform attached — thinking trace, embedded media, citation
 *  list, recommended follow-up questions. The body is HTML, so the
 *  brand / competitor / keyword highlight that the list-preview card
 *  uses doesn't apply here — operators reading the full text can search
 *  for the brand manually. */
function FullAnswerModal({
  ans,
  groups,
  loading,
  onClose,
}: {
  ans: PromptAnswerDetailOut | null;
  groups: HighlightGroup[];
  loading: boolean;
  onClose: () => void;
}) {
  if (loading || !ans) {
    return (
      <Modal open footer={null} onCancel={onClose} centered={false} title="加载完整回答...">
        <div style={{ textAlign: "center", padding: 48 }}>
          <Spin />
        </div>
      </Modal>
    );
  }
  const failed = ans.status && /failed|error|stopped/i.test(ans.status);
  const content = ans.answer_content ?? "";
  const reasoning = flattenReasoning(ans.reasoning_process);
  const media = (ans.media_content ?? []).filter(
    (m): m is Record<string, unknown> => !!m && typeof m === "object",
  );
  const refs = (ans.reference_list ?? []).filter(
    (r): r is Record<string, unknown> => !!r && typeof r === "object",
  );
  // citation_list is mixed: most platforms store plain URL strings,
  // yuanbao stores structured {url, title, site, ...} dicts. Split the
  // two so each gets rendered with the right shape.
  const citationStrings = (ans.citation_list ?? []).filter(
    (c): c is string => typeof c === "string" && c.length > 0,
  );
  const citationObjs = (ans.citation_list ?? []).filter(
    (c): c is Record<string, unknown> => !!c && typeof c === "object",
  );
  const citations = [...citationObjs, ...citationStrings.map((url) => ({ url }))];
  const recommended = ans.recommended_questions ?? [];

  return (
    <Modal
      open
      onCancel={onClose}
      footer={null}
      width={1024}
      centered={false}
      style={{ top: 24 }}
      // Same flex-based layout as 查看原文: cap the *content* at
      // ``100vh - 24px`` so the modal fits exactly inside antd's
      // full-viewport .ant-modal-wrap (which is overflow: auto, so even
      // a 1px overshoot lights up a page-edge scrollbar), and let the
      // body expand to fill the space below the header via ``flex: 1``.
      styles={{
        wrapper: { overflow: "hidden" },
        content: {
          maxHeight: "calc(100vh - 24px)",
          display: "flex",
          flexDirection: "column",
        },
        body: {
          flex: 1,
          minHeight: 0,
          overflowY: "auto",
          padding: 16,
        },
      }}
      title={
        <div>
          <div style={{ fontSize: 16, fontWeight: 600 }}>
            完整原文
            <Tag color="blue" style={{ marginLeft: 8 }}>
              {platformLabel(ans.platform ?? "?")}
            </Tag>
            <Tag style={{ marginLeft: 4 }}>{ans.mode ?? "?"}</Tag>
          </div>
          <div
            style={{
              marginTop: 6,
              fontSize: 12,
              color: "var(--text-tertiary)",
              fontWeight: 400,
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
            }}
          >
            <span>
              {ans.created_local_at
                ? dayjs(ans.created_local_at).format("YYYY-MM-DD HH:mm")
                : ""}
            </span>
            {ans.status && (
              <span style={{ color: failed ? "#dc2626" : undefined, fontWeight: 500 }}>
                {ans.status}
              </span>
            )}
            {ans.page_screenshot && (
              <a href={ans.page_screenshot} target="_blank" rel="noreferrer">
                <LinkOutlined /> 截图
              </a>
            )}
            <span style={{ color: "var(--text-quaternary)" }}>
              subtask {ans.subtask_id.slice(0, 8)}…
            </span>
          </div>
        </div>
      }
      destroyOnClose
    >
      {ans.error_message ? (
        <div
          style={{
            fontSize: 13,
            color: "#dc2626",
            background: "#fef2f2",
            padding: "8px 10px",
            borderRadius: 4,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {ans.error_message}
        </div>
      ) : (
        <>
          <FullSection title="正文">
            <div
              className="qt-answer-content"
              style={{
                fontSize: 14,
                lineHeight: 1.7,
                color: "var(--text-primary)",
                wordBreak: "break-word",
              }}
              // Pipeline: answer_content from the upstream LLM platform
              // is mixed Markdown + HTML — yuanbao in particular returns
              // prose with ## headers / tables / lists / **bold** plus
              // embedded <div class="media-*"> cards for videos and
              // images. ``renderAnswerHtml`` wraps the brand / competitor
              // / keyword tokens with their hl-* colour spans first,
              // then ``marked`` turns Markdown into HTML while leaving
              // the spans and yuanbao's media cards alone, then
              // ``DOMPurify`` strips anything dangerous (``<script>``,
              // ``on*`` handlers, ``javascript:`` URLs) — enough for the
              // LLM-output threat model where an attacker would need to
              // compromise the model's response, not the page.
              dangerouslySetInnerHTML={{
                __html: renderAnswerHtml(content, groups),
              }}
            />
          </FullSection>

          {reasoning.length > 0 && (
            <FullSection
              title={`思考过程 (${reasoning.length} 步)`}
              hint="thinking / reasoning trace"
            >
              <div
                style={{
                  fontSize: 13,
                  lineHeight: 1.65,
                  color: "var(--text-secondary)",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  background: "var(--bg-page, #f5f6f8)",
                  padding: "12px 14px",
                  borderRadius: 4,
                }}
              >
                {reasoning.map((seg, i) => (
                  <div
                    key={i}
                    style={{
                      paddingBottom: i === reasoning.length - 1 ? 0 : 10,
                      marginBottom: i === reasoning.length - 1 ? 0 : 10,
                      borderBottom:
                        i === reasoning.length - 1
                          ? "none"
                          : "1px dashed var(--border-light, #e5e7eb)",
                    }}
                  >
                    <div
                      style={{
                        fontSize: 11,
                        color: "var(--text-quaternary)",
                        marginBottom: 4,
                      }}
                    >
                      step {i + 1}
                    </div>
                    {seg}
                  </div>
                ))}
              </div>
            </FullSection>
          )}

          {media.length > 0 && (
            <FullSection title={`媒体内容 (${media.length})`}>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
                  gap: 8,
                }}
              >
                {media.map((m, i) => {
                  const url = pickMediaUrl(m);
                  const type = pickString(m, "type", "mime", "mimeType") ?? "image";
                  if (!url) {
                    return (
                      <div
                        key={i}
                        style={{
                          padding: 10,
                          border: "1px solid var(--border-light, #e5e7eb)",
                          borderRadius: 4,
                          fontSize: 12,
                          color: "var(--text-tertiary)",
                        }}
                      >
                        媒体项 #{i + 1}(无 url)
                        <pre
                          style={{
                            margin: "6px 0 0",
                            fontSize: 11,
                            whiteSpace: "pre-wrap",
                            wordBreak: "break-word",
                            color: "var(--text-quaternary)",
                          }}
                        >
                          {JSON.stringify(m, null, 2)}
                        </pre>
                      </div>
                    );
                  }
                  return (
                    <a
                      key={i}
                      href={url}
                      target="_blank"
                      rel="noreferrer"
                      style={{
                        display: "block",
                        border: "1px solid var(--border-light, #e5e7eb)",
                        borderRadius: 4,
                        overflow: "hidden",
                        background: "var(--bg-page, #fafafa)",
                      }}
                    >
                      {type.startsWith("image") ? (
                        <img
                          src={url}
                          alt=""
                          style={{
                            width: "100%",
                            height: 120,
                            objectFit: "cover",
                            display: "block",
                          }}
                        />
                      ) : (
                        <div
                          style={{
                            padding: 12,
                            fontSize: 12,
                            color: "var(--text-secondary)",
                          }}
                        >
                          {type} 媒体
                        </div>
                      )}
                      <div
                        style={{
                          padding: "6px 8px",
                          fontSize: 11,
                          color: "var(--text-tertiary)",
                          wordBreak: "break-all",
                        }}
                      >
                        {url}
                      </div>
                    </a>
                  );
                })}
              </div>
            </FullSection>
          )}

          {(refs.length > 0 || citations.length > 0) && (
            <FullSection
              title={`引用源 (${refs.length || citations.length})`}
              hint="referenceList / citationList"
            >
              {refs.length > 0 && (
                <ul
                  style={{
                    margin: 0,
                    paddingLeft: 18,
                    fontSize: 13,
                    lineHeight: 1.7,
                  }}
                >
                  {refs.map((r, i) => {
                    const url = pickString(r, "url", "link") ?? "";
                    const title = pickString(r, "title", "name") ?? url ?? `引用 ${i + 1}`;
                    const site =
                      pickString(r, "site", "domain", "host") ??
                      (url ? safeHostname(url) : "");
                    return (
                      <li key={i} style={{ marginBottom: 4 }}>
                        <a href={url} target="_blank" rel="noreferrer">
                          {title}
                        </a>
                        {site && (
                          <span
                            style={{
                              color: "var(--text-quaternary)",
                              marginLeft: 6,
                              fontSize: 12,
                            }}
                          >
                            ({site})
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
              {refs.length === 0 && citations.length > 0 && (
                <ul
                  style={{
                    margin: 0,
                    paddingLeft: 18,
                    fontSize: 13,
                    lineHeight: 1.7,
                  }}
                >
                  {citations.map((c, i) => {
                    const url = pickString(c, "url", "link") ?? "";
                    const title = pickString(c, "title", "name") ?? url ?? `引用 ${i + 1}`;
                    const site =
                      pickString(c, "site", "domain", "host") ??
                      (url ? safeHostname(url) : "");
                    return (
                      <li key={i} style={{ marginBottom: 4 }}>
                        <a href={url} target="_blank" rel="noreferrer">
                          {title}
                        </a>
                        {site && (
                          <span
                            style={{
                              color: "var(--text-quaternary)",
                              marginLeft: 6,
                              fontSize: 12,
                            }}
                          >
                            ({site})
                          </span>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}
            </FullSection>
          )}

          {recommended.length > 0 && (
            <FullSection
              title={`推荐问题 (${recommended.length})`}
              hint="recommendedQuestions"
            >
              <ul
                style={{
                  margin: 0,
                  paddingLeft: 18,
                  fontSize: 13,
                  lineHeight: 1.7,
                }}
              >
                {recommended.map((q, i) => (
                  <li key={i} style={{ marginBottom: 4 }}>
                    {pickRecommendedText(q)}
                  </li>
                ))}
              </ul>
            </FullSection>
          )}

          {!content && reasoning.length === 0 && media.length === 0 &&
            refs.length === 0 && citations.length === 0 &&
            recommended.length === 0 && (
              <div
                style={{
                  padding: 24,
                  textAlign: "center",
                  color: "var(--text-tertiary)",
                  fontSize: 13,
                }}
              >
                此回答没有任何结构化内容
              </div>
            )}
        </>
      )}
    </Modal>
  );
}

function FullSection({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
}) {
  return (
    <div className="qt-section" style={{ marginTop: 18 }}>
      <h3
        style={{
          margin: "0 0 10px",
          fontSize: 14,
          fontWeight: 600,
          color: "var(--text-primary)",
          display: "flex",
          alignItems: "baseline",
          gap: 8,
        }}
      >
        {title}
        {hint && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 400,
              color: "var(--text-quaternary)",
            }}
          >
            {hint}
          </span>
        )}
      </h3>
      {children}
    </div>
  );
}

function safeHostname(url: string): string {
  try {
    return new URL(url).hostname;
  } catch {
    return "";
  }
}