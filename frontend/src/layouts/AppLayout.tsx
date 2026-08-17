import { useEffect, useMemo, useState } from "react";
import { Layout, Dropdown } from "antd";
import {
  DashboardOutlined,
  ProjectOutlined,
  TeamOutlined,
  ApartmentOutlined,
  BarChartOutlined,
  BulbOutlined,
  ClusterOutlined,
  FileSearchOutlined,
  FundProjectionScreenOutlined,
  LinkOutlined,
  SettingOutlined,
  UserOutlined,
  LogoutOutlined,
} from "@ant-design/icons";
import {
  Outlet,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import { useAuth } from "../auth/AuthProvider";
import { useCurrentProject } from "../auth/ProjectContext";
import ProjectSwitcher from "../pages/Projects/ProjectSwitcher";
import { listProjects, type ProjectOut } from "../api/projects";
import "./AppLayout.css";

const { Sider, Header, Content } = Layout;

type AdminKey = "/admin" | "/admin/projects" | "/admin/customers";

type ProjectTabKey =
  | "overview"
  | "question"
  | "competitor"
  | "source"
  | "citation"
  | "answer"
  | "prompts"
  | "competitors"
  | "settings";

interface NavLeaf {
  key: string;
  label: string;
  icon: React.ReactNode;
  badge?: number;
}

interface NavGroup {
  title: string;
  items: NavLeaf[];
}

const PROJECT_TABS: Record<ProjectTabKey, NavLeaf> = {
  overview: { key: "overview", label: "首屏概览", icon: <FundProjectionScreenOutlined /> },
  question: {
    key: "question",
    label: "问题提及分析",
    icon: <FileSearchOutlined />,
  },
  competitor: { key: "competitor", label: "竞品分析", icon: <BarChartOutlined /> },
  source: { key: "source", label: "信源偏好", icon: <ApartmentOutlined /> },
  citation: { key: "citation", label: "引用源分析", icon: <LinkOutlined /> },
  answer: { key: "answer", label: "AI 回答详情", icon: <FileSearchOutlined /> },
  prompts: { key: "prompts", label: "问题管理", icon: <BulbOutlined /> },
  competitors: { key: "competitors", label: "竞品管理", icon: <ClusterOutlined /> },
  settings: { key: "settings", label: "设置", icon: <SettingOutlined /> },
};

const PROJECT_GROUP_LAYOUT: { title: string; keys: ProjectTabKey[] }[] = [
  {
    title: "数据洞察",
    keys: ["overview", "question", "competitor", "source", "citation"],
  },
  { title: "数据中心", keys: ["answer", "prompts", "competitors"] },
  { title: "系统", keys: ["settings"] },
];

const TAB_GROUP_TITLE = (() => {
  const map = new Map<ProjectTabKey, string>();
  for (const g of PROJECT_GROUP_LAYOUT) {
    for (const k of g.keys) map.set(k, g.title);
  }
  return (k: ProjectTabKey) => map.get(k) ?? "";
})();

const ADMIN_ITEMS: Record<AdminKey, NavLeaf> = {
  "/admin": { key: "/admin", label: "工作台", icon: <DashboardOutlined /> },
  "/admin/projects": {
    key: "/admin/projects",
    label: "监控项目",
    icon: <ProjectOutlined />,
  },
  "/admin/customers": {
    key: "/admin/customers",
    label: "客户管理",
    icon: <TeamOutlined />,
  },
};

const ADMIN_GROUP_TITLE = "管理组";

export default function AppLayout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const params = useParams<{ id?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const { currentProjectId: contextProjectId } = useCurrentProject();

  // URL `:id` wins (it's the most authoritative source). Fall back to the
  // ProjectContext value so the project nav groups survive clicks on
  // 管理组 (e.g. 工作台) without a page refresh.
  const urlProjectId =
    location.pathname.startsWith("/admin/projects/") && params.id
      ? Number(params.id)
      : null;
  const currentProjectId = urlProjectId ?? contextProjectId;

  const adminItems = useMemo<NavLeaf[]>(() => {
    const items: NavLeaf[] = [
      ADMIN_ITEMS["/admin"],
      ADMIN_ITEMS["/admin/projects"],
    ];
    if (user?.role === "super_admin") {
      items.push(ADMIN_ITEMS["/admin/customers"]);
    }
    return items;
  }, [user?.role]);

  // Pull prompts_count for every project the user can see, once per session.
  // ``listProjects`` returns ``ProjectOut[]`` with the count denormalised on
  // the server, so the sider can show a real badge without per-route
  // round-trips. ProjectSwitcher hits the same endpoint; both share this
  // fetch.
  const [promptsCountById, setPromptsCountById] = useState<Map<number, number>>(
    new Map(),
  );
  useEffect(() => {
    let cancelled = false;
    listProjects({ page: 1, size: 100 })
      .then((res) => {
        if (cancelled) return;
        const next = new Map<number, number>();
        for (const p of res.items as ProjectOut[]) {
          next.set(p.id, p.prompts_count ?? 0);
        }
        setPromptsCountById(next);
      })
      .catch(() => {
        // Badge just stays hidden if the list fails to load — the nav
        // itself is unaffected.
      });
    return () => {
      cancelled = true;
    };
  }, [currentProjectId]);

  const projectGroups = useMemo<NavGroup[]>(() => {
    if (currentProjectId === null) return [];
    return PROJECT_GROUP_LAYOUT.map((g) => ({
      title: g.title,
      items: g.keys.map((k) => {
        const leaf = { ...PROJECT_TABS[k] };
        if (k === "question") {
          const n = promptsCountById.get(currentProjectId);
          leaf.badge = n === undefined ? undefined : n;
        }
        return leaf;
      }),
    }));
  }, [currentProjectId, promptsCountById]);

  const activeAdminKey = (() => {
    const p = location.pathname;
    if (p.startsWith("/admin/customers")) return "/admin/customers";
    // 项目详情页(``/admin/projects/:id``)由项目级 nav 接管,管理组不点亮,
    // 避免和当前选中的 tab 同时高亮。
    if (p === "/admin/projects" || p === "/admin/projects/") return "/admin/projects";
    if (p === "/admin" || p === "/admin/") return "/admin";
    return null;
  })();

  const activeProjectKey = (() => {
    if (currentProjectId === null) return null;
    // 只有项目详情页(``/admin/projects/:id``)才算"进了某个 tab";
    // 列表页 / Dashboard / 客户管理即使 ProjectContext 残留 projectId,
    // 也视为"没选具体 tab",避免点 管理组 后侧栏项目组还残留高亮。
    if (!location.pathname.startsWith("/admin/projects/")) return null;
    const tab = searchParams.get("tab") ?? "overview";
    return (PROJECT_TABS[tab as ProjectTabKey] ? tab : "overview") as ProjectTabKey;
  })();

  const onAdminClick = (key: AdminKey) => navigate(key);

  const onProjectClick = (key: ProjectTabKey) => {
    if (currentProjectId === null) return;
    const next = new URLSearchParams(searchParams);
    next.set("tab", key);
    if (params.id) {
      setSearchParams(next, { replace: false });
    } else {
      navigate(`/admin/projects/${currentProjectId}?${next.toString()}`);
    }
  };

  const breadcrumb = (() => {
    // Breadcrumb 始终是"组名 / 菜单名"两段,不挂"工作台"前缀。
    // - 选中管理组某项 → 管理组 / {label}
    // - 选中项目组某个 tab → {数据洞察|数据中心|系统} / {label}
    if (activeAdminKey !== null) {
      return (
        <>
          <strong>{ADMIN_GROUP_TITLE}</strong>
          <span className="sep">/</span>
          <strong>{ADMIN_ITEMS[activeAdminKey].label}</strong>
        </>
      );
    }
    if (activeProjectKey !== null) {
      return (
        <>
          <strong>{TAB_GROUP_TITLE(activeProjectKey)}</strong>
          <span className="sep">/</span>
          <strong>{PROJECT_TABS[activeProjectKey].label}</strong>
        </>
      );
    }
    // 兜底:既不在管理组、也没进项目 tab(理论上路由不会到这)。
    return <strong>{location.pathname}</strong>;
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
        width={240}
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

        <div className="app-sider-scroll">
          {/* 项目级 nav-group:有当前项目上下文时就出现 —— 放在顶部 */}
          {projectGroups.map((g) => (
            <div key={g.title} className="nav-group-block">
              <div className="nav-group-title">{g.title}</div>
              {g.items.map((it) => {
                const k = it.key as ProjectTabKey;
                return (
                  <button
                    key={it.key}
                    type="button"
                    className={`nav-leaf${activeProjectKey === k ? " active" : ""}`}
                    onClick={() => onProjectClick(k)}
                  >
                    <span className="nav-leaf-icon">{it.icon}</span>
                    <span className="nav-leaf-text">{it.label}</span>
                    {it.badge !== undefined && (
                      <span className="nav-leaf-badge">{it.badge}</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}

          {/* 管理组: 工作台 / 监控项目 / 客户管理 —— 放在底部 */}
          <div className="nav-group-block">
            <div className="nav-group-title">管理组</div>
            {adminItems.map((it) => (
              <button
                key={it.key}
                type="button"
                className={`nav-leaf${activeAdminKey === it.key ? " active" : ""}`}
                onClick={() => onAdminClick(it.key as AdminKey)}
              >
                <span className="nav-leaf-icon">{it.icon}</span>
                <span className="nav-leaf-text">{it.label}</span>
              </button>
            ))}
          </div>
        </div>
      </Sider>

      <Layout>
        <Header className="app-header">
          <div className="breadcrumb">{breadcrumb}</div>
          <div className="header-right">
            <ProjectSwitcher
              currentId={currentProjectId === null ? undefined : currentProjectId}
              variant="header"
            />
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
