/**
 * 差异化分析 tab 的单张品牌卡(打开态 / 关闭态两态组件)。
 *
 * 打开态:卡头(品牌色左条 + 色点 + 品牌名 + 「对照基准」蓝 tag + 指标名 + ✕)
 *        → KPI(大数字 + % + 副标「M 模型两端加权」 + 竞品卡独有的「领先/落后
 *        自身 Xpt」胶囊)→ 表格(行 = 模型;列 = PC / 移动 / 整体 / vs 自身 /
 *        端侧差异)。
 * 关闭态:虚线占位条 + 色点 + 品牌名 + 指标胶囊 + 「点击展开」提示,点占位
 *        条恢复。
 *
 * 颜色全走 inline style(后端注入的品牌色 + 前端 WIZARD_MODELS 里的模型色);
 * 布局/字体走 .diff-card-* 类(在父 DiffPane 的 <style> 块里集中维护)。
 */

import type { DiffBrandCard, DiffBrandRow } from "../../../api/projects";
import { modelNameFor, platformColor } from "../platforms";
import {
  computeDevGap,
  computeRowVsSelf,
  devText,
  DEV_CLAMP,
  formatModelCount,
  sortRowsByWizard,
} from "./diffBrandColors";

interface Props {
  card: DiffBrandCard;
  /** 同 metric 下的自身卡 rows(打开态表格「vs 自身」列对照用)。null = 自身卡 / 无自身行。 */
  selfCard: DiffBrandCard | null;
  isOpen: boolean;
  onClose: () => void;
  onOpen: () => void;
}

export default function DiffCard({ card, selfCard, isOpen, onClose, onOpen }: Props) {
  if (!isOpen) {
    return (
      <div
        className="diff-card is-closed"
        onClick={onOpen}
        title="点击展开"
        data-key={`${card.metric}::${card.brand_canonical}`}
      >
        <div className="diff-card-closed-inner">
          <span className="model-dot" style={{ background: card.color }} />
          <span className="diff-card-closed-name">{card.brand}</span>
          <span className="diff-card-closed-metric">{metricName(card.metric)}</span>
          <span className="diff-card-open-hint">点击展开</span>
        </div>
      </div>
    );
  }

  // 行 = 后端给的原始 rows,前端按 WIZARD_MODELS 索引重排展示顺序
  const rows = sortRowsByWizard(card.rows);
  // 自身卡行(供「vs 自身」列对照;非自身卡才用)
  const selfRowByCode = new Map<string, DiffBrandRow>(
    sortRowsByWizard(selfCard?.rows ?? []).map((r) => [r.platform_code, r]),
  );
  // 自身卡的 head_value(给竞品卡「领先/落后自身 Xpt」胶囊用)
  const selfHead = selfCard?.head_value ?? null;
  const headGap = card.is_self || selfHead == null ? null : card.head_value - selfHead;
  const headGapCls = headGap == null ? "" : headGap >= 0 ? "is-up" : "is-down";
  const headGapTxt =
    headGap == null
      ? ""
      : `${headGap >= 0 ? "领先自身 " : "落后自身 "}${Math.abs(headGap).toFixed(1)}pt`;

  return (
    <div className="diff-card" data-key={`${card.metric}::${card.brand_canonical}`}>
      <div className="diff-card-head" style={{ borderLeftColor: card.color }}>
        <div className="diff-card-id">
          <span className="model-dot" style={{ background: card.color }} />
          <span className="diff-card-name">{card.brand}</span>
          {card.is_self && <span className="diff-card-tag">对照基准</span>}
        </div>
        <div className="diff-card-metric">{metricName(card.metric)}</div>
        <button
          type="button"
          className="diff-card-close"
          title="关闭此看板"
          onClick={onClose}
        >
          ✕
        </button>
      </div>
      <div className="diff-card-summary">
        <div className="diff-card-kpi">
          <span className="diff-card-kpi-val" style={{ color: card.color }}>
            {fmtNum(card.head_value)}
            <span className="diff-card-kpi-unit">%</span>
          </span>
          <span className="diff-card-kpi-label">{formatModelCount(card.rows.length)}</span>
        </div>
        {headGapTxt && (
          <span className={`diff-card-gap ${headGapCls}`}>{headGapTxt}</span>
        )}
      </div>
      <div className="diff-card-table-wrap">
        <table className="diff-card-table">
          <thead>
            <tr>
              <th>模型</th>
              <th className="is-num">PC</th>
              <th className="is-num">移动</th>
              <th className="is-num">整体</th>
              <th className="is-num">vs 自身</th>
              <th>端侧差异</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="diff-td-empty">当前模型筛选下无数据</td>
              </tr>
            ) : (
              rows.map((r) => {
                const selfRow = selfRowByCode.get(r.platform_code);
                const overall = r.overall;
                const vsSelf = card.is_self ? null : computeRowVsSelf(r, selfRow);
                const devGap = computeDevGap(r);
                // 文字 devText(devGap) 用真实值;CSS 偏移条 --dev clamp 到 ±1,
                // 让指针位移不飞出轨道(divisor = DEV_CLAMP)
                const devVar = Math.max(-1, Math.min(1, devGap / DEV_CLAMP));
                const gapCls = vsSelf == null ? "" : vsSelf >= 0 ? "is-up" : "is-down";
                const gapTxt =
                  vsSelf == null
                    ? "—"
                    : `${vsSelf >= 0 ? "+" : ""}${vsSelf.toFixed(1)}`;
                return (
                  <tr key={r.platform_code}>
                    <td className="diff-td-model">
                      <span
                        className="model-dot"
                        style={{ background: platformColor(r.platform_code) }}
                      />
                      {modelNameFor(r.platform_code, "fast")}
                    </td>
                    <td className="diff-td-num">{r.pc_rate.toFixed(1)}</td>
                    <td className="diff-td-num">{r.mobile_rate.toFixed(1)}</td>
                    <td className="diff-td-num diff-td-overall">{overall.toFixed(1)}</td>
                    <td className={`diff-td-num diff-td-gap ${gapCls}`}>{gapTxt}</td>
                    <td className="diff-td-dev">
                      <span
                        className="diff-dev-bar"
                        style={{ ["--dev" as string]: devVar.toFixed(3) }}
                      />
                      <span className="diff-dev-txt">{devText(devGap)}</span>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function metricName(m: DiffBrandCard["metric"]): string {
  switch (m) {
    case "mention":
      return "整体提及率";
    case "top1":
      return "Top1 提及率";
    case "top3":
      return "Top3 提及率";
  }
}

function fmtNum(v: number): string {
  if (!Number.isFinite(v)) return "—";
  return v.toFixed(1);
}
