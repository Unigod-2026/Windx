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
import NewProjectPage from "./pages/Projects/NewProject";
import PendingProjectsList from "./pages/PendingProjects/List";

const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  { path: "/", element: <Navigate to="/admin" replace /> },
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
