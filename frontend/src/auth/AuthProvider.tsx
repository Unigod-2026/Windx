import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
  ReactElement,
} from "react";
import { Navigate } from "react-router-dom";
import client from "../api/client";

export type Role = "super_admin" | "customer_admin";

export interface User {
  id: number;
  username: string;
  role: Role;
  customer_id: number | null;
}

interface AuthCtx {
  user: User | null;
  setUser: (u: User | null) => void;
  logout: () => void;
}

const Ctx = createContext<AuthCtx>({
  user: null,
  setUser: () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (!token) return;
    client
      .get<User>("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => setUser(null));
  }, []);

  const logout = () => {
    localStorage.removeItem("token");
    setUser(null);
    window.location.href = "/login";
  };

  return (
    <Ctx.Provider value={{ user, setUser, logout }}>{children}</Ctx.Provider>
  );
}

export function useAuth() {
  return useContext(Ctx);
}

export function RequireAuth({ children }: { children: ReactElement }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export function RequireSuperAdmin({ children }: { children: ReactElement }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "super_admin") return <Navigate to="/admin" replace />;
  return children;
}
