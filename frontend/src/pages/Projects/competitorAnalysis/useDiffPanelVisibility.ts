/**
 * 差异化分析 tab 的「哪些卡展开 / 哪些卡收起」状态持久化 hook。
 *
 * - localStorage key = ``windx_diff_panels``
 * - value = JSON 数组,元素形如 ``"<metric>::<brand_canonical>"``
 *   (用 canonical 而不是展示名 —— 防「珂润 Curel」/「珂润」漂移)
 * - 元素存在 = 该卡「关闭」(占位态);不在数组里 = 展开
 *   (沿用原型 ``App.diffPanels`` 的「关闭集合」语义,这样「全部收起」= 一次
 *   set 全集 key,「全部展开」= 一次 set 空数组 / 清空 localStorage)
 * - SSR / 隐私模式 / quota 异常都 try/catch 兜底
 * - 切项目 / 数据变化导致部分 key 失效 → effect 里脏 key 清理,但不主动
 *   removeItem(切回老项目时残留 key 仍在,符合「保留用户上次选择」直觉)
 */

import { useCallback, useEffect, useState } from "react";

const STORAGE_KEY = "windx_diff_panels";

/** 解析 localStorage 里的 panels 列表 —— 失败 / 不是数组 / 非字符串元素
 *  都当作空。SSR(无 window)返回空数组。 */
function readStored(): string[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter((x): x is string => typeof x === "string");
  } catch {
    return [];
  }
}

function writeStored(panels: string[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(panels));
  } catch {
    // quota exceeded / 隐私模式无 localStorage → 静默忽略
  }
}

function removeStored(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 静默忽略
  }
}

/** 把当前有效 key 全集转成「全开」面板列表(空数组 = 无任何卡关闭)。 */
function defaultPanels(): string[] {
  return [];
}

export interface UseDiffPanelVisibilityResult {
  /** 当前关闭的卡 key 集合(去重 + 只保留 validKeys)。 */
  panels: string[];
  /** 更新关闭集合并写回 localStorage。 */
  persist: (next: string[]) => void;
  /** 「恢复默认」= 清掉 localStorage 并把所有有效 key 当成「关闭」(全开) */
  reset: () => void;
}

export function useDiffPanelVisibility(
  validKeys: Set<string>,
): UseDiffPanelVisibilityResult {
  // 首屏:从 localStorage 读 → 只保留当前有效的 key → 脏 key 丢掉。
  // 读不到 / 解析失败 → 默认全开(空数组)。
  const [panels, setPanels] = useState<string[]>(() => {
    const stored = readStored();
    if (stored.length === 0) return defaultPanels();
    return stored.filter((k) => validKeys.has(k));
  });

  // validKeys 变化(切项目 / toolbar 触发 diff_brand 重算) → 同步清理脏 key。
  // 长度未变就不 setState,避免无谓 re-render。
  useEffect(() => {
    setPanels((prev) => {
      const next = prev.filter((k) => validKeys.has(k));
      return next.length === prev.length ? prev : next;
    });
  }, [validKeys]);

  const persist = useCallback((next: string[]) => {
    setPanels(next);
    writeStored(next);
  }, []);

  const reset = useCallback(() => {
    removeStored();
    setPanels(defaultPanels());
  }, []);

  return { panels, persist, reset };
}
