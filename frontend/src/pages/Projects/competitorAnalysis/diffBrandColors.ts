/**
 * 差异化分析 tab 的算法常量与行级辅助函数。
 *
 * 后端 ``_compute_diff_brand`` 已经把 head_value(与「全部竞品」tab 同口径,
 * ``CompetitorKpi.{mention,top1,top3}_rate * 100``,不分 platform / 终端)和
 * rate 全算好推到前端,这里只做展示层的二次处理:
 *   1. ``sortRowsByWizard`` — 按 WIZARD_MODELS 的 value 索引重排 rows,让
 *      「豆包→元宝→千问→Kimi→DeepSeek→文心→ChatGPT→蚂蚁阿福」的顺序稳定
 *      (后端给的是字母序,前端展示按产品定义的顺序)
 *   2. ``computeRowVsSelf`` — 本行整体 − 自身行整体(同 metric 内对照)
 *   3. ``computeDevGap`` / ``devText`` — PC vs 移动端的端侧差,
 *      文字用真实值,CSS 偏移条 ``--dev`` 用 ``DEV_CLAMP`` clamp
 */

import { WIZARD_MODELS } from "../wizardConfig";
import type { DiffBrandRow } from "../../../api/projects";

/** 端侧差异条满程刻度 —— ±8pt 拉满,超过的数值都按 ±8pt 限幅后喂给
 *  CSS 偏移条 ``--dev``(避免长尾把视觉比例挤垮、指针飞出轨道)。
 *  文字部分(``devText``)**不**clamp —— 显示真实差值。 */
export const DEV_CLAMP = 8;

/** WIZARD_MODELS 顺序下的 base code 数组(只取 .value,无 _mobile 后缀),
 *  与后端 _strip_mobile 输出对齐。 */
export const WIZARD_MODEL_CODES: string[] = WIZARD_MODELS.map((m) => m.value);

/** 按 WIZARD_MODELS 索引重排 rows;未在 WIZARD_MODELS 里的 code(理论上
 *  不会出现,后端只接受项目配置的 platform)按字母序排到末尾。 */
export function sortRowsByWizard(rows: DiffBrandRow[]): DiffBrandRow[] {
  const idx = new Map(WIZARD_MODEL_CODES.map((c, i) => [c, i]));
  return [...rows].sort((a, b) => {
    const ai = idx.has(a.platform_code) ? idx.get(a.platform_code)! : Number.POSITIVE_INFINITY;
    const bi = idx.has(b.platform_code) ? idx.get(b.platform_code)! : Number.POSITIVE_INFINITY;
    if (ai !== bi) return ai - bi;
    return a.platform_code.localeCompare(b.platform_code);
  });
}

/** 本行整体 − 自身行整体;自身卡 / 无自身行 → null,UI 显示「—」。
 *  口径与表格「整体」列一致(per-platform 跨 web+mobile 合并率),
 * 不是行内 (pc + mobile) / 2 的均值。 */
export function computeRowVsSelf(
  r: DiffBrandRow,
  selfRow: DiffBrandRow | undefined,
): number | null {
  if (!selfRow) return null;
  return r.overall - selfRow.overall;
}

/** 端侧差异 = pc − mobile,**不**clamp,直接返回真实差值(单位 pt)。
 *  CSS 偏移条 ``--dev`` 变量使用时,由 DiffCard 自行 clamp 到 ±DEV_CLAMP
 *  以避免指针飞出轨道 —— 文字部分始终用真实值。 */
export function computeDevGap(r: DiffBrandRow): number {
  return r.pc_rate - r.mobile_rate;
}

/** 端侧差异的展示文字:"PC 高 3.5" / "移动高 1.2"。 */
export function devText(gap: number): string {
  return `${gap >= 0 ? "PC 高" : "移动高"} ${Math.abs(gap).toFixed(1)}`;
}

/** 头部 KPI 「M 模型两端加权」中的 M(rows 数)→ 默认 0。 */
export function formatModelCount(n: number): string {
  return `${n} 模型两端加权`;
}
