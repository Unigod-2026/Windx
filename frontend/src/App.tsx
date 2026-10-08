import {
  RouterProvider,
  createBrowserRouter,
  Navigate,
} from "react-router-dom";
import { AuthProvider, RequireAuth, RequireSuperAdmin } from "./auth/AuthProvider";
import { ProjectProvider } from "./auth/ProjectContext";
import AppLayout from "./layouts/AppLayout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Customers from "./pages/Customers";
import ProjectsList from "./pages/Projects/List";
import ProjectDetail from "./pages/Projects/Detail";
import PublicReportPreview from "./pages/PublicReportPreview";
import AdminReportPreview from "./pages/Reports/AdminReportPreview";
import NewProjectPage from "./pages/Projects/NewProject";
import PendingProjectsList from "./pages/PendingProjects/List";

const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  { path: "/", element: <Navigate to="/admin" replace /> },
  // 公开报告预览 —— 无需登录,任何人凭 share_token 都能看。
  // 路径独立于 /admin/*,不走 RequireAuth,不走 AppLayout
  // (接收者通常不在 app 内,侧边栏/工具栏是噪音)。
  // 后端 gate by is_published:未发布的报告 token URL 访问直接 404。
  { path: "/public/reports/:token", element: <PublicReportPreview /> },
  // Admin 周报编辑入口 —— 顶层路由,前缀 `/reports/*`(故意避开 /admin/*)。
  // 关键:React Router v6 默认按 path-prefix 嵌套,任何 `/admin/X` 形式
  // 的顶层路由都会被识别为 /admin 的子路径并被 AppLayout 包住;
  // 改用 /reports/:id 后,React Router 匹配这个独立路径,不触发任何
  // 父级 AppLayout,直接渲染 AdminReportPreview。
  {
    path: "/reports/:id",
    element: (
      <RequireAuth>
        <AdminReportPreview />
      </RequireAuth>
    ),
  },
  {
    path: "/admin",
    element: (
      <RequireAuth>
        <AppLayout />
      </RequireAuth>
    ),
    children: [
      { index: true, element: <Dashboard /> },
      { path: "customers", element: <RequireSuperAdmin><Customers /></RequireSuperAdmin> },
      { path: "projects", element: <ProjectsList /> },
      // 新建项目 —— 多步向导独立路由,不进入项目列表页。
      { path: "new-project", element: <NewProjectPage /> },
      // 待审核 —— 客户看到自己的申请,管理员看到全部;后端按 session
      // 强制 tenant 范围,前端不做 role 分叉。
      { path: "pending-projects", element: <PendingProjectsList /> },
      // Detail is now an in-place modal opened from the list page; the
      // dedicated route is preserved as a redirect so any old / shared
      // links still land on the editor.
      { path: "projects/:id", element: <ProjectDetail /> },
    ],
  },
  { path: "*", element: <Navigate to="/admin" replace /> },
]);

export default function App() {
  return (
    <AuthProvider>
      <ProjectProvider>
        <RouterProvider router={router} />
      </ProjectProvider>
    </AuthProvider>
  );
}