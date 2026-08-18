import { useState } from "react";
import { Form, Input, Button, Card, Alert, Space, Tag } from "antd";
import { useNavigate } from "react-router-dom";
import client from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { getDashboard } from "../api/dashboard";
import "../layouts/AppLayout.css";

interface LoginValues {
  username: string;
  password: string;
}

export default function Login() {
  const { setUser } = useAuth();
  const nav = useNavigate();
  const [loading, setLoading] = useState(false);
  const [devLoading, setDevLoading] = useState(false);
  const [hint, setHint] = useState<string | null>(
    "提示:登录接口 /api/auth/login 尚未实现。可以使用「Mock 登录」进入开发态(仅本地)。"
  );

  const onFinish = async (v: LoginValues) => {
    setLoading(true);
    setHint(null);
    try {
      const r = await client.post<{ token: string }>("/auth/login", v);
      localStorage.setItem("token", r.data.token);
      const me = await client.get("/auth/me");
      setUser(me.data);
      nav(await resolveDefaultProject());
    } catch {
      setHint(
        "登录失败:后端 /api/auth/login 尚未实现(预期行为)。请使用「Mock 登录」继续开发,或稍后重试。"
      );
    } finally {
      setLoading(false);
    }
  };

  // Resolve the URL to land on after login. super_admin and customer_admin
  // both default to the most recently triggered project (the backend scopes
  // recent_runs by tenant); if there are no runs yet we fall back to the
  // admin dashboard.
  const resolveDefaultProject = async (): Promise<string> => {
    try {
      const dash = await getDashboard();
      const latest = dash.recent_runs[0];
      if (latest) return `/admin/projects/${latest.project_id}?tab=overview`;
    } catch {
      // fall through
    }
    return "/admin";
  };

  // Dev-only "mock login": sets a fake token and creates a super_admin user
  // so the dev experience works before /api/auth/login is implemented.
  const mockLogin = async (role: "super_admin" | "customer_admin") => {
    setDevLoading(true);
    localStorage.setItem("token", `mock-token-${role}-${Date.now()}`);
    setUser({
      id: 1,
      username: role === "super_admin" ? "dev-super" : "dev-customer",
      role,
      customer_id: role === "super_admin" ? null : 1,
    });
    nav(await resolveDefaultProject());
  };

  return (
    <div className="login-page">
      <Card className="login-card" bordered={false}>
        <div className="login-brand">
          <div className="mark">w</div>
          <div className="text">
            <strong>windx 管理后台</strong>
            <span>AI 品牌监控平台</span>
          </div>
        </div>

        {hint && (
          <Alert
            type="info"
            showIcon
            message={hint}
            style={{ marginBottom: 16, fontSize: 12 }}
          />
        )}

        <Form<LoginValues> onFinish={onFinish} layout="vertical" size="large">
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: "请输入用户名" }]}
          >
            <Input placeholder="admin" autoComplete="username" />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: "请输入密码" }]}
          >
            <Input.Password
              placeholder="••••••"
              autoComplete="current-password"
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" block loading={loading}>
            登录
          </Button>
        </Form>

        <div style={{ marginTop: 16 }}>
          <Space direction="vertical" style={{ width: "100%" }} size={8}>
            <div style={{ fontSize: 12, color: "#8c8c8c" }}>
              开发态快捷登录 <Tag color="orange">Mock</Tag>
            </div>
            <Space>
              <Button
                size="small"
                onClick={() => mockLogin("super_admin")}
                loading={devLoading}
              >
                Mock super_admin
              </Button>
              <Button
                size="small"
                onClick={() => mockLogin("customer_admin")}
                loading={devLoading}
              >
                Mock customer_admin
              </Button>
            </Space>
          </Space>
        </div>
      </Card>
    </div>
  );
}
