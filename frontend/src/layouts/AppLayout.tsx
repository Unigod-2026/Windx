import { useMemo } from "react";
import { Layout, Menu, Dropdown } from "antd";
import {
  DashboardOutlined,
  ProjectOutlined,
  TeamOutlined,
  UserOutlined,
  LogoutOutlined,
} from "@ant-design/icons";
import { Outlet, useLocation, useNavigate, Link } from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import "./AppLayout.css";

const { Sider, Header, Content } = Layout;

type MenuItem = {
  key: string;
  label: string;
  icon: React.ReactNode;
};

export default function AppLayout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const items: MenuItem[] = useMemo(() => {
    const base: MenuItem[] = [
      { key: "/admin", label: "工作台", icon: <DashboardOutlined /> },
      { key: "/admin/projects", label: "监控项目", icon: <ProjectOutlined /> },
    ];
    if (user?.role === "super_admin") {
      base.push({
        key: "/admin/customers",
        label: "客户管理",
        icon: <TeamOutlined />,
      });
    }
    return base;
  }, [user?.role]);

  // Match the deepest path the menu can map to.
  const selectedKey = (() => {
    const path = location.pathname;
    if (path.startsWith("/admin/customers")) return "/admin/customers";
    if (path.startsWith("/admin/projects")) return "/admin/projects";
    if (path === "/admin" || path === "/admin/") return "/admin";
    return path;
  })();

  const breadcrumb = (() => {
    const path = location.pathname;
    if (path === "/admin") {
      return (
        <>
          <strong>工作台</strong>
        </>
      );
    }
    if (path.startsWith("/admin/customers")) {
      return (
        <>
          <Link to="/admin">工作台</Link>
          <span className="sep">/</span>
          <strong>客户管理</strong>
        </>
      );
    }
    if (path.startsWith("/admin/projects")) {
      const segments = path.split("/").filter(Boolean);
      if (segments.length >= 3) {
        return (
          <>
            <Link to="/admin">工作台</Link>
            <span className="sep">/</span>
            <Link to="/admin/projects">监控项目</Link>
            <span className="sep">/</span>
            <strong>项目详情</strong>
          </>
        );
      }
      return (
        <>
          <Link to="/admin">工作台</Link>
          <span className="sep">/</span>
          <strong>监控项目</strong>
        </>
      );
    }
    return <strong>{path}</strong>;
  })();

  const userMenu = {
    items: [
      {
        key: "logout",
        icon: <LogoutOutlined />,
        label: "退出登录",
        onClick: logout,
      },
    ],
  };

  const initial = (user?.username ?? "?").slice(0, 1).toUpperCase();

  return (
    <Layout className="app-layout">
      <Sider
        className="app-sider"
        width={220}
        breakpoint="lg"
        collapsedWidth={0}
      >
        <div className="logo">
          <div className="logo-mark">w</div>
          <div className="logo-text">
            <strong>windx</strong>
            <span>AI 品牌监控平台</span>
          </div>
        </div>
        <Menu
          className="app-menu"
          mode="inline"
          selectedKeys={[selectedKey]}
          onClick={({ key }) => navigate(key)}
          items={items}
        />
      </Sider>
      <Layout>
        <Header className="app-header">
          <div className="breadcrumb">{breadcrumb}</div>
          <div className="header-right">
            <Dropdown menu={userMenu} placement="bottomRight">
              <div className="user-chip">
                <div className="avatar">{initial}</div>
                <div className="meta">
                  <strong>{user?.username ?? "未登录"}</strong>
                  <span>
                    {user?.role === "super_admin" ? "超级管理员" : "客户管理员"}
                  </span>
                </div>
                <UserOutlined style={{ fontSize: 12, color: "#bfbfbf" }} />
              </div>
            </Dropdown>
          </div>
        </Header>
        <Content className="app-content">
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}
