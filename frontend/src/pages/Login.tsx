import { useState } from "react";
import { Form, Input, Button, Checkbox, message } from "antd";
import { UserOutlined, LockOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import client from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { useSetCurrentProject } from "../auth/ProjectContext";
import { listProjects } from "../api/projects";
import "./Login.css";

interface LoginValues {
  username: string;
  password: string;
}

export default function Login() {
  const { setUser } = useAuth();
  const setCurrentProjectId = useSetCurrentProject();
  const nav = useNavigate();
  const [loading, setLoading] = useState(false);

  const onFinish = async (v: LoginValues) => {
    setLoading(true);
    try {
      const r = await client.post<{ token: string }>("/auth/login", v);
      localStorage.setItem("token", r.data.token);
      const me = await client.get("/auth/me");
      setUser(me.data);
      // 默认项目:super_admin/customer_admin 都拿「最新创建的 active 项目」。
      // 后端 listProjects 按 session 自动收窄 customer_admin 到自己的客户。
      const res = await listProjects({ status: "active", page: 1, size: 1 });
      const latest = res.items[0];
      if (latest) setCurrentProjectId(latest.id);
      nav(latest ? `/admin/projects/${latest.id}?tab=overview` : "/admin");
    } catch (err: any) {
      const status = err?.response?.status;
      if (status === 403) {
        message.error("账号已被停用，请联系管理员");
      } else if (status === 401) {
        message.error("用户名或密码错误");
      } else {
        message.error("登录失败，请稍后重试");
      }
    } finally {
      setLoading(false);
    }
  };

  const placeholderToast = () => {
    message.info("暂未开通，敬请期待");
  };

  return (
    <div className="page-login">
      <div className="login-bg">
        <div className="login-bg-shape shape-1" />
        <div className="login-bg-shape shape-2" />
        <div className="login-bg-shape shape-3" />
      </div>
      <div className="login-container">
        <div className="login-left">
          <div className="brand-block">
            <div className="brand-logo">
              <img src="/logo.png" width={56} height={56} alt="WINDx" />
            </div>
            <div className="brand-text">
              <h1>WINDx</h1>
              <p>风球科技 GEO 监控平台</p>
            </div>
          </div>

          <div className="login-slogan">
            <h2>看见品牌在 AI 世界中的样子</h2>
            <p>
              实时监测 7 大主流大模型对您品牌的提及、推荐与情感倾向，洞察竞品动态，掌握信源话语权。
            </p>
          </div>

          <div className="login-features">
            <div className="feature-item">
              <div className="feature-icon icon-monitor" />
              <div className="feature-text">
                <strong>全模型覆盖</strong>
                <span>豆包 · 元宝 · 通义千问 · Kimi · DeepSeek · 文心一言 · 蚂蚁阿福</span>
              </div>
            </div>
            <div className="feature-item">
              <div className="feature-icon icon-chart" />
              <div className="feature-text">
                <strong>多维数据分析</strong>
                <span>提及率 · 排名 · 情感 · 引用源 · 竞品对比</span>
              </div>
            </div>
            <div className="feature-item">
              <div className="feature-icon icon-alert" />
              <div className="feature-text">
                <strong>实时告警</strong>
                <span>排名骤降 · 竞品超越 · 负面提及 · 信源异动</span>
              </div>
            </div>
          </div>
        </div>

        <div className="login-right">
          <div className="login-card">
            <div className="login-card-header">
              <h3>登录账号</h3>
              <p>欢迎回来，继续监控您的品牌影响力</p>
            </div>

            <Form<LoginValues>
              onFinish={onFinish}
              layout="vertical"
              requiredMark={false}
            >
              <Form.Item
                name="username"
                label="账号 / 邮箱"
                rules={[{ required: true, message: "请输入账号或邮箱" }]}
              >
                <Input
                  size="large"
                  prefix={<UserOutlined />}
                  placeholder="请输入账号或邮箱"
                  autoComplete="username"
                />
              </Form.Item>
              <Form.Item
                name="password"
                label="密码"
                rules={[{ required: true, message: "请输入密码" }]}
              >
                <Input.Password
                  size="large"
                  prefix={<LockOutlined />}
                  placeholder="请输入密码"
                  autoComplete="current-password"
                />
              </Form.Item>

              <div className="login-options">
                <Checkbox>7 天内自动登录</Checkbox>
                <a className="link" onClick={placeholderToast}>
                  忘记密码？
                </a>
              </div>

              <Button
                type="primary"
                htmlType="submit"
                size="large"
                block
                loading={loading}
                className="login-submit"
              >
                登 录
              </Button>
            </Form>

            <div className="login-divider">
              <span>其他登录方式</span>
            </div>
            <div className="login-social">
              <button
                type="button"
                className="social-btn"
                onClick={placeholderToast}
              >
                微信
              </button>
              <button
                type="button"
                className="social-btn"
                onClick={placeholderToast}
              >
                企微
              </button>
              <button
                type="button"
                className="social-btn"
                onClick={placeholderToast}
              >
                钉钉
              </button>
              <button
                type="button"
                className="social-btn"
                onClick={placeholderToast}
              >
                SSO
              </button>
            </div>

            <div className="login-footer">
              还没有账号？<a className="link" onClick={placeholderToast}>立即注册</a>
            </div>
          </div>

          <div className="login-meta">
            © 2026 风球科技 · WINDx Technology · 京ICP备XXXXXXXX号
          </div>
        </div>
      </div>
    </div>
  );
}
