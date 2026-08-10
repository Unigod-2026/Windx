import {
  RouterProvider,
  createBrowserRouter,
  Navigate,
} from "react-router-dom";
import { AuthProvider, RequireAuth, RequireSuperAdmin } from "./auth/AuthProvider";
import AppLayout from "./layouts/AppLayout";
import Login from "./pages/Login";
import Dashboard from "./pages/Dashboard";
import Customers from "./pages/Customers";
import ProjectsList from "./pages/Projects/List";
import ProjectDetail from "./pages/Projects/Detail";

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
      <RouterProvider router={router} />
    </AuthProvider>
  );
}
