/**
 * 公开报告预览页 —— 无需登录,任何人拿到 share_token 链接都能看。
 *
 * 与 ReportPreview 渲染同一章节树(参见 docs/参芪十一味颗粒-GEO周报
 * 模板),只换数据源(public endpoint)与 toolbar bar(无返回按钮)。
 */

import { useEffect, useState } from "react";
import { Alert, Skeleton } from "antd";
import { useParams } from "react-router-dom";
import { getPublicReportSnapshot, type ReportSnapshotOut } from "../api/reports";
import {
  PlatformTable,
  Sparkline,
  deltaClass,
  pct,
  pp,
} from "./Projects/ReportPreview";
import "./Projects/ReportPreview.css";

export default function PublicReportPreview() {
  const params = useParams<{ token: string }>();
  const token = params?.token ?? "";
  const [data, setData] = useState<ReportSnapshotOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) {
      setLoading(false);
      setError("链接无效");
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getPublicReportSnapshot(token)
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
  }, [token]);

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

  if (data.unpublished) {
    return (
      <div className="report-preview">
        <div className="report-preview-bar">
          <span />
        </div>
        <article className="report-preview-body">
          <h1 className="report-preview-title">报告尚未发布</h1>
          <p style={{ color: "#666", marginTop: 24 }}>
            {data.title ?? ""} 的报告周期 {data.period_start} 至 {data.period_end}{" "}
            尚未补充完成,生成者还在编辑中。请稍后重试,或联系报告创建者。
          </p>
        </article>
      </div>
    );
  }

  const { meta, snapshot } = data;
  return (
    <div className="report-preview">
      <div className="report-preview-bar">
        <span /> {/* spacer, no 返回 button */}
        <button onClick={() => window.print()}>打印 / PDF</button>
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

        <PublicSectionOne snapshot={snapshot} />
        <PublicSectionTwo snapshot={snapshot} />
        <PublicSectionThree snapshot={snapshot} />
        <PublicSectionFour snapshot={snapshot} />
        <PublicSectionFive snapshot={snapshot} />
        <PublicSectionAttribution snapshot={snapshot} />

        <footer className="report-preview-footer">
          报告由风球科技 GEO 监控平台生成 ｜ 模板 {meta.template_id}
        </footer>
      </article>
    </div>
  );
}

function EmptyBlock({ message }: { message: string }) {
  return <div className="report-preview-empty">{message}</div>;
}

function ChapterHeading({ title }: { title: string }) {
  return <h2 className="report-preview-h2">{title}</h2>;
}

function PublicSectionOne({
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

function PublicSectionTwo({
  snapshot,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  const block = snapshot.weekly_summary;
  const hasAny =
    block &&
    (block.core_finding || block.platform_dynamic ||
     block.content_result || block.scene_coverage);
  return (
    <section>
      <ChapterHeading title="二、本周总结" />
      {!block || !hasAny ? (
        <EmptyBlock message="暂无数数据" />
      ) : (
        <ul className="report-preview-summary-list">
          {block.core_finding && (
            <li>
              <strong>本周核心结论：</strong>
              {block.core_finding}
            </li>
          )}
          {block.platform_dynamic && (
            <li>
              <strong>平台动态：</strong>
              {block.platform_dynamic}
            </li>
          )}
          {block.content_result && (
            <li>
              <strong>内容成效：</strong>
              {block.content_result}
            </li>
          )}
          {block.scene_coverage && (
            <li>
              <strong>场景覆盖：</strong>
              {block.scene_coverage}
            </li>
          )}
        </ul>
      )}
    </section>
  );
}

function PublicSectionThree({
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
          <p style={{ color: "#666", fontSize: 12 }}>
            （详见登录后报告详情页）
          </p>
        </>
      )}
    </section>
  );
}

function PublicSectionFour(_props: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  return (
    <section>
      <ChapterHeading title="四、本周内容运营" />
      <EmptyBlock message="暂无数数据" />
    </section>
  );
}

function PublicSectionFive({
  snapshot,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  const zero = snapshot.zero_mention_prompts || [];
  if (zero.length === 0) {
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
      <h3 className="report-preview-h3">5.1 持续未提及问题</h3>
      <ul className="report-preview-summary-list">
        {zero.map((p) => (
          <li key={p.prompt_id}>{p.prompt_text}</li>
        ))}
      </ul>
    </section>
  );
}

function PublicSectionAttribution({
  snapshot,
}: {
  snapshot: ReportSnapshotOut["snapshot"];
}) {
  const text = snapshot.attribution ?? null;
  return (
    <section>
      <ChapterHeading title="5.3 核心归因" />
      {text ? (
        <p style={{ whiteSpace: "pre-wrap" }}>{text}</p>
      ) : (
        <EmptyBlock message="暂无数数据" />
      )}
    </section>
  );
}
