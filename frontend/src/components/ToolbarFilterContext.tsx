import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

/**
 * 全局工具栏 → 数据 Tab 的筛选值传递通道。
 *
 * 工具栏（AppLayout 下的 GlobalToolbar）与各数据 Tab（OverviewTab /
 * QuestionTab / CompetitorAnalysisTab ...）是兄弟节点,不能直接传 props;
 * 用 Context 让两边各 hook 一次即可。当前只承载「模型」筛选项 —— 题目 /
 * 日期 / 模式 / 终端 等后续再扩。
 *
 * 模型筛选语义:Toolbar 里维护的是「本项目配置 + 默认全选」的一份
 * ``Set<modelCode>``,Provider 把这份集合以及「自上次应用以来的版本号」
 * 暴露出去。各 Tab 在 ``useEffect`` 里把 ``version`` 加进依赖,点
 * 「应用」就让版本号 +1,Tab 就会重新 fetch。
 */

/** 时间区间 —— 全局工具栏下日期下拉对外的最终口径。
 *  ``days`` 用于预设(7/15/30/60);``start``/``end`` 用于自定义。 */
export type ToolbarDateRange =
  | { days: number; start?: undefined; end?: undefined }
  | { start: string; end: string; days?: undefined };

/** 模式分桶 —— 全局工具栏下「模式」分段控件对外的最终口径。
 *  - ``"fast"``  : 快速 (Subtask.mode IN 'standard'/'search'/'web')
 *  - ``"think"`` : 思考 (Subtask.mode IN 'reasoning'/'reasoning_search')
 *  UI 用 Set<"fast" | "think"> 维护「勾选状态」;应用时把全选状态映射成
 *  ``null``(不筛),与 platforms / prompt_ids 同款「全选即 null」语义。 */
export type ThinkingMode = "fast" | "think";

/** 终端分桶 —— 全局工具栏下「终端」分段控件对外的最终口径。 */
export type DeliveryMode = "web" | "mobile";

export interface ToolbarFilterState {
  /** 模型筛选 —— 空集合 / null 表示「全部」(不筛)。 */
  selectedModels: string[] | null;
  /** 问题筛选 —— 空集合 / null 表示「全部」。 */
  selectedPromptIds: number[] | null;
  /** 日期区间 —— null 表示「未选」(由 Tab 自己用本地默认值)。 */
  selectedDateRange: ToolbarDateRange | null;
  /** 模式筛选 —— null 表示「全部」(不筛)。 */
  selectedThinkingMode: ThinkingMode[] | null;
  /** 终端筛选 —— null 表示「全部」(不筛)。 */
  selectedDeliveryMode: DeliveryMode[] | null;
  /** 「应用」按钮触发 +1;Tab 把这个加进 useEffect 依赖即可强制刷新。 */
  version: number;
}

export interface ToolbarFilterContextValue extends ToolbarFilterState {
  /** 内部用:Toolbar 把当前勾选状态写进来,version 同步 +1。 */
  apply: (next: {
    selectedModels?: string[] | null;
    selectedPromptIds?: number[] | null;
    selectedDateRange?: ToolbarDateRange | null;
    selectedThinkingMode?: ThinkingMode[] | null;
    selectedDeliveryMode?: DeliveryMode[] | null;
  }) => void;
}

const Ctx = createContext<ToolbarFilterContextValue | null>(null);

export function ToolbarFilterProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  // 初始 version = 1,首屏各 Tab 也会拿到一次,触发首次 fetch。
  const [selectedModels, setSelectedModels] = useState<string[] | null>(null);
  const [selectedPromptIds, setSelectedPromptIds] = useState<number[] | null>(
    null,
  );
  const [selectedDateRange, setSelectedDateRange] =
    useState<ToolbarDateRange | null>(null);
  const [selectedThinkingMode, setSelectedThinkingMode] = useState<
    ThinkingMode[] | null
  >(null);
  const [selectedDeliveryMode, setSelectedDeliveryMode] = useState<
    DeliveryMode[] | null
  >(null);
  const [version, setVersion] = useState(1);

  const apply = useCallback(
    (next: {
      selectedModels?: string[] | null;
      selectedPromptIds?: number[] | null;
      selectedDateRange?: ToolbarDateRange | null;
      selectedThinkingMode?: ThinkingMode[] | null;
      selectedDeliveryMode?: DeliveryMode[] | null;
    }) => {
      if (next.selectedModels !== undefined) {
        setSelectedModels(next.selectedModels);
      }
      if (next.selectedPromptIds !== undefined) {
        setSelectedPromptIds(next.selectedPromptIds);
      }
      if (next.selectedDateRange !== undefined) {
        setSelectedDateRange(next.selectedDateRange);
      }
      if (next.selectedThinkingMode !== undefined) {
        setSelectedThinkingMode(next.selectedThinkingMode);
      }
      if (next.selectedDeliveryMode !== undefined) {
        setSelectedDeliveryMode(next.selectedDeliveryMode);
      }
      setVersion((v) => v + 1);
    },
    [],
  );

  const value = useMemo<ToolbarFilterContextValue>(
    () => ({
      selectedModels,
      selectedPromptIds,
      selectedDateRange,
      selectedThinkingMode,
      selectedDeliveryMode,
      version,
      apply,
    }),
    [
      selectedModels,
      selectedPromptIds,
      selectedDateRange,
      selectedThinkingMode,
      selectedDeliveryMode,
      version,
      apply,
    ],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useToolbarFilter(): ToolbarFilterContextValue {
  const v = useContext(Ctx);
  if (!v) {
    // 没有 Provider(例如 /login 页)时,返回一个「不工作」的占位,
    // 调用方拿到的 version 不会变,apply 是 noop,行为与初始一致。
    return {
      selectedModels: null,
      selectedPromptIds: null,
      selectedDateRange: null,
      selectedThinkingMode: null,
      selectedDeliveryMode: null,
      version: 0,
      apply: () => {},
    };
  }
  return v;
}
