import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  ReactNode,
} from "react";

interface ProjectCtx {
  currentProjectId: number | null;
  setCurrentProjectId: (id: number | null) => void;
}

const Ctx = createContext<ProjectCtx>({
  currentProjectId: null,
  setCurrentProjectId: () => {},
});

const STORAGE_KEY = "windx.currentProjectId";

function readStoredProjectId(): number | null {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    if (!v) return null;
    const n = Number(v);
    return Number.isInteger(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

/**
 * Persists the "current project" across navigations inside the SPA so
 * the sidebar's 数据洞察 / 数据中心 / 系统 groups stay visible while the
 * user clicks around 管理组 (工作台 / 监控项目 / 客户管理). Without this,
 * leaving /admin/projects/:id would lose the project context and the
 * project-level nav items would vanish.
 *
 * localStorage 兜底浏览器硬刷新:刷新后 React state 会归零,这里从
 * localStorage 读出来恢复 —— 避免在「监控项目」列表页刷新时侧栏项目组
 * 突然消失。
 */
export function ProjectProvider({ children }: { children: ReactNode }) {
  const [currentProjectId, setCurrentProjectIdState] = useState<number | null>(
    () => readStoredProjectId(),
  );

  const setCurrentProjectId = useCallback((id: number | null) => {
    setCurrentProjectIdState(id);
    try {
      if (id === null) localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, String(id));
    } catch {
      // localStorage 不可用(隐私模式 / quota)时静默失败,内存 state 仍生效
    }
  }, []);

  // 多 tab 同步:在别的 tab 切了项目,这边也跟着切。
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key !== STORAGE_KEY) return;
      setCurrentProjectIdState(readStoredProjectId());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const value = useMemo(
    () => ({ currentProjectId, setCurrentProjectId }),
    [currentProjectId, setCurrentProjectId],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCurrentProject(): ProjectCtx {
  return useContext(Ctx);
}

/**
 * Convenience for places that only need the setter — keeps the import
 * short when the reader value isn't used.
 */
export function useSetCurrentProject(): (id: number | null) => void {
  const { setCurrentProjectId } = useContext(Ctx);
  return useCallback(setCurrentProjectId, [setCurrentProjectId]);
}
