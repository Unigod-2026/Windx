import {
  createContext,
  useContext,
  useEffect,
  useState,
  ReactNode,
  ReactElement,
} from "react";
import { Navigate } from "react-router-dom";
import { Spin } from "antd";
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

function FullPageSpin() {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: "100vh",
      }}
    >
      <Spin size="large" />
    </div>
  );
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  // True until the mount-time /auth/me probe settles. ``RequireAuth``
  // uses this so a hard refresh doesn't bounce to /login while the
  // probe is still in flight — first render starts with ``user=null``,
  // and without this gate the route would redirect even when the
  // localStorage token is valid.
  const [ready, setReady] = useState(false);

  // Decide the initial ready state synchronously: if there's no token
  // to validate, there's nothing to wait for, so the first render is
  // already valid. Only the "token present, probing /auth/me" path
  // needs the gate.
  const [hasToken] = useState(() => Boolean(localStorage.getItem("token")));

  useEffect(() => {
    if (!hasToken) {
      setReady(true);
      return;
    }
    client
      .get<User>("/auth/me")
      .then((r) => setUser(r.data))
      .catch(() => setUser(null))
      .finally(() => setReady(true));
  }, [hasToken]);

  const logout = () => {
    localStorage.removeItem("token");
    setUser(null);
    window.location.href = "/login";
  };

  return (
    <Ctx.Provider value={{ user, setUser, logout }}>
      {hasToken && !ready ? <FullPageSpin /> : children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  return useContext(Ctx);
}

export function RequireAuth({ children }: { children: ReactElement }) {
  // ``ready`` is consumed off the provider; once it's true we evaluate
  // the user. If neither is set yet, the AuthProvider's full-page Spin
  // is already covering the screen — but we re-check here as a defensive
  // guard in case RequireAuth is mounted outside the provider.
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