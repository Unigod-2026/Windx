# 竞品分析页 — 移除「竞争优势矩阵」占位 panel

- 日期: 2026-08-19
- 状态: 已与用户确认,待实施
- 范围: 仅前端 `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx`

---

## Context

`CompetitorAnalysisTab` 当前展示 4 个 panel:

1. 竞品概览(全宽表格)
2. 提及趋势对比(全宽 SVG 折线)
3. 差异化标签云(半宽)
4. 竞争优势矩阵(半宽,**占位** — 文案是「客户关注点 × 品牌 — 关注点表待接入」+「竞争优势矩阵需要先配置「客户关注点」」)

第 4 个 panel 是为「客户关注点表」预留的占位,后端没有「关注点」相关接口,实际拿不到任何数据,目前永远显示一个 `ThunderboltFilled` 图标 + 占位文案。

`docs/更新版UI/index.html` 的新版 竞品分析 草图里,有一个 `input-hint-panel` 卡片 + 「编辑关注点」按钮。但用户当前不打算接入关注点表,因此两版设计里与「关注点」相关的 UI(占位 panel + 新版 hint card)都不需要出现在生产代码里。

## 目标

1. 从 `CompetitorAnalysisTab` 移除「竞争优势矩阵」panel,页面只剩 3 个可渲染 panel。
2. 剩余 panel 视觉对齐,不留大面积空白。
3. 不引入新的占位文案、不新增接口、不改动后端。

## 非目标

- 不改 `CompetitorsTab`(竞品管理 CRUD,本次不动)。
- 不在 `CompetitorAnalysisTab` 顶部加「新增竞品」按钮。
- 不引入「input-hint-panel」卡片(关注点功能未做,加了也是死链)。
- 不动 `getCompetitorAnalysis` API、不动 SQL、不动数据库。
- 不改路由 / Tab 切换 / 任何 props。

---

## 决策摘要

| 议题 | 决定 |
|---|---|
| 删除对象 | 「4. 竞争优势矩阵」panel 整块(JSX + 注释 + 占位文案) |
| 网格收口 | 「差异化标签云」从 `panel` 改为 `panel panel-wide`,与上面两个 panel-wide 对齐 |
| import 清理 | 删除 `ThunderboltFilled`(仅占位 panel 使用) |
| 样式清理 | `<style>` 块整体不动 — 里面所有 class 仍被剩余 3 个 panel 引用,本次不触动 |
| 验证 | 浏览器切到「竞品分析」tab,确认 3 个 panel 渲染、无 console error |

---

## 改动详情

### A. 删除项

文件: `frontend/src/pages/Projects/CompetitorAnalysisTab.tsx`

1. **删 import** (`@ant-design/icons` 那行):
   - `ThunderboltFilled`(只在占位 panel 用)

2. **删 JSX**(在「3. 差异化标签云」panel 之后,`</div>` 闭合 `cna-grid` 之前):

   ```jsx
   {/* 4. 竞争优势矩阵 — 关注点表未接入,占位 */}
   <div className="panel">
     <div className="panel-header">
       <h3>竞争优势矩阵</h3>
       <p>客户关注点 × 品牌 — 关注点表待接入</p>
     </div>
     <div className="panel-body">
       <div style={{ padding: "32px 24px", textAlign: "center", color: "var(--text-tertiary)", fontSize: 13 }}>
         <ThunderboltFilled style={{ fontSize: 24, color: "var(--brand-blue)", marginBottom: 8 }} />
         <div style={{ marginBottom: 6 }}>竞争优势矩阵需要先配置「客户关注点」</div>
         <div style={{ fontSize: 12 }}>关注点表接入后,这里会按 关注点 × 品牌 展示每品牌的优势率(命中 AI 回答中该关注点的比例)</div>
       </div>
     </div>
   </div>
   ```

### B. 修改项

将「3. 差异化标签云」的 `<div className="panel">` 改为 `<div className="panel panel-wide">`,使其与上方两个 panel-wide 一致,布局对齐、不留右侧空白。

### C. 保留项(不动)

- 顶部 `<div className="cna-root">` + `<div className="cna-grid">` 结构
- 1. 竞品概览 panel + `<table>` 渲染
- 2. 趋势对比图 panel + `Sparkline` / `TrendChart` SVG 组件
- 3. 差异化标签云 panel + tag-cloud 渲染
- `useState` / `useEffect` / 数据获取逻辑
- 顶部文件注释(只删一行 `{/* 4. 竞争优势矩阵 ... */}` 块注释即可)
- `<style>` 块整体保留(里面所有 class 仍然在被引用的 panel 中使用)
- `getCompetitorAnalysis` API / 后端逻辑

---

## 验证

1. **代码层面:**
   - `pnpm run lint` 通过(确认无未使用 import 警告)
   - `pnpm run typecheck` 通过
2. **运行层面:**
   - 启动 dev server,登录后进入任一项目 → 切到「竞品分析」tab
   - 确认:页面渲染 3 个 panel(竞品概览 / 趋势对比 / 差异化标签云),均为全宽或对齐
   - 确认:浏览器 console 无 error / warning
   - 确认:顶部「新增竞品」按钮不存在
   - 确认:页面无「竞争优势矩阵」「客户关注点」等文案

---

## 风险

- 低。纯 UI 删减,不涉及数据流、props、API、路由、权限。
- `<style>` 块保留的内联 CSS 不影响功能,但技术债略增。后续如要清理,可单独跑一次 style audit。

## 后续(可选,不在本次范围)

- 「客户关注点」功能如未来要落地,需要后端先有 focus_points / focus_point_brand_rate 表与对应接口,然后才能恢复「竞争优势矩阵」panel + 新版「编辑关注点」按钮。