import { Button, Col, Row, Spin, message } from "antd";
import { ReloadOutlined } from "@ant-design/icons";
import dayjs from "dayjs";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getDashboard, type DashboardOut } from "../../api/dashboard";
import "./Dashboard.css";

const STATUS_LABEL: Record<string, { text: string; cls: string; dot: string }> = {
  success: { text: "成功", cls: "stamp-success", dot: "" },
  failed: { text: "失败", cls: "stamp-danger", dot: "failed" },
  partial: { text: "部分完成", cls: "stamp-warning", dot: "partial" },
  skipped: { text: "跳过", cls: "stamp-mute", dot: "skipped" },
  running: { text: "运行中", cls: "stamp-orange", dot: "running" },
  queued: { text: "排队中", cls: "stamp-info", dot: "queued" },
};

const STATE_ROWS: { key: string; label: string; cls: string }[] = [
  { key: "success", label: "成功", cls: "success" },
  { key: "partial", label: "部分", cls: "partial" },
  { key: "failed", label: "失败", cls: "failed" },
  { key: "running", label: "运行中", cls: "running" },
  { key: "skipped", label: "跳过", cls: "skipped" },
];

const num = (n: number) => n.toLocaleString("en-US");
const pad2 = (n: number) => n.toString().padStart(2, "0");
const formatMMSS = (sec: number | null) => {
  if (sec == null) return "";
  const mm = Math.floor(sec / 60);
  const ss = sec % 60;
  return `${pad2(mm)}:${pad2(ss)}`;
};
const formatRelative = (iso: string) => {
  const triggered = dayjs(iso);
  const diffMs = Date.now() - triggered.valueOf();
  const diffMin = Math.round(diffMs / 60000);
  if (diffMin < 1) return "刚刚";
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH} 小时前`;
  const diffD = Math.round(diffH / 24);
  return `${diffD} 天前`;
};
const formatNext = (iso: string) => {
  const d = dayjs(iso);
  const now = dayjs();
  if (d.isSame(now, "day")) return `今天 ${d.format("HH:mm")}`;
  if (d.isSame(now.add(1, "day"), "day")) return `明天 ${d.format("HH:mm")}`;
  return d.format("MM-DD HH:mm");
};

function StatusStamp({ status }: { status: string }) {
  const cfg = STATUS_LABEL[status] ?? { text: status, cls: "stamp-mute", dot: "" };
  return <span className={`stamp ${cfg.cls}`}>{cfg.text}</span>;
}

function KpiCard({
  label,
  value,
  subtitle,
  tone,
}: {
  label: string;
  value: number;
  subtitle: React.ReactNode;
  tone: "blue" | "green" | "red" | "orange";
}) {
  return (
    <div className={`kpi kpi-${tone}`}>
      <div className="label">{label}</div>
      <div className="num">{num(value)}</div>
      <div className="meta">{subtitle}</div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const [data, setData] = useState<DashboardOut | null>(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const d = await getDashboard();
      setData(d);
    } catch (err) {
      message.error((err as Error).message || "加载失败");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  if (!data && loading) {
    return (
      <div style={{ padding: 80, textAlign: "center" }}>
        <Spin />
      </div>
    );
  }

  if (!data) {
    return <div className="empty-block">暂无数据</div>;
  }

  const successPct =
    data.today_runs > 0
      ? ((data.today_success / data.today_runs) * 100).toFixed(1)
      : "0.0";
  const failedPct =
    data.today_runs > 0
      ? ((data.today_failed / data.today_runs) * 100).toFixed(1)
      : "0.0";

  return (
    <div className="dashboard-page">
      <div className="page-title">
        <div>
          <h1>工作台</h1>
          <div className="desc">实时监控调度运行状况、查看今日任务概况</div>
        </div>
        <Button
          icon={<ReloadOutlined />}
          onClick={load}
          loading={loading}
        >
          刷新
        </Button>
      </div>

      {/* KPI row */}
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} md={6}>
          <KpiCard
            label="今日执行次数"
            value={data.today_runs}
            subtitle={<span>实时统计</span>}
            tone="blue"
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <KpiCard
            label="今日成功"
            value={data.today_success}
            subtitle={
              <>
                <span className="up">{successPct}%</span>
                <span>成功率</span>
              </>
            }
            tone="green"
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <KpiCard
            label="今日失败"
            value={data.today_failed}
            subtitle={
              <>
                <span className="down">{failedPct}%</span>
                <span>失败率</span>
              </>
            }
            tone="red"
          />
        </Col>
        <Col xs={24} sm={12} md={6}>
          <KpiCard
            label="启用项目数"
            value={data.enabled_projects}
            subtitle={<span>当前活跃调度</span>}
            tone="orange"
          />
        </Col>
      </Row>

      {/* Two-column row: timeline + distribution */}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={16}>
          <div className="card">
            <div className="card-header">
              <div>
                <h3>最近执行</h3>
                <div className="sub">跨所有项目的最新 10 条执行记录</div>
              </div>
            </div>
            <div className="timeline">
              {data.recent_runs.length === 0 ? (
                <div className="empty-block">暂无执行记录</div>
              ) : (
                data.recent_runs.map((r) => {
                  const cfg = STATUS_LABEL[r.status] ?? {
                    text: r.status,
                    cls: "stamp-mute",
                    dot: "",
                  };
                  const platforms = r.platforms.join(" · ");
                  const platformPrefix = platforms ? `${platforms} · ` : "";
                  const detail =
                    r.status === "success"
                      ? `${platformPrefix}共 ${r.prompt_count} 个问题全部完成 · 耗时 ${formatMMSS(r.duration_seconds)}`
                      : r.status === "failed"
                        ? `执行失败 · ${r.duration_seconds != null ? `耗时 ${formatMMSS(r.duration_seconds)}` : "未完成"}`
                        : r.status === "skipped"
                          ? "5 分钟内已执行过相同时间槽,跳过本次"
                          : r.status === "running"
                            ? `${platformPrefix}正在执行中`
                            : r.status === "queued"
                              ? "等待执行"
                              : `耗时 ${formatMMSS(r.duration_seconds)}`;
                  return (
                    <div className="timeline-item" key={r.id}>
                      <div className={`timeline-dot ${cfg.dot}`} />
                      <div className="timeline-content">
                        <div className="top">
                          <span
                            className="name"
                            onClick={() =>
                              navigate(`/admin/projects/${r.project_id}`)
                            }
                          >
                            {r.project_name}
                          </span>
                          <StatusStamp status={r.status} />
                          <span className="time">
                            {formatRelative(r.triggered_at)}
                          </span>
                        </div>
                        <div className="bot">{detail}</div>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </Col>

        <Col xs={24} md={8}>
          <div className="card">
            <div className="card-header">
              <div>
                <h3>今日执行状态分布</h3>
                <div className="sub">基于今日全部任务</div>
              </div>
            </div>
            <div className="dist-list">
              {(() => {
                const dist = data.status_distribution;
                const total = data.today_runs || 1;
                // Map the 5 UI rows to the 5 backend statuses. The mockup
                // labels "部分" (partial) but the v2 run schema has no
                // partial status; we map it to queued (also a non-terminal
                // bucket) so the row still appears.
                const getCount = (key: string) => {
                  if (key === "success") return dist.success;
                  if (key === "failed") return dist.failed;
                  if (key === "running") return dist.running;
                  if (key === "skipped") return dist.skipped;
                  if (key === "partial") return dist.queued;
                  return 0;
                };
                return STATE_ROWS.map((row) => {
                  const count = getCount(row.key);
                  const pct = (count / total) * 100;
                  return (
                    <div className={`dist-row ${row.cls}`} key={row.key}>
                      <span>{row.label}</span>
                      <div className="dist-bar">
                        <span style={{ width: `${Math.min(100, pct)}%` }} />
                      </div>
                      <span className="pct">{count}</span>
                    </div>
                  );
                });
              })()}
            </div>
          </div>
        </Col>
      </Row>

      {/* Upcoming */}
      <div className="card">
        <div className="card-header">
          <div>
            <h3>即将执行</h3>
            <div className="sub">按调度计划自动执行的任务</div>
          </div>
        </div>
        <div className="upcoming-list">
          {data.upcoming.length === 0 ? (
            <div className="empty-block">暂无即将执行的任务</div>
          ) : (
            data.upcoming.map((u) => (
              <div className="upcoming-item" key={u.project_id}>
                <div className="when">{formatNext(u.next_run_at)}</div>
                <div
                  className="name"
                  style={{ cursor: "pointer" }}
                  onClick={() => navigate(`/admin/projects/${u.project_id}`)}
                >
                  {u.project_name}
                </div>
                <div className="customer">{u.customer_name}</div>
                <span className="tag">
                  {u.platforms.length > 0
                    ? u.platforms.join(" · ")
                    : "—"}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
