/**
 * 「设置」sub-tab —— 参照 docs/风球GEO监控平台UI-261005/index.html:1804-2019
 * 拆出两个 sub-pane:
 *   - account(账号设置):个人信息 / 修改密码 / 通知设置
 *   - perm   (用户权限):角色说明 / 权限矩阵 / 用户列表 / 租户管理
 *
 * 数据可用范围(2026-10-08):
 *   - 当前用户 ``useAuth().user`` 有 email / phone / notification_prefs,由
 *     后端 ``/auth/me`` 返回;无 customer_name 时靠 listCustomers 反查。
 *   - PATCH /api/auth/me + POST /api/auth/change-password 真实落库
 *     (super_admin 邮箱 / 手机号强制 readonly,要求后台手动调整)。
 *   - 客户列表 ``listCustomers()`` 已有,租户管理直接消费。
 *
 * sub-tab 路由用 ``?sub=account|perm``(URLSearchParams),刷新保留。
 * perm sub-tab 仅对 super_admin 开放,其他角色看到「请联系超级管理员」提示。
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  Avatar,
  Button,
  Empty,
  Form,
  Input,
  Switch,
  Tag,
  message,
} from "antd";
import {
  EditOutlined,
  LockOutlined,
  NotificationOutlined,
  TeamOutlined,
  ApartmentOutlined,
  UserSwitchOutlined,
} from "@ant-design/icons";
import { useAuth, type NotificationPrefs, type User } from "../../../auth/AuthProvider";
import { listCustomers, type Customer } from "../../../api/customers";
import { listProjects, type ProjectOut } from "../../../api/projects";
import { patchMe, changePassword } from "../../../api/auth";

type SettingsSub = "account" | "perm";

const SUB_TABS: { key: SettingsSub; label: string }[] = [
  { key: "account", label: "账号设置" },
  { key: "perm", label: "用户权限" },
];

// 4 角色色板 —— 对齐 docs/风球GEO监控平台UI-261005/v3.7 降饱和 7 色:
// super_admin=豆包蓝 / customer_admin=元宝橙 / member=通义绿 / viewer=Kimi 紫
const ROLE_COLOR: Record<string, string> = {
  super_admin: "#3f6bc4",
  customer_admin: "#c9803a",
  member: "#3d9070",
  viewer: "#8250bd",
};

const ROLE_LABEL: Record<string, string> = {
  super_admin: "超级管理员",
  customer_admin: "客户管理员",
  member: "普通用户",
  viewer: "客户",
};

// 角色说明卡(对齐 doc role-cards)
const ROLE_DESCRIPTIONS: Array<{ key: string; name: string; desc: string }> = [
  { key: "super_admin", name: "超级管理员", desc: "平台运营,管理所有客户、用户与系统配置" },
  { key: "customer_admin", name: "客户管理员", desc: "租户主账号,管理本租户项目与子账号" },
  { key: "member", name: "普通用户", desc: "租户内成员,可查看与使用授权范围内的功能" },
  { key: "viewer", name: "客户", desc: "只读账号,查看已分享的报告与面板" },
];

// 权限矩阵 —— 功能模块 × 角色权限
// ✓ = 全权限, △ = 部分权限, — = 无权限;本期 hardcode,后端权限引擎下个版本上线
const PERM_MATRIX: Array<{ module: string; cells: Record<string, "✓" | "△" | "—"> }> = [
  { module: "项目创建 / 编辑", cells: { super_admin: "✓", customer_admin: "△", member: "—", viewer: "—" } },
  { module: "项目查看", cells: { super_admin: "✓", customer_admin: "✓", member: "✓", viewer: "△" } },
  { module: "监控数据导出", cells: { super_admin: "✓", customer_admin: "✓", member: "△", viewer: "—" } },
  { module: "周报编辑 / 发布", cells: { super_admin: "✓", customer_admin: "△", member: "—", viewer: "—" } },
  { module: "客户管理", cells: { super_admin: "✓", customer_admin: "—", member: "—", viewer: "—" } },
  { module: "用户管理", cells: { super_admin: "✓", customer_admin: "△", member: "—", viewer: "—" } },
  { module: "系统设置", cells: { super_admin: "✓", customer_admin: "—", member: "—", viewer: "—" } },
  { module: "数据字典导入", cells: { super_admin: "✓", customer_admin: "△", member: "—", viewer: "—" } },
];

// 通知偏好 localStorage 键 —— 后端是 source of truth,localStorage 只做
// (1) 切 tab / 切项目时的乐观 UI;(2) 后端 PATCH 失败时回退读盘,保证
// 「通知偏好永不为 0」体验。key 命名稳定,后端字段叫 notification_prefs。
const NOTIF_STORAGE_KEY = "windx.notif.v1";

const NOTIF_DEFAULTS: NotificationPrefs = {
  mention: true,
  drop: true,
  report: true,
  system: false,
};

function loadNotifLocal(): NotificationPrefs {
  try {
    const raw = localStorage.getItem(NOTIF_STORAGE_KEY);
    if (!raw) return NOTIF_DEFAULTS;
    const parsed = JSON.parse(raw) as Partial<NotificationPrefs>;
    return { ...NOTIF_DEFAULTS, ...parsed };
  } catch {
    return NOTIF_DEFAULTS;
  }
}

function saveNotifLocal(p: NotificationPrefs) {
  try {
    localStorage.setItem(NOTIF_STORAGE_KEY, JSON.stringify(p));
  } catch {
    // localStorage 写失败(隐私模式 / 容量满)静默。
  }
}

export default function SettingsPane() {
  const { user, setUser } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const subParam = searchParams.get("sub");
  const sub: SettingsSub = subParam === "perm" ? "perm" : "account";

  // 顶层拉一次 customers,AccountPane(展示所属客户名) + PermPane(租户管理)共用。
  // 5xx / 网络错误容错到空数组,UI 显示「—」而不是炸红。
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [customersLoading, setCustomersLoading] = useState(true);
  useEffect(() => {
    let cancelled = false;
    listCustomers({ page: 1, size: 200 })
      .then((d) => {
        if (cancelled) return;
        setCustomers(d.items);
      })
      .catch(() => {
        if (cancelled) return;
        setCustomers([]);
      })
      .finally(() => {
        if (!cancelled) setCustomersLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const switchSub = (next: SettingsSub) => {
    const sp = new URLSearchParams(searchParams);
    if (next === "account") sp.delete("sub");
    else sp.set("sub", next);
    setSearchParams(sp, { replace: false });
  };

  return (
    <div className="set-root">
      <div className="secondary-tabs">
        {SUB_TABS.map((t) => (
          <div
            key={t.key}
            className={`secondary-tab${sub === t.key ? " active" : ""}`}
            onClick={() => switchSub(t.key)}
          >
            {t.label}
          </div>
        ))}
      </div>

      <div className="set-content">
        {sub === "account" ? (
          <AccountPane
            user={user}
            setUser={setUser}
            customers={customers}
            customersLoading={customersLoading}
          />
        ) : (
          <PermPane
            currentUserRole={user?.role ?? null}
            customers={customers}
          />
        )}
      </div>

      <style>{SETTINGS_CSS}</style>
    </div>
  );
}

/* ------------------------------------------------------------------
 * sub-pane 1: 账号设置
 * ------------------------------------------------------------------ */

function AccountPane({
  user,
  setUser,
  customers,
  customersLoading,
}: {
  user: User | null;
  setUser: (u: User | null) => void;
  customers: Customer[];
  customersLoading: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [pwdForm] = Form.useForm<{ oldPwd: string; newPwd: string; newPwd2: string }>();
  const [pwdSaving, setPwdSaving] = useState(false);
  // 通知偏好 —— 以「后端是 source of truth」为前提,首屏从 user.notification_prefs 取
  // (若缺失回退到 localStorage),用户切换开关触发 PATCH 后端,失败回退到 localStorage。
  const [notif, setNotif] = useState<NotificationPrefs>(
    () => user?.notification_prefs ?? loadNotifLocal(),
  );
  // 通知防抖:200ms 静默期内多次切换合并成一次 PATCH,避免来回拨开关时刷后端。
  const notifTimerRef = useRef<number | null>(null);
  useEffect(() => {
    if (notifTimerRef.current !== null) window.clearTimeout(notifTimerRef.current);
    notifTimerRef.current = window.setTimeout(() => {
      if (!user) return;
      patchMe({ notification_prefs: notif })
        .then((u) => {
          setUser(u);
          saveNotifLocal(notif);
        })
        .catch(() => {
          // 后端失败 → 回退到 localStorage,保证 UI 不空;下次刷新会重新从
          // /me 拿,服务端真值永远是 source of truth。
          saveNotifLocal(notif);
        });
    }, 200);
    return () => {
      if (notifTimerRef.current !== null) window.clearTimeout(notifTimerRef.current);
    };
  }, [notif, user, setUser]);

  if (!user) return <Empty description="未登录" />;

  const isSuperAdmin = user.role === "super_admin";

  const onSaveProfile = async (vals: { name: string; email: string; phone: string }) => {
    setSaving(true);
    try {
      const updated = await patchMe({
        email: vals.email.trim() || null,
        phone: vals.phone.trim() || null,
      });
      setUser(updated);
      saveNotifLocal(updated.notification_prefs ?? notif);
      message.success("个人信息已保存");
      setEditing(false);
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err as Error).message;
      message.error(typeof detail === "string" ? detail : "保存失败");
    } finally {
      setSaving(false);
    }
  };
  const onCancelEdit = () => setEditing(false);

  const onChangePwd = async () => {
    let vals: { oldPwd: string; newPwd: string; newPwd2: string };
    try {
      vals = await pwdForm.validateFields();
    } catch {
      return; // antd validateFields 失败时已经标红
    }
    if (vals.newPwd !== vals.newPwd2) {
      message.error("两次输入的新密码不一致");
      return;
    }
    setPwdSaving(true);
    try {
      await changePassword({ old_password: vals.oldPwd, new_password: vals.newPwd });
      message.success("密码已修改,请用新密码重新登录");
      pwdForm.resetFields();
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        (err as Error).message;
      message.error(typeof detail === "string" ? detail : "修改密码失败");
    } finally {
      setPwdSaving(false);
    }
  };
  const onResetPwd = () => pwdForm.resetFields();

  // 所属客户:super_admin 永远「-」disabled;customer_admin 反查 customers 拿名字。
  const customerName = (() => {
    if (isSuperAdmin) return "-";
    if (user.customer_id === null) return "—";
    const found = customers.find((c) => c.id === user.customer_id);
    return found?.name ?? `客户 #${user.customer_id}`;
  })();

  return (
    <div className="set-stack">
      {/* 个人信息 panel */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>个人信息</h3>
            <p>当前登录账号的基础信息{isSuperAdmin ? "(超级管理员邮箱 / 手机号需联系后台调整)" : ""}</p>
          </div>
          <Button
            size="small"
            icon={<EditOutlined />}
            onClick={() => setEditing((v) => !v)}
            disabled={editing}
          >
            编辑
          </Button>
        </div>
        <div className="panel-body">
          <div className="set-profile">
            <Avatar
              size={56}
              style={{
                background: `linear-gradient(135deg, ${ROLE_COLOR[user.role] ?? "#1a55e8"}, #4d80f0)`,
                fontSize: 22,
                fontWeight: 600,
              }}
            >
              {user.username.slice(0, 1).toUpperCase()}
            </Avatar>
            <div className="set-profile-main">
              <div className="set-name">{user.username}</div>
              <div className="set-sub">
                <Tag color={ROLE_COLOR[user.role] ? "default" : "default"} style={{ background: ROLE_COLOR[user.role] + "22", color: ROLE_COLOR[user.role], borderColor: ROLE_COLOR[user.role] + "55" }}>
                  {ROLE_LABEL[user.role] ?? user.role}
                </Tag>
                {user.customer_id !== null && (
                  <span style={{ marginLeft: 8 }}>租户 #{user.customer_id}</span>
                )}
                <span style={{ marginLeft: 8 }}>账号启用中</span>
              </div>
            </div>
          </div>
          {/* 编辑态:姓名 / 邮箱 / 手机号 可填;super_admin 邮箱 / 手机号 强制 disabled
              (后端 PATCH /me 会拒)。保存走 onSaveProfile,调 patchMe 真实落库。 */}
          {editing ? (
            <Form
              layout="vertical"
              className="set-form"
              initialValues={{
                name: user.username,
                email: user.email ?? "",
                phone: user.phone ?? "",
              }}
              onFinish={onSaveProfile}
            >
              <div className="set-form-row">
                <Form.Item
                  label="姓名"
                  name="name"
                  rules={[{ required: true, message: "请输入姓名" }]}
                  className="set-form-group"
                >
                  <Input placeholder="请输入姓名" maxLength={64} />
                </Form.Item>
                <Form.Item
                  label="邮箱"
                  name="email"
                  rules={[
                    {
                      validator: (_, v: string) => {
                        if (!v) return Promise.resolve();
                        if (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(v)) return Promise.resolve();
                        return Promise.reject(new Error("邮箱格式不正确"));
                      },
                    },
                  ]}
                  className="set-form-group"
                >
                  <Input
                    placeholder="example@windx.com"
                    maxLength={128}
                    disabled={isSuperAdmin}
                  />
                </Form.Item>
              </div>
              <div className="set-form-row">
                <Form.Item
                  label="手机号"
                  name="phone"
                  className="set-form-group"
                >
                  <Input placeholder="请输入手机号" maxLength={32} disabled={isSuperAdmin} />
                </Form.Item>
                <div className="set-form-group">
                  <label>所属客户</label>
                  <Input value={customerName} readOnly variant="borderless" />
                </div>
              </div>
              <div className="set-form-actions">
                <Button type="primary" size="small" htmlType="submit" loading={saving}>
                  保存
                </Button>
                <Button size="small" onClick={onCancelEdit}>
                  取消
                </Button>
              </div>
            </Form>
          ) : (
            <div className="set-form">
              <div className="set-form-row">
                <div className="set-form-group">
                  <label>姓名</label>
                  <Input value={user.username} readOnly variant="borderless" />
                </div>
                <div className="set-form-group">
                  <label>邮箱</label>
                  <Input
                    value={user.email ?? "—"}
                    readOnly
                    placeholder="未设置"
                    variant="borderless"
                  />
                </div>
              </div>
              <div className="set-form-row">
                <div className="set-form-group">
                  <label>手机号</label>
                  <Input
                    value={user.phone ?? "—"}
                    readOnly
                    placeholder="未设置"
                    variant="borderless"
                  />
                </div>
                <div className="set-form-group">
                  <label>所属客户</label>
                  <Input
                    value={customersLoading ? "加载中…" : customerName}
                    readOnly
                    variant="borderless"
                  />
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 修改密码 panel */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>修改密码</h3>
            <p>至少 8 位,需含字母与数字</p>
          </div>
        </div>
        <div className="panel-body">
          <Form form={pwdForm} layout="vertical" className="set-form">
            <div className="set-form-group">
              <label>当前密码</label>
              <Form.Item
                name="oldPwd"
                rules={[{ required: true, message: "请输入当前密码" }]}
                noStyle
              >
                <Input.Password placeholder="请输入当前密码" autoComplete="current-password" />
              </Form.Item>
            </div>
            <div className="set-form-row">
              <div className="set-form-group">
                <label>新密码</label>
                <Form.Item
                  name="newPwd"
                  rules={[
                    { required: true, message: "请输入新密码" },
                    { min: 8, message: "密码至少 8 位" },
                    {
                      validator: (_, v: string) => {
                        if (!v) return Promise.resolve();
                        if (!/[A-Za-z]/.test(v)) return Promise.reject(new Error("密码必须包含字母"));
                        if (!/\d/.test(v)) return Promise.reject(new Error("密码必须包含数字"));
                        return Promise.resolve();
                      },
                    },
                  ]}
                  noStyle
                >
                  <Input.Password
                    placeholder="至少 8 位,需含字母与数字"
                    autoComplete="new-password"
                  />
                </Form.Item>
              </div>
              <div className="set-form-group">
                <label>确认新密码</label>
                <Form.Item
                  name="newPwd2"
                  rules={[{ required: true, message: "请再次输入新密码" }]}
                  noStyle
                >
                  <Input.Password placeholder="请再次输入新密码" autoComplete="new-password" />
                </Form.Item>
              </div>
            </div>
            <div className="set-form-actions">
              <Button
                type="primary"
                size="small"
                icon={<LockOutlined />}
                onClick={onChangePwd}
                loading={pwdSaving}
              >
                修改密码
              </Button>
              <Button size="small" onClick={onResetPwd}>
                清空
              </Button>
            </div>
          </Form>
        </div>
      </div>

      {/* 通知设置 panel —— Switch 切换触发 debounced PATCH /me,失败回退 localStorage */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>通知设置</h3>
            <p>切换后自动保存到后端(账号维度),失败时回退本机缓存</p>
          </div>
          <NotificationOutlined style={{ color: "var(--text-tertiary)", fontSize: 18 }} />
        </div>
        <div className="panel-body">
          <div className="set-notice-list">
            <NoticeItem
              title="提及告警"
              desc="品牌提及率单日跌幅超过 10% 时推送"
              checked={notif.mention}
              onChange={(v) => setNotif((p) => ({ ...p, mention: v }))}
            />
            <NoticeItem
              title="掉落告警"
              desc="问题从 Top3 掉落至 Top10 以外时推送"
              checked={notif.drop}
              onChange={(v) => setNotif((p) => ({ ...p, drop: v }))}
            />
            <NoticeItem
              title="双周报告"
              desc="每双周自动生成《GEO 周报》后提醒"
              checked={notif.report}
              onChange={(v) => setNotif((p) => ({ ...p, report: v }))}
            />
            <NoticeItem
              title="系统公告"
              desc="平台版本更新、维护窗口等通知"
              checked={notif.system}
              onChange={(v) => setNotif((p) => ({ ...p, system: v }))}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

function NoticeItem({
  title,
  desc,
  checked,
  onChange,
}: {
  title: string;
  desc: string;
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="set-notice-item">
      <div className="set-notice-main">
        <div className="set-notice-title">{title}</div>
        <div className="set-notice-desc">{desc}</div>
      </div>
      <Switch checked={checked} onChange={onChange} />
    </label>
  );
}

/* ------------------------------------------------------------------
 * sub-pane 2: 用户权限
 * ------------------------------------------------------------------ */

function PermPane({
  currentUserRole,
  customers,
}: {
  currentUserRole: string | null;
  customers: Customer[];
}) {
  // 权限矩阵 / 用户列表 / 租户管理 仅 super_admin 可见;
  // customer_admin / member / viewer 看到「请联系超级管理员」提示。
  if (currentUserRole !== "super_admin") {
    return (
      <div className="panel">
        <div className="panel-body">
          <Empty
            image={<TeamOutlined style={{ fontSize: 56, color: "var(--text-tertiary)" }} />}
            imageStyle={{ height: 72 }}
            description={
              <div className="set-empty-desc">
                <h4>仅超级管理员可访问</h4>
                <p>
                  用户与租户管理由超级管理员在「客户管理」中维护。如需变更账号 / 权限,
                  请联系超级管理员处理。
                </p>
              </div>
            }
          />
        </div>
      </div>
    );
  }

  return (
    <div className="set-stack">
      {/* 角色说明卡 */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>角色说明</h3>
            <p>平台 4 级角色权限模型</p>
          </div>
        </div>
        <div className="panel-body">
          <div className="set-role-grid">
            {ROLE_DESCRIPTIONS.map((r) => (
              <div key={r.key} className="set-role-card">
                <span
                  className="set-role-stripe"
                  style={{ background: ROLE_COLOR[r.key] ?? "#bfbfbf" }}
                />
                <div className="set-role-name">{r.name}</div>
                <div className="set-role-desc">{r.desc}</div>
                <div className="set-role-key">{r.key}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 权限矩阵 */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>权限矩阵</h3>
            <p>功能模块 × 角色权限对照(✓ 全权限 / △ 部分 / — 无权限)</p>
          </div>
        </div>
        <div className="panel-body">
          <div className="set-table-wrap">
            <table className="set-matrix">
              <thead>
                <tr>
                  <th>功能模块</th>
                  {ROLE_DESCRIPTIONS.map((r) => (
                    <th key={r.key}>
                      <span
                        className="set-role-dot"
                        style={{ background: ROLE_COLOR[r.key] }}
                      />
                      {r.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {PERM_MATRIX.map((row) => (
                  <tr key={row.module}>
                    <td className="set-matrix-module">{row.module}</td>
                    {ROLE_DESCRIPTIONS.map((r) => {
                      const v = row.cells[r.key] ?? "—";
                      return (
                        <td key={r.key} className={`set-matrix-cell set-cell-${v}`}>
                          {v}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* 用户列表(本期后端无 /users 接口,显式说明) */}
      <div className="panel">
        <div className="panel-header">
          <div>
            <h3>用户列表</h3>
            <p>平台内所有账号(超管 / 客户 / 普通用户 / 客户只读)</p>
          </div>
        </div>
        <div className="panel-body">
          <Empty
            image={<UserSwitchOutlined style={{ fontSize: 48, color: "var(--text-tertiary)" }} />}
            imageStyle={{ height: 64 }}
            description={
              <div className="set-empty-desc">
                <h4>用户列表 API 待提供</h4>
                <p>后端本期未提供 /users 列表接口,下个版本将开放用户与角色管理。</p>
              </div>
            }
          >
            <Button
              type="primary"
              icon={<TeamOutlined />}
              onClick={() => message.info("邀请用户功能将在下个版本上线")}
            >
              邀请用户
            </Button>
          </Empty>
        </div>
      </div>

      {/* 租户管理 —— 复用 SettingsPane 顶层 fetch 的 customers */}
      <TenantPanel customers={customers} />
    </div>
  );
}

function TenantPanel({ customers }: { customers: Customer[] }) {
  const [projects, setProjects] = useState<ProjectOut[]>([]);
  useEffect(() => {
    listProjects({ page: 1, size: 200 })
      .then((d) => setProjects(d.items as ProjectOut[]))
      .catch(() => setProjects([]));
  }, []);

  const projectCountByCustomer = useMemo(() => {
    // 项目没显式 customer_id 字段;/projects 不返回 customer 维度,
    // 本期先全部按 0 占位,留接口供后端补字段时替换;UI 仍可看租户基础信息。
    void projects;
    return new Map<number, number>();
  }, [projects]);

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h3>租户管理</h3>
          <p>平台内所有客户(租户)账号;后端无创建 endpoint,「新建租户」占位</p>
        </div>
        <Button
          icon={<ApartmentOutlined />}
          onClick={() => message.info("新建租户功能将在下个版本上线")}
        >
          新建租户
        </Button>
      </div>
      <div className="panel-body">
        {customers.length === 0 ? (
          <Empty description="暂无租户" />
        ) : (
          <div className="set-table-wrap">
            <table className="set-matrix">
              <thead>
                <tr>
                  <th>租户</th>
                  <th>联系人</th>
                  <th>项目数</th>
                  <th>状态</th>
                  <th>备注</th>
                </tr>
              </thead>
              <tbody>
                {customers.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <strong>{c.name}</strong>
                      <span style={{ marginLeft: 6, color: "var(--text-tertiary)", fontSize: 11 }}>
                        #{c.id} · {c.code}
                      </span>
                    </td>
                    <td>{c.contact ?? "—"}</td>
                    <td>{projectCountByCustomer.get(c.id) ?? 0}</td>
                    <td>
                      <Tag color={c.status === "active" ? "green" : "default"}>
                        {c.status === "active" ? "启用" : "禁用"}
                      </Tag>
                    </td>
                    <td>
                      <span style={{ color: "var(--text-tertiary)", fontSize: 12 }}>
                        创建于 {c.created_at.slice(0, 10)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

const SETTINGS_CSS = `
.set-root { display: flex; flex-direction: column; gap: 12px; padding: 12px 0; }
.set-content { padding: 4px 0; }
.set-stack { display: flex; flex-direction: column; gap: 16px; }

/* sub-tab —— 复制自 OverviewTab 的 .secondary-tabs / .secondary-tab,
   限定在 .set-root 作用域内避免污染其它页面(OverviewTab 原样式只在
   该组件 mount 时挂载,SettingsPane 没复用上)。 */
.set-root .secondary-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  border-bottom: 1px solid var(--border-light, #f0f0f0);
  padding: 0 4px;
}
.set-root .secondary-tab {
  padding: 10px 16px;
  font-size: 14px;
  color: var(--text-secondary, #4f4f4f);
  cursor: pointer;
  border-bottom: 2px solid transparent;
  margin-bottom: -1px;
  user-select: none;
}
.set-root .secondary-tab:hover { color: var(--brand-blue, #1a55e8); }
.set-root .secondary-tab.active {
  color: var(--brand-blue, #1a55e8);
  border-bottom-color: var(--brand-blue, #1a55e8);
  font-weight: 500;
}

.set-root .panel {
  background: #fff;
  border: 1px solid var(--border-light, #f0f0f0);
  border-radius: 8px;
}
.set-root .panel-header {
  padding: 14px 20px 12px;
  border-bottom: 1px solid var(--border-light, #f0f0f0);
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}
.set-root .panel-header h3 { margin: 0 0 4px; font-size: 15px; font-weight: 600; }
.set-root .panel-header p { margin: 0; font-size: 12px; color: var(--text-tertiary); }
.set-root .panel-body { padding: 16px 20px; }

/* 个人信息 profile */
.set-profile { display: flex; align-items: center; gap: 16px; padding-bottom: 16px; border-bottom: 1px solid var(--border-light, #f0f0f0); margin-bottom: 16px; }
.set-profile-main { display: flex; flex-direction: column; gap: 4px; }
.set-name { font-size: 16px; font-weight: 600; color: var(--text-primary); }
.set-sub { font-size: 12px; color: var(--text-tertiary); display: flex; align-items: center; flex-wrap: wrap; }

/* 表单 */
.set-form { display: flex; flex-direction: column; gap: 14px; }
.set-form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
@media (max-width: 768px) { .set-form-row { grid-template-columns: 1fr; } }
.set-form-group { display: flex; flex-direction: column; gap: 6px; }
.set-form-group label { font-size: 12px; color: var(--text-tertiary); }
/* antd Form.Item 在 set-form-group 里走 column 布局,清掉默认 margin */
.set-form .ant-form-item { margin-bottom: 0; }
.set-form-actions { display: flex; gap: 8px; padding-top: 4px; }

/* 通知设置 */
.set-notice-list { display: flex; flex-direction: column; }
.set-notice-item {
  display: flex; align-items: center; gap: 16px; padding: 12px 0;
  border-bottom: 1px dashed var(--border-light, #f0f0f0);
  cursor: pointer;
}
.set-notice-item:last-child { border-bottom: 0; }
.set-notice-main { flex: 1; min-width: 0; }
.set-notice-title { font-size: 14px; font-weight: 500; color: var(--text-primary); }
.set-notice-desc { font-size: 12px; color: var(--text-tertiary); margin-top: 2px; }

/* 角色说明卡 */
.set-role-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
.set-role-card {
  position: relative;
  background: var(--bg-page, #fafafa);
  border: 1px solid var(--border-light, #f0f0f0);
  border-radius: 8px;
  padding: 14px 16px 14px 20px;
  overflow: hidden;
}
.set-role-stripe {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  width: 4px;
}
.set-role-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }
.set-role-desc { font-size: 12px; color: var(--text-secondary); margin-top: 6px; line-height: 1.5; }
.set-role-key { font-size: 11px; color: var(--text-tertiary); margin-top: 6px; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

/* 权限矩阵 / 租户管理 表格 */
.set-table-wrap { overflow-x: auto; }
.set-matrix { width: 100%; border-collapse: collapse; font-size: 13px; }
.set-matrix th, .set-matrix td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border-light, #f0f0f0);
  text-align: center;
}
.set-matrix th { color: var(--text-secondary); font-weight: 500; background: var(--bg-page, #fafafa); white-space: nowrap; }
.set-matrix th:first-child, .set-matrix td:first-child { text-align: left; }
.set-matrix-module { font-weight: 500; color: var(--text-primary); }
.set-matrix-cell { font-size: 14px; }
.set-cell-✓ { color: #3d9070; font-weight: 600; }
.set-cell-△ { color: #c9803a; font-weight: 600; }
.set-cell-— { color: #bfbfbf; }
.set-role-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }

/* empty desc */
.set-empty-desc h4 { margin: 8px 0 4px; font-size: 14px; color: var(--text-primary); }
.set-empty-desc p { margin: 0 auto; font-size: 12px; color: var(--text-secondary); max-width: 360px; line-height: 1.6; }
`;
