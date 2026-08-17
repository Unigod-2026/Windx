import { useEffect, useMemo, useState } from "react";
import { Dropdown, Input, message } from "antd";
import type { MenuProps } from "antd";
import { useNavigate } from "react-router-dom";
import { listProjects, type ProjectOut } from "../../api/projects";

interface Props {
  /** Optional — when absent, the trigger shows a "选择项目" placeholder. */
  currentId?: number;
  variant?: "header" | "inline";
}

/**
 * Dropdown that lets the analyst jump between projects without going
 * back to the list page. Loads the (full, paginated) project list on
 * demand; searches by name/code. Picking a project lands on its
 * overview tab so the analyst sees KPIs immediately.
 */
export default function ProjectSwitcher({ currentId, variant = "inline" }: Props) {
  const navigate = useNavigate();
  const [all, setAll] = useState<ProjectOut[]>([]);
  const [keyword, setKeyword] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        // First page is enough for the dropdown — projects typically
        // number in the tens, not thousands.
        const data = await listProjects({ page: 1, size: 200 });
        if (!cancelled) setAll(data.items);
      } catch (err) {
        message.error((err as Error).message || "项目列表加载失败");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const filtered = useMemo(() => {
    const k = keyword.trim().toLowerCase();
    if (!k) return all;
    return all.filter(
      (p) =>
        p.name.toLowerCase().includes(k) ||
        p.code.toLowerCase().includes(k),
    );
  }, [all, keyword]);

  const goTo = (id: number) => navigate(`/admin/projects/${id}?tab=overview`);

  const menu: MenuProps = {
    items: filtered.map((p) => ({
      key: String(p.id),
      label: (
        <div style={{ minWidth: 220, padding: "2px 0" }}>
          <div style={{ fontWeight: 500 }}>{p.name}</div>
          <div style={{ fontSize: 12, color: "var(--text-tertiary)" }}>
            {p.code}
            {p.status === "disabled" && (
              <span style={{ marginLeft: 8, color: "var(--text-quaternary)" }}>
                已停用
              </span>
            )}
          </div>
        </div>
      ),
    })),
    onClick: ({ key }) => goTo(Number(key)),
  };

  const current = currentId !== undefined ? all.find((p) => p.id === currentId) : undefined;
  const triggerLabel = current?.name ?? "选择项目";

  return (
    <Dropdown
      menu={menu}
      trigger={["click"]}
      placement="bottomRight"
      dropdownRender={() => (
        <div
          style={{
            background: "#fff",
            borderRadius: 8,
            boxShadow: "0 6px 16px rgba(0,0,0,0.12)",
            padding: 4,
            maxHeight: 420,
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
        >
          <div style={{ padding: "4px 8px" }}>
            <Input.Search
              placeholder="搜索项目名 / 编号"
              allowClear
              autoFocus
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
            />
          </div>
          <div style={{ overflowY: "auto", maxHeight: 360 }}>
            {filtered.length === 0 ? (
              <div
                style={{
                  padding: "24px 12px",
                  color: "var(--text-tertiary)",
                  textAlign: "center",
                  fontSize: 13,
                }}
              >
                无匹配项目
              </div>
            ) : (
              filtered.map((p) => (
                <div
                  key={p.id}
                  onClick={() => goTo(p.id)}
                  style={{
                    padding: "8px 12px",
                    cursor: "pointer",
                    borderRadius: 4,
                    background:
                      p.id === currentId ? "var(--brand-blue-bg, #eff6ff)" : undefined,
                  }}
                  onMouseEnter={(e) => {
                    if (p.id !== currentId) {
                      e.currentTarget.style.background = "rgba(0,0,0,0.04)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (p.id !== currentId) {
                      e.currentTarget.style.background = "";
                    }
                  }}
                >
                  <div style={{ fontWeight: 500, color: "var(--text-primary)" }}>
                    {p.name}
                  </div>
                  <div style={{ fontSize: 12, color: "var(--text-tertiary)", marginTop: 2 }}>
                    {p.code}
                    {p.status === "disabled" && (
                      <span style={{ marginLeft: 8, color: "var(--text-quaternary)" }}>
                        · 已停用
                      </span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    >
      <button
        type="button"
        className={`project-switcher-trigger${variant === "header" ? " variant-header" : ""}`}
      >
        <span className="psw-label">项目</span>
        <strong className="psw-name">{triggerLabel}</strong>
        <span className="psw-arrow">▾</span>
      </button>
    </Dropdown>
  );
}
