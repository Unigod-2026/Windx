import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Badge,
  Button,
  Checkbox,
  Dropdown,
  Tooltip,
  message,
} from "antd";
import type { MenuProps } from "antd";
import {
  AppstoreOutlined,
  CalendarOutlined,
  CloudDownloadOutlined,
  DesktopOutlined,
  ExportOutlined,
  ImportOutlined,
  MessageOutlined,
  MobileOutlined,
  QuestionCircleOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { DatePicker } from "antd";
import dayjs from "dayjs";
import { getProject, type PromptOut } from "../api/projects";
import type {
  DeliveryMode,
  ThinkingMode,
  ToolbarDateRange,
} from "./ToolbarFilterContext";
import { WIZARD_MODELS } from "../pages/Projects/wizardConfig";
import { useToolbarFilter } from "./ToolbarFilterContext";

interface GlobalToolbarProps {
  /** 工具栏只在项目详情页(/admin/projects/:id)显示。父组件负责传 true。 */
  visible: boolean;
}

/**
 * 全局工具栏 —— 参照 docs/风球GEO监控平台UI/index.html 的
 * `id="global-toolbar"` 形态:9 个控件单行排开
 *   模型 / 问题 / 日期 / 模式 / 终端 / 导入 / 导出 / 下载 / 消息中心
 * 骨架版:筛选值本地 useState,导入/导出/下载/消息点击弹 toast 占位,
 * 真正的后端联动留给各 Tab 后续接 URL search params。
 *
 * 模型下拉:从当前项目的 ``geo_project_platforms`` 读出本项目配置的
 * ``modelCode`` 集合(每个 modelCode 一行,不论几个 mode / device),
 * 默认全选。后续叠加一个「可用模型白名单」(WIZARD_MODELS)兜底,
 * 防止后端返回了新代码但前端未跟进而漏展示。
 */
export default function GlobalToolbar({ visible }: GlobalToolbarProps) {
  const params = useParams<{ id?: string }>();
  const projectId = params.id ? Number(params.id) : null;
  const toolbar = useToolbarFilter();

  // 日期下拉 —— 预设(7/15/30/60)直接生效,自定义通过 RangePicker 选完后
  // 自动 apply。disabledDate 限制:不超过 30 天,不超今天。
  const [datePreset, setDatePreset] = useState<"7" | "15" | "30" | "60" | "custom">("15");
  // 自定义草稿 —— RangePicker 的当前值。仅在 datePreset === "custom" 时使用。
  const [customRange, setCustomRange] = useState<[dayjs.Dayjs, dayjs.Dayjs] | null>(null);
  const [dateMenuOpen, setDateMenuOpen] = useState(false);
  const [modes, setModes] = useState<{ fast: boolean; think: boolean }>({
    fast: true,
    think: true,
  });
  const [devices, setDevices] = useState<{ pc: boolean; mobile: boolean }>({
    pc: true,
    mobile: true,
  });

  // 模式分桶 → 「应用」参数。两侧都勾选等价于「不筛」(null);
  // 与 platforms / prompt_ids 的「全选即 null」语义一致,避免空字符串
  // 带来的歧义。
  const toggleMode = (k: "fast" | "think") => {
    setModes((m) => {
      const next = { ...m, [k]: !m[k] };
      const list: ThinkingMode[] = [];
      if (next.fast) list.push("fast");
      if (next.think) list.push("think");
      // 全选 → null(不筛);只选一个 → 单元素 list;全不选 → 空 list,
      // 后端 SQL IN () 会返回 0 行,UI 收到 0 是预期结果。
      toolbar.apply({
        selectedThinkingMode: list.length === 2 ? null : list,
      });
      return next;
    });
  };
  const toggleDevice = (k: "pc" | "mobile") => {
    setDevices((d) => {
      const next = { ...d, [k]: !d[k] };
      const list: DeliveryMode[] = [];
      if (next.pc) list.push("web");
      if (next.mobile) list.push("mobile");
      toolbar.apply({
        selectedDeliveryMode: list.length === 2 ? null : list,
      });
      return next;
    });
  };

  // 项目当前配置的 modelCode 集合 —— 控制下拉里展示哪些模型,
  // 以及默认勾选状态。空数组时不下拉(显示「加载中…」占位)。
  const [projectModels, setProjectModels] = useState<string[]>([]);
  // 已应用的模型选择 —— 写入 context 的最终值,按钮 label 据此渲染。
  const [appliedModels, setAppliedModels] = useState<Set<string>>(new Set());
  // 草稿选择 —— dropdown 内正在勾选的状态。打开时从 applied 复制,
  // 关闭时无论路径都不主动重置 —— 下次打开会自动从 applied 复制,
  // 天然实现「点应用才保存,其他路径关闭即丢弃」语义。
  const [stagedModels, setStagedModels] = useState<Set<string>>(new Set());
  const [modelsLoading, setModelsLoading] = useState(false);
  // 模型下拉是否打开。点 trigger / 外部 / 应用 三种路径都能关,
  // 点 dropdown 内的 checkbox 不触发关闭。
  const [modelMenuOpen, setModelMenuOpen] = useState(false);

  // 问题集 —— 项目配置的监控问题(prompts),下拉里 checkbox 多选。
  const [projectPrompts, setProjectPrompts] = useState<PromptOut[]>([]);
  const [appliedPrompts, setAppliedPrompts] = useState<Set<number>>(new Set());
  const [stagedPrompts, setStagedPrompts] = useState<Set<number>>(new Set());
  const [promptsLoading, setPromptsLoading] = useState(false);
  const [promptMenuOpen, setPromptMenuOpen] = useState(false);

  useEffect(() => {
    if (!visible || projectId === null) {
      setProjectModels([]);
      setAppliedModels(new Set());
      setStagedModels(new Set());
      setProjectPrompts([]);
      setAppliedPrompts(new Set());
      setStagedPrompts(new Set());
      return;
    }
    let cancelled = false;
    setModelsLoading(true);
    setPromptsLoading(true);
    getProject(projectId)
      .then((d) => {
        if (cancelled) return;
        // 用 ``platform_code``(API code,如 ``qianwen`` / ``qianwen_mobile``)
        // 去重 —— 同一逻辑模型(qianwen)的 web 行 + mobile 行是两个独立
        // 平台 code,工具栏要把它们分开显示。否则用户只看到「通义千问」
        // 一项,网页 / 移动数据混在一起没法按 (model, device) 维度筛选。
        const codes = Array.from(new Set(d.platforms.map((p) => p.platform_code ?? p.platform)));
        setProjectModels(codes);
        const allModels = new Set(codes);
        // 默认全选当前项目配的所有模型。
        setAppliedModels(allModels);
        setStagedModels(allModels);
        // prompts —— 监控问题集。archived 状态的不展示(已下线)。
        const activePrompts = d.prompts.filter((p) => p.status !== "archived");
        const promptIds = activePrompts.map((p) => p.id);
        const allPrompts = new Set(promptIds);
        setProjectPrompts(activePrompts);
        setAppliedPrompts(allPrompts);
        setStagedPrompts(allPrompts);
        // 「应用」状态也一并同步到 Context:首次进入时 selectedModels
        // 是 null (= 全部),这里把全选结果写回,保证首次 OverviewTab
        // 拉的也是「全平台」,而不是某种奇怪的 null 路径。
        toolbar.apply({ selectedModels: null, selectedPromptIds: null });
      })
      .catch(() => {
        if (!cancelled) {
          message.error("加载项目配置失败");
          setProjectModels([]);
          setAppliedModels(new Set());
          setStagedModels(new Set());
          setProjectPrompts([]);
          setAppliedPrompts(new Set());
          setStagedPrompts(new Set());
        }
      })
      .finally(() => {
        if (!cancelled) {
          setModelsLoading(false);
          setPromptsLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
    // toolbar.apply 在 useCallback 里,引用稳定;显式只依赖可见性 + id。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [visible, projectId]);

  // 配了 N 个 modelCode,白名单过滤后是真正展示在 UI 上的选项。
  // 白名单防止后端多出未支持的 code 时误显示。
  // 下拉项以 ``platform_code`` 为 key —— 同一逻辑模型(qianwen)的 web
  // 行 + mobile 行是两个独立项,UI 上挂「网页版 / 移动版」徽标区分。
  // ``known`` 复用 ``WIZARD_MODELS`` 取颜色 + 中文名;``unknown`` 兜底
  // 兜那些后端多出但前端未支持的 code,raw 显示。
  const modelOptions = useMemo(() => {
    const known: { code: string; name: string; color: string; delivery: "web" | "mobile" }[] = [];
    const unknown: string[] = [];
    const seen = new Set<string>();
    for (const code of projectModels) {
      if (seen.has(code)) continue;
      seen.add(code);
      const entry = WIZARD_MODELS.find(
        (m) => m.value === code || m.mobileCode === code,
      );
      if (entry) {
        known.push({
          code,
          name: entry.name,
          color: entry.color,
          delivery: code === entry.mobileCode ? "mobile" : "web",
        });
      } else {
        unknown.push(code);
      }
    }
    return { known, unknown };
  }, [projectModels]);

  if (!visible) return null;

  const toggleModel = (code: string) =>
    setStagedModels((s) => {
      const next = new Set(s);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  const allModelCodes = projectModels;
  const allSelected =
    allModelCodes.length > 0 && allModelCodes.every((c) => stagedModels.has(c));
  const partialSelected =
    !allSelected && allModelCodes.some((c) => stagedModels.has(c));

  // AntD Menu 的 items —— Header 是 group(纯展示),模型复选框是普通项,
  // 「应用」放在 group 里。MenuProps["items"] 类型与渲染均交给 AntD,
  // 我们只关心 onClick 不在 checkbox 项上触发 menu 源关闭。
  const dropdownMenuItems: MenuProps["items"] = [
    {
      key: "header",
      type: "group",
      label: (
        <div className="gt-model-menu-head" onClick={(e) => e.stopPropagation()}>
          <Checkbox
            checked={allSelected}
            indeterminate={partialSelected}
            onChange={(e) => {
              if (e.target.checked) {
                setStagedModels(new Set(allModelCodes));
              } else {
                setStagedModels(new Set());
              }
            }}
          >
            全选
          </Checkbox>
          <span className="gt-model-menu-count">
            {stagedModels.size}/{allModelCodes.length}
          </span>
        </div>
      ),
    },
    { type: "divider" },
    ...modelOptions.known.map((m) => ({
      key: m.code,
      // 让 label 区域点击不冒泡到 Menu 的 item click —— 避免触发 menu 源关闭
      // (checkbox 自带 onClick 会被 Menu 视为 menu click)
      label: (
        <div onClick={(e) => e.stopPropagation()}>
          <Checkbox
            checked={stagedModels.has(m.code)}
            onChange={() => toggleModel(m.code)}
          >
            <span
              className="gt-model-dot"
              style={{ background: m.color }}
              aria-hidden
            />
            {m.name}
            {/* 「网页版 / 移动版」徽标:让用户清楚这张 card 是 web 还是
                mobile 渠道,避免「勾了 qianwen 却忘了 mobile 也在跑」的
                认知偏差。颜色沿用工具栏已有 web=蓝 / mobile=橙 的语义。 */}
            <span className="gt-model-delivery" data-delivery={m.delivery}>
              {m.delivery === "mobile" ? "移动版" : "网页版"}
            </span>
          </Checkbox>
        </div>
      ),
    })),
    ...(modelOptions.unknown.length > 0
      ? [
          { type: "divider" as const },
          {
            key: "unknown",
            type: "group" as const,
            label: <span className="gt-model-menu-unknown">未识别 code</span>,
          },
          ...modelOptions.unknown.map((code) => ({
            key: `unknown-${code}`,
            label: (
              <div onClick={(e) => e.stopPropagation()}>
                <Checkbox
                  checked={stagedModels.has(code)}
                  onChange={() => toggleModel(code)}
                >
                  <code>{code}</code>
                </Checkbox>
              </div>
            ),
          })),
        ]
      : []),
    { type: "divider" },
    {
      key: "apply",
      type: "group",
      label: (
        <div className="gt-model-menu-foot" onClick={(e) => e.stopPropagation()}>
          <Button
            type="primary"
            size="small"
            block
            onClick={() => {
              // 「全部勾选」等价于「不筛选」(后端 null 路径),与
              // 不传 platforms 参数同口径,避免空字符串带来的歧义。
              const isFullSelection =
                stagedModels.size === allModelCodes.length &&
                allModelCodes.length > 0;
              setAppliedModels(new Set(stagedModels));
              toolbar.apply({
                selectedModels: isFullSelection ? null : Array.from(stagedModels),
              });
              message.success(
                isFullSelection
                  ? "已应用:全部模型"
                  : `已应用:已选 ${stagedModels.size} 个模型`,
              );
              // 关掉下拉,触发各 Tab 重拉(由 context version++ 驱动)。
              setModelMenuOpen(false);
            }}
          >
            应用
          </Button>
        </div>
      ),
    },
  ];

  const modelValueLabel = modelsLoading
    ? "加载中…"
    : projectModels.length === 0
      ? "未配置"
      : appliedModels.size === projectModels.length
        ? "全部"
        : appliedModels.size === 0
          ? "未选"
          : `已选 ${appliedModels.size}`;

  const exportItems: MenuProps["items"] = [
    { key: "config", label: "全局筛选配置", onClick: () => message.info("导出 CSV — 全局筛选配置（开发中）") },
    { key: "business", label: "业务数据", onClick: () => message.info("导出 CSV — 业务数据（开发中）") },
    { key: "all", label: "全部导出", onClick: () => message.info("导出 CSV — 全部（开发中）") },
  ];

  const applyDatePreset = (preset: "7" | "15" | "30" | "60") => {
    setDatePreset(preset);
    setCustomRange(null);
    toolbar.apply({
      selectedDateRange: { days: Number(preset) } satisfies ToolbarDateRange,
    });
    setDateMenuOpen(false);
  };

  const dateItems: MenuProps["items"] = [
    { key: "7", label: "近 7 天", onClick: () => applyDatePreset("7") },
    { key: "15", label: "近 15 天", onClick: () => applyDatePreset("15") },
    { key: "30", label: "近 30 天", onClick: () => applyDatePreset("30") },
    { key: "60", label: "近 2 个月", onClick: () => applyDatePreset("60") },
    { type: "divider" },
    {
      key: "custom",
      label: (
        <div onClick={(e) => e.stopPropagation()}>
          <div style={{ fontSize: 12, color: "#6b7280", marginBottom: 4 }}>
            自定义(不超过 1 个月)
          </div>
          <DatePicker.RangePicker
            size="small"
            value={customRange}
            allowClear={false}
            // disabledDate: 跨度超过 30 天或晚于今天时置灰。
            disabledDate={(cur) => {
              if (!cur) return false;
              if (cur > dayjs().endOf("day")) return true;
              const anchor = customRange?.[0] ?? customRange?.[1] ?? null;
              if (anchor && Math.abs(cur.diff(anchor, "day")) >= 30) return true;
              return false;
            }}
            onChange={(v) => {
              if (!v || !v[0] || !v[1]) {
                setCustomRange(v as [dayjs.Dayjs, dayjs.Dayjs] | null);
                return;
              }
              setCustomRange([v[0], v[1]]);
              setDatePreset("custom");
              toolbar.apply({
                selectedDateRange: {
                  start: v[0].format("YYYY-MM-DD"),
                  end: v[1].format("YYYY-MM-DD"),
                } satisfies ToolbarDateRange,
              });
              setDateMenuOpen(false);
            }}
          />
        </div>
      ),
    },
  ];

  // 问题下拉 —— 与模型同款多选 + 应用语义。prompt 文本超过 50 字省略,
  // tooltip 给出全文,避免下拉宽度被长问题撑爆。
  const truncatePrompt = (s: string) =>
    s.length > 50 ? s.slice(0, 50) + "…" : s;

  const allPromptIds = projectPrompts.map((p) => p.id);
  const promptAllSelected =
    allPromptIds.length > 0 &&
    allPromptIds.every((id) => stagedPrompts.has(id));
  const promptPartial =
    !promptAllSelected && allPromptIds.some((id) => stagedPrompts.has(id));

  const togglePrompt = (id: number) =>
    setStagedPrompts((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const promptDropdownItems: MenuProps["items"] = [
    {
      key: "header",
      type: "group",
      label: (
        <div
          className="gt-model-menu-head"
          onClick={(e) => e.stopPropagation()}
        >
          <Checkbox
            checked={promptAllSelected}
            indeterminate={promptPartial}
            onChange={(e) => {
              if (e.target.checked) {
                setStagedPrompts(new Set(allPromptIds));
              } else {
                setStagedPrompts(new Set());
              }
            }}
          >
            全选
          </Checkbox>
          <span className="gt-model-menu-count">
            {stagedPrompts.size}/{allPromptIds.length}
          </span>
        </div>
      ),
    },
    { type: "divider" },
    ...projectPrompts.map((p) => ({
      key: `prompt-${p.id}`,
      label: (
        <div onClick={(e) => e.stopPropagation()}>
          <Tooltip
            title={p.prompt.length > 50 ? p.prompt : ""}
            placement="left"
          >
            <Checkbox
              checked={stagedPrompts.has(p.id)}
              onChange={() => togglePrompt(p.id)}
            >
              <span className="gt-prompt-text">{truncatePrompt(p.prompt)}</span>
            </Checkbox>
          </Tooltip>
        </div>
      ),
    })),
    { type: "divider" },
    {
      key: "apply",
      type: "group",
      label: (
        <div
          className="gt-model-menu-foot"
          onClick={(e) => e.stopPropagation()}
        >
          <Button
            type="primary"
            size="small"
            block
            onClick={() => {
              const isFullSelection =
                stagedPrompts.size === allPromptIds.length &&
                allPromptIds.length > 0;
              setAppliedPrompts(new Set(stagedPrompts));
              toolbar.apply({
                selectedPromptIds: isFullSelection
                  ? null
                  : Array.from(stagedPrompts),
              });
              message.success(
                isFullSelection
                  ? "已应用:全部问题"
                  : `已应用:已选 ${stagedPrompts.size} 个问题`,
              );
              setPromptMenuOpen(false);
            }}
          >
            应用
          </Button>
        </div>
      ),
    },
  ];

  const promptValueLabel = promptsLoading
    ? "加载中…"
    : projectPrompts.length === 0
      ? "未配置"
      : appliedPrompts.size === projectPrompts.length
        ? "全部"
        : appliedPrompts.size === 0
          ? "未选"
          : `已选 ${appliedPrompts.size}`;

  return (
    <div className="gt">
      {/* 左侧 5 个筛选控件:模型 / 问题 / 日期 / 模式 / 终端 */}
      <div className="gt-filters">
        <Dropdown
          menu={{ items: dropdownMenuItems }}
          // controlled open —— 关键:忽略 menu 源的关闭事件(checkbox 项点击
          // 会触发 source: 'menu'),只接受 trigger / outside 源的关闭。
          // 「应用」按钮通过自身 onClick 主动 setModelMenuOpen(false) 关闭。
          // 每次打开时把 applied 复制到 staged 作为本轮编辑起点;
          // 关闭路径不主动重置 staged —— 下次打开会再次从 applied 复制,
          // 天然实现「外部关闭即丢弃 staged」语义。
          open={modelMenuOpen}
          onOpenChange={(next, info) => {
            if (next) setStagedModels(new Set(appliedModels));
            if (!next && info?.source === "menu") return; // 保留多选
            setModelMenuOpen(next);
          }}
          trigger={["click"]}
          disabled={projectModels.length === 0}
          overlayClassName="gt-model-dropdown"
          placement="bottomLeft"
        >
          <Button className="gt-btn" icon={<AppstoreOutlined />}>
            <span className="gt-btn-label">模型</span>
            <span className="gt-btn-value">{modelValueLabel}</span>
          </Button>
        </Dropdown>

        <Dropdown
          menu={{ items: promptDropdownItems }}
          open={promptMenuOpen}
          onOpenChange={(next, info) => {
            if (next) setStagedPrompts(new Set(appliedPrompts));
            if (!next && info?.source === "menu") return; // 保留多选
            setPromptMenuOpen(next);
          }}
          trigger={["click"]}
          disabled={projectPrompts.length === 0}
          overlayClassName="gt-model-dropdown gt-prompt-dropdown"
          placement="bottomLeft"
        >
          <Button className="gt-btn" icon={<QuestionCircleOutlined />}>
            <span className="gt-btn-label">问题</span>
            <span className="gt-btn-value">{promptValueLabel}</span>
          </Button>
        </Dropdown>

        <Dropdown
          menu={{ items: dateItems }}
          open={dateMenuOpen}
          onOpenChange={(next, info) => {
            // 「自定义」项内的 RangePicker 点击会冒泡 source:'menu',
            // 关闭下拉会让日历选不完。屏蔽 source:'menu',预设项点击已
            // 在 onClick 内主动 setDateMenuOpen(false) 关闭。
            if (!next && info?.source === "menu") return;
            setDateMenuOpen(next);
          }}
          trigger={["click"]}
          placement="bottomLeft"
          overlayClassName="gt-date-dropdown"
        >
          <Button className="gt-btn" icon={<CalendarOutlined />}>
            <span className="gt-btn-label">日期</span>
            <span className="gt-btn-value">
              {datePreset === "custom" && customRange
                ? `${customRange[0].format("MM-DD")} ~ ${customRange[1].format("MM-DD")}`
                : `近 ${datePreset} 天`}
            </span>
          </Button>
        </Dropdown>

        <div className="gt-seg">
          <span className="gt-seg-label">模式</span>
          <button
            type="button"
            className={`gt-seg-item${modes.fast ? " is-active" : ""}`}
            onClick={() => toggleMode("fast")}
            title="快速模式"
          >
            <ThunderboltOutlined /> 快速
          </button>
          <button
            type="button"
            className={`gt-seg-item${modes.think ? " is-active" : ""}`}
            onClick={() => toggleMode("think")}
            title="思考模式"
          >
            <span className="gt-seg-dot" /> 思考
          </button>
        </div>

        <div className="gt-seg">
          <span className="gt-seg-label">终端</span>
          <button
            type="button"
            className={`gt-seg-item${devices.pc ? " is-active" : ""}`}
            onClick={() => toggleDevice("pc")}
            title="PC 端"
          >
            <DesktopOutlined /> PC
          </button>
          <button
            type="button"
            className={`gt-seg-item${devices.mobile ? " is-active" : ""}`}
            onClick={() => toggleDevice("mobile")}
            title="移动端"
          >
            <MobileOutlined /> 移动端
          </button>
        </div>
      </div>

      <div className="gt-spacer" />

      {/* 右侧 4 个图标按钮:导入 / 导出 / 下载 / 消息中心 */}
      <div className="gt-actions">
        <Tooltip title="导入规则">
          <Button
            className="gt-icon-btn"
            icon={<ImportOutlined />}
            onClick={() => message.info("导入（开发中）")}
          >
            导入
          </Button>
        </Tooltip>

        <Dropdown menu={{ items: exportItems }} trigger={["click"]}>
          <Button className="gt-icon-btn" icon={<ExportOutlined />}>
            导出
          </Button>
        </Dropdown>

        <Tooltip title="下载管理">
          <Button
            className="gt-icon-btn"
            icon={<CloudDownloadOutlined />}
            onClick={() => message.info("下载管理（开发中）")}
          >
            下载
          </Button>
        </Tooltip>

        <Tooltip title="消息中心">
          <Badge count={3} size="small" offset={[-2, 4]}>
            <Button
              className="gt-icon-btn"
              icon={<MessageOutlined />}
              onClick={() => message.info("消息中心（开发中）")}
            >
              消息中心
            </Button>
          </Badge>
        </Tooltip>
      </div>
    </div>
  );
}
