/**
 * 「视频类信源」sub-tab —— 完成态。
 *
 * 参照 docs/风球GEO监控平台UI/index.html:1052-1083 + js/app.js:2941-2972:
 *   - 顶部「视频类信源聚合」面板:平台卡片网格(抖音 / B 站 / 快手 / ...)——
 *     每张卡片显示「平台名 + 引用条数 + 占比进度条 + 模型 tag 列表 + 信源
 *     tag 列表」,右上角共 N 条视频信源总数。
 *   - 底部「按模型视频信源分布」面板:ECharts 横向 ranking bar,展示每个
 *     模型对视频类信源的引用条数对比。
 *
 * 数据由后端 ``GET /projects/{id}/source-video`` 一次性返回 —— 仅统计
 * 命中 _VIDEO_PLATFORM_RULES(抖音 / B 站 / 快手 / 西瓜 / YouTube / 优酷 /
 * 腾讯视频 / 新浪视频)的引用,窗口 + toolbar 筛选口径与 source-preferences
 * / source-detail 完全一致。
 */

import { useEffect, useMemo, useState } from "react";
import { Empty, Skeleton, message } from "antd";
import * as echarts from "echarts";
import EChart from "../../../components/EChart";
import {
  getProject,
  getVideoSources,
  type ProjectPlatform,
  type SourcePlatformSlice,
  type VideoPlatformSlice,
  type VideoSourceOut,
} from "../../../api/projects";
import { platformLabel, rowKeyOfPlatform } from "../platforms";
import { useToolbarFilter } from "../../../components/ToolbarFilterContext";

interface Props {
  projectId: number;
}

export default function VideoSources({ projectId }: Props) {
  const [out, setOut] = useState<VideoSourceOut | null>(null);
  const [loading, setLoading] = useState(true);
  // ``effectiveModels`` 全选 fallback 用 —— 与 AllSources / SourceDetail 同款实现。
  const [projectPlatforms, setProjectPlatforms] = useState<ProjectPlatform[] | null>(null);
  const toolbar = useToolbarFilter();

  useEffect(() => {
    let cancelled = false;
    getProject(projectId)
      .then((d) => { if (!cancelled) setProjectPlatforms(d.platforms); })
      .catch(() => { if (!cancelled) setProjectPlatforms([]); });
    return () => { cancelled = true; };
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
    () => (toolbar.selectedPromptIds ? [...toolbar.selectedPromptIds].sort().join("|") : "all"),
    [toolbar.selectedPromptIds],
  );

  useEffect(() => {
    if (effectiveModels === undefined) return;
    let cancelled = false;
    setLoading(true);
    getVideoSources(projectId, {
      days: dateQuery.days,
      start: dateQuery.start,
      end: dateQuery.end,
      models: effectiveModels,
      prompts: toolbar.selectedPromptIds ?? undefined,
    })
      .then((d) => { if (!cancelled) setOut(d); })
      .catch((err: Error) => {
        if (!cancelled) message.error(err.message || "视频类信源数据加载失败");
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [projectId, toolbar.version, effectiveModels, dateKey, promptsKey]);

  if (loading) return <Skeleton active paragraph={{ rows: 6 }} />;
  if (!out || out.total === 0) {
    return <Empty description="窗口内尚无视频类信源" style={{ padding: 32 }} />;
  }

  return (
    <div className="vs-root">
      {/* 顶部:视频类信源聚合(平台卡片网格) */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>视频类信源聚合</h3>
            <p>抖音 / B 站 / 快手 / 西瓜 / YouTube 等视频平台被 AI 引用的分布</p>
          </div>
          <div className="panel-actions">
            <span className="vs-total">
              共 <strong>{out.total.toLocaleString()}</strong> 条视频信源
            </span>
          </div>
        </div>
        <div className="panel-body">
          <PlatformGrid platforms={out.platforms} total={out.total} />
        </div>
      </div>

      {/* 底部:按模型视频信源分布(ranking bar) */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>按模型视频信源分布</h3>
            <p>各模型引用视频类信源的数量对比</p>
          </div>
        </div>
        <div className="panel-body">
          <ByModelRanking byModel={out.by_model} />
        </div>
      </div>

      <style>{`
        .vs-root { display: flex; flex-direction: column; gap: 12px; padding: 12px 0; }
        .vs-total {
          font-size: 12px;
          color: var(--text-secondary);
        }
        .vs-total strong {
          font-size: 16px;
          font-weight: 600;
          color: var(--brand-blue, #1a55e8);
          margin: 0 4px;
        }
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
        .panel-header h3 { margin: 0; font-size: 15px; font-weight: 600; color: var(--text-primary); }
        .panel-header p { margin: 4px 0 0; font-size: 12px; color: var(--text-tertiary); }
        .panel-body { padding: 16px 18px; }
      `}</style>
    </div>
  );
}

/* ------------------------------------------------------------------
 * 平台卡片网格 —— 每个视频平台一张卡
 * ------------------------------------------------------------------ */

function PlatformGrid({ platforms, total }: { platforms: VideoPlatformSlice[]; total: number }) {
  if (platforms.length === 0) {
    return <Empty description="暂无视频平台引用" />;
  }
  return (
    <>
      <div className="vs-platform-grid">
        {platforms.map((p) => (
          <PlatformCard key={p.name} platform={p} total={total} />
        ))}
      </div>
      <style>{`
        .vs-platform-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
          gap: 12px;
        }
        .vs-platform-card {
          border: 1px solid var(--border-light, #f0f0f0);
          border-radius: 8px;
          padding: 14px 16px;
          background: var(--bg-page, #fafafa);
          display: flex;
          flex-direction: column;
          gap: 10px;
        }
        .vs-platform-head {
          display: flex;
          align-items: baseline;
          justify-content: space-between;
        }
        .vs-platform-name {
          font-size: 14px;
          font-weight: 600;
          color: var(--text-primary);
        }
        .vs-platform-count {
          font-size: 12px;
          color: var(--text-secondary);
          font-weight: 500;
        }
        .vs-platform-count strong {
          font-size: 16px;
          color: var(--text-primary);
          font-weight: 600;
          margin-right: 2px;
        }
        .vs-platform-bar {
          width: 100%;
          height: 6px;
          border-radius: 999px;
          background: var(--border-light, #f0f0f0);
          overflow: hidden;
        }
        .vs-platform-bar-fill {
          height: 100%;
          border-radius: 999px;
          transition: width 0.3s ease;
        }
        .vs-platform-tags {
          display: flex;
          flex-wrap: wrap;
          gap: 4px;
        }
        .vs-tag {
          padding: 2px 8px;
          font-size: 11px;
          border-radius: 4px;
          background: rgba(0, 0, 0, 0.04);
          color: var(--text-secondary);
          white-space: nowrap;
        }
        .vs-tag-count {
          color: var(--text-primary);
          font-weight: 600;
          margin-left: 2px;
        }
        .vs-platform-models-label,
        .vs-platform-sources-label {
          font-size: 11px;
          color: var(--text-tertiary);
          margin-right: 4px;
        }
        .vs-platform-sources .vs-tag {
          background: rgba(26, 85, 232, 0.08);
          color: var(--brand-blue, #1a55e8);
        }
      `}</style>
    </>
  );
}

function PlatformCard({ platform, total }: { platform: VideoPlatformSlice; total: number }) {
  const pct = total > 0 ? Math.round((platform.count / total) * 100) : 0;
  // platforms 字段是 dict[model_compound_key, count],按 count desc 排序后渲染。
  const sortedModels = useMemo(() => {
    return Object.entries(platform.platforms).sort((a, b) => b[1] - a[1]);
  }, [platform.platforms]);
  return (
    <div className="vs-platform-card">
      <div className="vs-platform-head">
        <span className="vs-platform-name">{platform.name}</span>
        <span className="vs-platform-count">
          <strong>{platform.count}</strong> 条
        </span>
      </div>
      <div className="vs-platform-bar">
        <div
          className="vs-platform-bar-fill"
          style={{ width: `${pct}%`, background: platform.color }}
        />
      </div>
      {sortedModels.length > 0 && (
        <div className="vs-platform-tags vs-platform-models">
          <span className="vs-platform-models-label">模型</span>
          {sortedModels.map(([model, c]) => (
            <span key={model} className="vs-tag">
              {platformLabel(model)}
              <span className="vs-tag-count">{c}</span>
            </span>
          ))}
        </div>
      )}
      {platform.sources.length > 0 && (
        <div className="vs-platform-tags vs-platform-sources">
          <span className="vs-platform-sources-label">信源</span>
          {platform.sources.map((s) => (
            <span key={s} className="vs-tag">
              {s}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------
 * 按模型视频信源分布 —— ECharts 横向 ranking bar
 * ------------------------------------------------------------------ */

function ByModelRanking({ byModel }: { byModel: SourcePlatformSlice[] }) {
  const option = useMemo<echarts.EChartsOption | null>(() => {
    if (byModel.length === 0) return null;
    // 横向 bar:ranking —— 按 total_refs desc 排序,
    // label 显示数字,无 tooltip trickery。
    const sorted = [...byModel].sort((a, b) => b.total_refs - a.total_refs);
    const labels = sorted.map((b) => platformLabel(b.platform));
    const values = sorted.map((b) => b.total_refs);
    return {
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { left: 120, right: 60, top: 16, bottom: 24 },
      xAxis: {
        type: "value",
        minInterval: 1,
        axisLabel: { fontSize: 11 },
      },
      yAxis: {
        type: "category",
        data: labels,
        axisLabel: { fontSize: 11 },
        inverse: true,
      },
      series: [{
        name: "视频信源引用条数",
        type: "bar",
        data: values,
        barWidth: 18,
        itemStyle: { color: "#1a55e8", borderRadius: [0, 4, 4, 0] },
        label: {
          show: true,
          position: "right",
          fontSize: 11,
          color: "var(--text-secondary)",
          formatter: "{c}",
        },
      }],
    };
  }, [byModel]);

  if (!option) return <Empty description="暂无模型视频信源数据" />;
  return <EChart option={option} height={260} />;
}
