import {
  createContext,
  useCallback,
  useContext,
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

/**
 * Persists the "current project" across navigations inside the SPA so
 * the sidebar's 数据洞察 / 数据中心 / 系统 groups stay visible while the
 * user clicks around 管理组 (工作台 / 监控项目 / 客户管理). Without this,
 * leaving /admin/projects/:id would lose the project context and the
 * project-level nav items would vanish.
 */
export function ProjectProvider({ children }: { children: ReactNode }) {
  const [currentProjectId, setCurrentProjectId] = useState<number | null>(null);
  const value = useMemo(
    () => ({ currentProjectId, setCurrentProjectId }),
    [currentProjectId],
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
