/**
 * 全屏报告预览页 —— 出版物阅读器风格,多章节。
 *
 * 数据:GET /api/reports/{report_id} 返回结构化 JSON,
 *      不依赖 GlobalToolbar(按 spec §3.4)。
 * 渲染:React 直接渲染,套用 SPA 视觉 token(spec §3.5),
 *      不用 iframe / dangerouslySetInnerHTML。
 * 章节:与 docs/参芪十一味颗粒-GEO周报-20260814.pdf 对齐 ——
 *      头部 + 一 / 二 / 三 / 四 / 五 / 5.3 + 页脚。
 *      数据缺失的章节保留标题 + 「暂无数数据」占位。
 * 打印:浏览器原生 window.print()。
 */

import { useEffect, useState } from "react";
import { Alert, Button, Input, Skeleton, Space, message } from "antd";
import { useNavigate, useParams } from "react-router-dom";
import {
  getReportSnapshot,
  publishReport,
  unpublishReport,
  updateReport,
  type Report,
  type ReportSnapshotOut,
} from "../../api/reports";
import "./ReportPreview.css";

// ----- Helpers (re-exported for PublicReportPreview) -----

export function pct(rate: number | null | undefined): string {
  if (rate === null || rate === undefined) return "—";
  return `${(rate * 100).toFixed(2)}%`;
}

export function pp(delta: number | null | undefined): string {
  if (delta === null || delta === undefined) return "—";
  const v = delta * 100;
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}pp`;
}

export function deltaClass(delta: number | null | undefined): "up" | "down" | "flat" {
  if (delta === null || delta === undefined) return "flat";
  if (delta > 0.0005) return "up";
  if (delta < -0.0005) return "down";
  return "flat";
}

function truncate(s: string, n: number): string {
  return s.length <= n ? s : s.slice(0, n - 1) + "…";
}

// ----- Page component -----

export default function ReportPreview() {
  const params = useParams<{ id: string; reportId: string }>();
  const navigate = useNavigate();
  const projectId = params?.id ?? "";
  const reportId = Number(params?.reportId);
  const [data, setData] = useState<ReportSnapshotOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!reportId) {
      setLoading(false);
      setError("链接无效");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getReportSnapshot(reportId)
      .then((d) => {
        if (!cancelled) setData(d);
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
  }, [reportId]);

  const [publishing, setPublishing] = useState(false);

  const saveDraft = async (overrides: Record<string, string | null>) => {
    try {
      await updateReport(reportId, overrides);
      message.success("草稿已保存");
      // Refresh snapshot so the rendered values reflect the new overrides.
      const fresh = await getReportSnapshot(reportId);
      setData(fresh);
    } catch (err) {
      message.error((err as Error).message || "保存失败");
    }
  };

  const publish = async () => {
    setPublishing(true);
    try {
      const updated: Report = await publishReport(reportId);
      message.success("已发布");
      setData((prev) => (prev ? { ...prev, meta: updated } : prev));
    } catch (err) {
      message.error((err as Error).message || "发布失败");
    } finally {
      setPublishing(false);
    }
  };

  const unpublish = async () => {
    setPublishing(true);
    try {
      const updated: Report = await unpublishReport(reportId);
      message.success("已取消发布");
      setData((prev) => (prev ? { ...prev, meta: updated } : prev));
    } catch (err) {
      message.error((err as Error).message || "取消发布失败");
    } finally {
      setPublishing(false);
    }
  };

  if (loading) {
    return (
      <div className="report-preview">
        <Skeleton active />
      </div>
    );
  }
  if (error) {
    return (
      <div className="report-preview">
        <Alert type="error" message={error} showIcon />
      </div>
    );
  }
  if (!data) return null;

  const { meta, snapshot } = data;
  return (
    <div className="report-preview">
      <div className="report-preview-bar">
        <button onClick={() => navigate(`/admin/projects/${projectId}?tab=report`)}>
          ← 返回
        </button>
        <Space>
          {data?.meta.is_published ? (
            <Button onClick={unpublish} loading={publishing}>
              取消发布
            </Button>
          ) : (
            <Button type="primary" onClick={publish} loading={publishing}>
              发布
            </Button>
          )}
          <Button onClick={() => window.print()}>打印 / PDF</Button>
        </Space>
      </div>

      <article className="report-preview-body">
        <h1 className="report-preview-title">{snapshot.project.name}</h1>
        <h2 className="report-preview-subtitle">GEO 周报</h2>

        <div className="report-preview-meta">
          报告周期 {meta.period_start} 至 {meta.period_end}
          <span className="report-preview-meta-sep">·</span>
          {meta.scope_text}
          <span className="report-preview-meta-sep">·</span>
          {meta.generated_by_name}
          <span className="report-preview-meta-sep">·</span>
          {snapshot.baseline.date
            ? `基线 ${snapshot.baseline.date} ${pct(snapshot.baseline.rate ?? 0)}`
            : "未配置基线"}
          <span className="report-preview-meta-sep">·</span>
          生成于 {snapshot.generated_at}
        </div>

        <SectionOneOverall snapshot={snapshot} />
        <SectionTwoSummary snapshot={snapshot} onSave={saveDraft} />
        <SectionThreeBreakdown snapshot={snapshot} />
        <SectionFourContentOps snapshot={snapshot} />
        <SectionFiveWeeklyChanges snapshot={snapshot} />
        <SectionAttribution snapshot={snapshot} onSave={saveDraft} />

        <footer className="report-preview-footer">
          报告由风球科技 GEO 监控平台生成 ｜ 模板 {meta.template_id}
        </footer>
      </article>
    </div>
  );
}

// ----- Chapter components (each is independently tested / styled) -----

function EmptyBlock({ message }: { message: string }) {
  return <div className="report-preview-empty">{message}</div>;
}

function ChapterHeading({ title }: { title: string }) {
  return <h2 className="report-preview-h2">{title}</h2>;
}

function SectionOneOverall({
  snapshot,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  const daily = snapshot.daily_mention_rate;
  if (!daily || daily.length === 0) {
    return (
      <section>
        <ChapterHeading title="一、整体提及率走势" />
        <EmptyBlock message="暂无数数据" />
      </section>
    );
  }
  const last = daily[daily.length - 1];
  const prev = daily.length >= 2 ? daily[daily.length - 2] : null;
  const current = last?.rate ?? 0;
  const previous = prev?.rate ?? 0;
  const wow = current - previous;
  const baseline = snapshot.baseline.rate;

  return (
    <section>
      <ChapterHeading title="一、整体提及率走势" />
      <div className="report-preview-kpis">
        <div className="report-preview-kpi">
          <div className="report-preview-kpi-label">当前周期提及率</div>
          <div className="report-preview-kpi-value">{pct(current)}</div>
        </div>
        <div className="report-preview-kpi">
          <div className="report-preview-kpi-label">周环比</div>
          <div className={`report-preview-kpi-value ${deltaClass(wow)}`}>
            {pp(wow)}
          </div>
        </div>
        <div className="report-preview-kpi">
          <div className="report-preview-kpi-label">
            {snapshot.baseline.date
              ? `基线 (${snapshot.baseline.date})`
              : "基线"}
          </div>
          <div className="report-preview-kpi-value flat">
            {baseline !== null ? pct(baseline) : "未配置基线"}
          </div>
        </div>
      </div>
      <Sparkline points={daily} />
    </section>
  );
}

function SectionTwoSummary({
  snapshot,
  onSave,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
  onSave: (overrides: Record<string, string | null>) => Promise<void>;
}) {
  const fields = [
    { key: "weekly_core_finding", label: "本周核心结论", hint: "1-2 句话总结本周监控结果" },
    { key: "weekly_platform_dynamic", label: "平台动态", hint: "本周 AI 平台层面的整体趋势" },
    { key: "weekly_content_result", label: "内容成效", hint: "本周发布/分发对提及率的拉动效果" },
    { key: "weekly_scene_coverage", label: "场景覆盖", hint: "本周各类问题的覆盖变化" },
  ] as const;

  const block = snapshot.weekly_summary || {
    core_finding: null,
    platform_dynamic: null,
    content_result: null,
    scene_coverage: null,
  };

  // Map template key → snapshot sub-field key.
  const valueOf = (k: string): string | null => {
    if (k === "weekly_core_finding") return block.core_finding;
    if (k === "weekly_platform_dynamic") return block.platform_dynamic;
    if (k === "weekly_content_result") return block.content_result;
    if (k === "weekly_scene_coverage") return block.scene_coverage;
    return null;
  };

  return (
    <section>
      <ChapterHeading title="二、本周总结" />
      {fields.map((f) => (
        <EditableBlock
          key={f.key}
          label={f.label}
          hint={f.hint}
          value={valueOf(f.key)}
          onSave={(v) => onSave({ [f.key]: v })}
        />
      ))}
    </section>
  );
}

function EditableBlock({
  label,
  hint,
  value,
  onSave,
}: {
  label: string;
  hint: string;
  value: string | null;
  onSave: (next: string | null) => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value ?? "");
  const [saving, setSaving] = useState(false);

  const startEdit = () => {
    setDraft(value ?? "");
    setEditing(true);
  };

  const cancel = () => {
    setDraft(value ?? "");
    setEditing(false);
  };

  const save = async () => {
    setSaving(true);
    try {
      await onSave(draft.trim() || null);
      setEditing(false);
    } catch {
      // parent toasts; stay in editing mode so user can retry
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="report-preview-block">
      <div className="report-preview-block-head">
        <strong>{label}</strong>
        <span className="report-preview-block-hint">{hint}</span>
      </div>
      {editing ? (
        <div>
          <Input.TextArea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            autoSize={{ minRows: 2, maxRows: 6 }}
            disabled={saving}
          />
          <div style={{ marginTop: 8, display: "flex", gap: 8 }}>
            <Button type="primary" loading={saving} onClick={save}>
              保存
            </Button>
            <Button onClick={cancel} disabled={saving}>
              取消
            </Button>
          </div>
        </div>
      ) : value ? (
        <p style={{ whiteSpace: "pre-wrap" }}>{value}</p>
      ) : (
        <EmptyBlock message="点此编辑" />
      )}
      {!editing && (
        <Button type="link" size="small" onClick={startEdit}>
          编辑
        </Button>
      )}
    </div>
  );
}

function SectionThreeBreakdown({
  snapshot,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  const breakdown = snapshot.platform_breakdown || [];
  const matrix = snapshot.prompt_platform_matrix || [];
  const summary = snapshot.platform_summary || [];

  return (
    <section>
      <ChapterHeading title="三、分平台周环比变化与问题级提及率明细" />

      <h3 className="report-preview-h3">3.1 平台周环比</h3>
      {breakdown.length === 0 ? (
        <EmptyBlock message="暂无数数据" />
      ) : (
        <PlatformTable rows={breakdown} />
      )}

      {summary.length > 0 && (
        <>
          <h3 className="report-preview-h3">3.2 平台简评</h3>
          <ul className="report-preview-summary-list">
            {summary.map((s) => (
              <li key={s.platform_code}>{s.note}</li>
            ))}
          </ul>
        </>
      )}

      {matrix.length > 0 && (
        <>
          <h3 className="report-preview-h3">3.3 问题×平台 矩阵</h3>
          <MatrixTable matrix={matrix} />
        </>
      )}
    </section>
  );
}

function SectionFourContentOps({
  snapshot,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  const ops = snapshot.content_ops;
  return (
    <section>
      <ChapterHeading title="四、本周内容运营" />
      {ops ? (
        <p>{typeof ops === "string" ? ops : JSON.stringify(ops)}</p>
      ) : (
        <EmptyBlock message="暂无数数据" />
      )}
    </section>
  );
}

function SectionFiveWeeklyChanges({
  snapshot,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  const changes = snapshot.weekly_changes;
  const zero = snapshot.zero_mention_prompts || [];
  const hasChanges =
    changes &&
    ((changes.new_mentions?.length ?? 0) > 0 ||
      (changes.increased?.length ?? 0) > 0 ||
      (changes.decreased?.length ?? 0) > 0 ||
      (changes.lost_mentions?.length ?? 0) > 0);
  const hasZero = zero.length > 0;
  if (!hasChanges && !hasZero) {
    return (
      <section>
        <ChapterHeading title="五、待突破问题与本周边际变化" />
        <EmptyBlock message="暂无数数据" />
      </section>
    );
  }

  return (
    <section>
      <ChapterHeading title="五、待突破问题与本周边际变化" />

      {hasZero && (
        <>
          <h3 className="report-preview-h3">5.1 持续未提及问题</h3>
          <ul className="report-preview-summary-list">
            {zero.map((p) => (
              <li key={p.prompt_id}>{p.prompt_text}</li>
            ))}
          </ul>
        </>
      )}

      {hasChanges && (
        <>
          <h3 className="report-preview-h3">5.2 本周边际变化</h3>
          <ChangesBlock changes={changes!} />
        </>
      )}
    </section>
  );
}

function SectionAttribution({
  snapshot,
  onSave,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
  onSave: (overrides: Record<string, string | null>) => Promise<void>;
}) {
  const text = snapshot.attribution ?? null;
  return (
    <section>
      <ChapterHeading title="5.3 核心归因" />
      <EditableBlock
        label="5.3 核心归因"
        hint="下一阶段重点关注的归因分析"
        value={text}
        onSave={(v) => onSave({ attribution: v })}
      />
    </section>
  );
}

// ----- Sub-components -----

export function Sparkline({
  points,
}: {
  points: ReportSnapshotOut["snapshot"]["daily_mention_rate"];
}) {
  if (!points || points.length === 0) return <div>无数据</div>;
  const w = 1024;
  const h = 200;
  const padX = 24;
  const padY = 16;
  const max = Math.max(0.001, ...points.map((p) => p.rate));
  const step = (w - padX * 2) / Math.max(1, points.length - 1);
  const path = points
    .map((p, i) => {
      const x = padX + i * step;
      const y = h - padY - (p.rate / max) * (h - padY * 2);
      return `${i === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
    })
    .join(" ");
  const dots = points.map((p, i) => {
    const x = padX + i * step;
    const y = h - padY - (p.rate / max) * (h - padY * 2);
    return <circle key={p.date} cx={x} cy={y} r={2.5} fill="#2E5BFF" />;
  });
  return (
    <div className="report-preview-spark">
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
        <path d={path} fill="none" stroke="#2E5BFF" strokeWidth={2} />
        {dots}
      </svg>
    </div>
  );
}

export function PlatformTable({
  rows,
}: {
  rows: ReportSnapshotOut["snapshot"]["platform_breakdown"];
}) {
  if (!rows || rows.length === 0) return <div>无数据</div>;
  const sorted = [...rows].sort((a, b) => b.current_rate - a.current_rate);
  return (
    <table className="report-preview-table">
      <thead>
        <tr>
          <th>平台</th>
          <th>本期</th>
          <th>上期</th>
          <th>周环比</th>
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => (
          <tr key={r.platform_code}>
            <td>{r.platform_label}</td>
            <td className="num">
              {pct(r.current_rate)} ({r.current_mentioned}/{r.current_total})
            </td>
            <td className="num">
              {pct(r.previous_rate)} ({r.previous_mentioned}/{r.previous_total})
            </td>
            <td className={`num ${deltaClass(r.delta_pp)}`}>{pp(r.delta_pp)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function MatrixTable({
  matrix,
}: {
  matrix: ReportSnapshotOut["snapshot"]["prompt_platform_matrix"];
}) {
  const rows = matrix ?? [];
  const platforms: string[] = [];
  const seen = new Set<string>();
  for (const row of rows) {
    for (const pc of Object.keys(row.per_platform || {})) {
      if (!seen.has(pc)) {
        platforms.push(pc);
        seen.add(pc);
      }
    }
  }
  return (
    <table className="report-preview-table report-preview-matrix">
      <thead>
        <tr>
          <th>问题</th>
          {platforms.map((pc) => (
            <th key={pc}>{pc}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const per = row.per_platform || {};
          return (
            <tr key={row.prompt_id}>
              <td title={row.prompt_text}>{truncate(row.prompt_text, 32)}</td>
              {platforms.map((pc) => (
                <td
                  key={pc}
                  className={per[pc] ? "mark-yes" : "mark-no"}
                >
                  {per[pc] ? "✓" : "—"}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ChangesBlock({
  changes,
}: {
  changes: NonNullable<ReportSnapshotOut["snapshot"]["weekly_changes"]>;
}) {
  const sections: Array<[string, Array<unknown>]> = [
    ["新增突破 (0 → ≥1)", changes.new_mentions ?? []],
    ["上升 (覆盖平台数 +1)", changes.increased ?? []],
    ["回落 (覆盖平台数 -1)", changes.decreased ?? []],
    ["失守 (≥1 → 0)", changes.lost_mentions ?? []],
  ];
  const items = sections
    .filter(([, rows]) => rows.length > 0)
    .map(([title, rows]) => (
      <li key={title}>
        <strong>{title}</strong>: {rows.length} 个问题
      </li>
    ));
  return items.length > 0 ? (
    <ul className="report-preview-summary-list">{items}</ul>
  ) : (
    <EmptyBlock message="暂无数数据" />
  );
}
