import { Fragment, useEffect, useMemo, useState } from "react";
import { Layout, Dropdown, Tooltip } from "antd";
import {
  DashboardOutlined,
  ProjectOutlined,
  TeamOutlined,
  ApartmentOutlined,
  BarChartOutlined,
  BookOutlined,
  FileSearchOutlined,
  FundProjectionScreenOutlined,
  InboxOutlined,
  LinkOutlined,
  SettingOutlined,
  LogoutOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
} from "@ant-design/icons";
import { ChevronRight, Plus, User } from "lucide-react";
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
import GlobalToolbar from "../components/GlobalToolbar";
import { ToolbarFilterProvider } from "../components/ToolbarFilterContext";
import "./AppLayout.css";

const { Sider, Header, Content } = Layout;

type AdminKey =
  | "/admin"
  | "/admin/projects"
  | "/admin/customers"
  | "/admin/pending-projects";

type ProjectTabKey =
  | "overview"
  | "question"
  | "competitor"
  | "source"
  | "self-articles"
  | "citation"
  | "answer"
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
  "self-articles": {
    key: "self-articles",
    label: "自有文章引用分析",
    icon: <BookOutlined />,
  },
  citation: { key: "citation", label: "引用源分析", icon: <LinkOutlined /> },
  answer: { key: "answer", label: "答案质量分析", icon: <FileSearchOutlined /> },
  settings: { key: "settings", label: "设置", icon: <SettingOutlined /> },
};

const PROJECT_GROUP_LAYOUT: { title: string; keys: ProjectTabKey[] }[] = [
  {
    title: "数据洞察",
    keys: ["overview", "question", "competitor", "source", "self-articles", "citation"],
  },
  { title: "数据中心", keys: ["answer"] },
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
  "/admin/pending-projects": {
    key: "/admin/pending-projects",
    label: "待审核",
    icon: <InboxOutlined />,
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
  const [siderCollapsed, setSiderCollapsed] = useState(false);

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
      // 待审核 —— 客户看到自己的提交,管理员看到全部;后端按 session
      // 强制 tenant 范围,前端不需要 role 分叉。
      ADMIN_ITEMS["/admin/pending-projects"],
    ];
    if (user?.role === "super_admin") {
      items.push(ADMIN_ITEMS["/admin/customers"]);
    }
    return items;
  }, [user?.role]);

  // 待审核数量 —— 侧栏「待审核」菜单的小红点。
  // customer_admin 只看到自己的,super_admin 看到全部(后端已按 session
  // 收窄)。数量 > 99 显示「99+」。
  const [pendingCount, setPendingCount] = useState<number | null>(null);
  useEffect(() => {
    let cancelled = false;
    // The pre-20260908_0002 surface used ``listPendingProjects`` against a
    // shadow table. The merged surface filters the regular project list
    // by ``status=pending``; the same call shape with the new wire.
    listProjects({ page: 1, size: 1, status: "pending" })
      .then((res) => {
        if (cancelled) return;
        setPendingCount(res.total);
      })
      .catch(() => {
        if (!cancelled) setPendingCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

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
    if (p.startsWith("/admin/pending-projects"))
      return "/admin/pending-projects";
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
    // - /admin/new-project:不走面包屑,改走 header 右侧的"标题 + 副标题"块,
    //   渲染到 .app-header,视觉上像参考 index.html 的 wizard-head。
    if (location.pathname === "/admin/new-project") {
      return (
        <div className="header-title">
          <h2>新增项目</h2>
          <p className="header-sub">按步骤填写项目配置，提交后由后台审核</p>
        </div>
      );
    }
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

  return (
    <Layout className="app-layout">
      <Sider
        className="app-sider"
        width={240}
        collapsedWidth={64}
        collapsed={siderCollapsed}
        trigger={null}
        theme="light"
      >
        <div className="logo">
          <img
            src="/logo.png"
            width={36}
            height={36}
            alt="WINDx"
            className="logo-svg"
          />
          <div className="logo-text">
            <strong>WINDx</strong>
            <span>GEO 监控</span>
          </div>
        </div>

        <ProjectSwitcher
          currentId={currentProjectId === null ? undefined : currentProjectId}
          variant="sidebar"
        />

        <div className="app-sider-scroll">
          {/* 项目级 nav-group:有当前项目上下文时就出现 —— 放在顶部 */}
          {projectGroups.map((g) => (
            <div key={g.title} className="nav-group-block">
              <div className="nav-group-title">{g.title}</div>
              {g.items.map((it) => {
                const k = it.key as ProjectTabKey;
                const btn = (
                  <button
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
                // When the sider is collapsed the text is hidden, so
                // surface the label as a tooltip on hover. In expanded
                // mode the label is already inline, so the tooltip
                // would only be noise.
                return siderCollapsed ? (
                  <Tooltip
                    key={it.key}
                    title={it.label}
                    placement="right"
                    mouseEnterDelay={0}
                  >
                    {btn}
                  </Tooltip>
                ) : (
                  <Fragment key={it.key}>{btn}</Fragment>
                );
              })}
            </div>
          ))}

          {/* 管理组: 工作台 / 监控项目 / 待审核 / 客户管理 —— 放在底部 */}
          <div className="nav-group-block">
            <div className="nav-group-title">管理组</div>
            {adminItems.map((it) => {
              const isPendingLeaf = it.key === "/admin/pending-projects";
              const badge =
                isPendingLeaf && pendingCount !== null && pendingCount > 0
                  ? pendingCount > 99
                    ? "99+"
                    : String(pendingCount)
                  : undefined;
              const btn = (
                <button
                  type="button"
                  className={`nav-leaf${activeAdminKey === it.key ? " active" : ""}`}
                  onClick={() => onAdminClick(it.key as AdminKey)}
                >
                  <span className="nav-leaf-icon">{it.icon}</span>
                  <span className="nav-leaf-text">{it.label}</span>
                  {badge !== undefined && (
                    <span className="nav-leaf-badge nav-leaf-badge-pending">
                      {badge}
                    </span>
                  )}
                </button>
              );
              return siderCollapsed ? (
                <Tooltip
                  key={it.key}
                  title={it.label}
                  placement="right"
                  mouseEnterDelay={0}
                >
                  {btn}
                </Tooltip>
              ) : (
                <Fragment key={it.key}>{btn}</Fragment>
              );
            })}
          </div>
        </div>

        {/* 新建项目主操作入口 —— 参照 index.html #sidebar-create,放在登录信息之上。
           客户点这个按钮走「申请 → 审核」流程;super_admin 点这个按钮直接给目标客户
           起草一份申请。后端按 session 强制 customer_admin 的 customer_id。
           点击直接进入独立向导页(/admin/new-project),不经过项目列表页。
           折叠时只显示 + 图标(配 tooltip),展开时显示图标 + "新建项目"文字。 */}
        {user && (
          <div className="sidebar-create">
            {siderCollapsed ? (
              <Tooltip title="新建项目" placement="right" mouseEnterDelay={0}>
                <button
                  type="button"
                  className="btn-create-project"
                  aria-label="新建项目"
                  onClick={() => navigate("/admin/new-project")}
                >
                  <span className="create-icon">
                    <Plus size={16} strokeWidth={2} />
                  </span>
                </button>
              </Tooltip>
            ) : (
              <button
                type="button"
                className="btn-create-project"
                onClick={() => navigate("/admin/new-project")}
              >
                <span className="create-icon">
                  <Plus size={16} strokeWidth={2} />
                </span>
                <span>新建项目</span>
              </button>
            )}
          </div>
        )}

        <Dropdown menu={userMenu} placement="topRight" trigger={["click"]}>
          <div className="sidebar-user" role="button">
            <div className="user-avatar"><User size={18} strokeWidth={2} /></div>
            <div className="user-info">
              <strong>{user?.username ?? "未登录"}</strong>
              <span>
                {user?.role === "super_admin" ? "超级管理员" : "客户管理员"}
              </span>
            </div>
            <ChevronRight className="user-arrow" size={15} strokeWidth={1.75} />
          </div>
        </Dropdown>
      </Sider>

      <Layout>
        <Header className="app-header">
          <button
            type="button"
            className="header-collapse-btn"
            onClick={() => setSiderCollapsed((v) => !v)}
            title={siderCollapsed ? "展开菜单" : "收起菜单"}
          >
            {siderCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </button>
          <div className="breadcrumb">{breadcrumb}</div>
          <div className="header-right" />
        </Header>
        {/* 全局工具栏 —— 参照 docs/风球GEO监控平台UI/index.html 的
            #global-toolbar。仅在项目详情页显示,其他页面不渲染。
            ToolbarFilterProvider 把「应用」按钮触发的筛选版本号下发给
            各数据 Tab(OverviewTab / QuestionTab ...),保证点确认就刷新。 */}
        <ToolbarFilterProvider>
          <GlobalToolbar visible={currentProjectId !== null && location.pathname.startsWith("/admin/projects/")} />
          <Content className="app-content">
            <Outlet />
          </Content>
        </ToolbarFilterProvider>
      </Layout>
    </Layout>
  );
}
