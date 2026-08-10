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
