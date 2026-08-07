# 任务调度管理界面 — 设计文档

- 日期: 2026-08-07
- 状态: 已与用户对齐,待用户复审
- 范围: windx 全栈系统,本 spec 仅讨论**新增功能**;现有「接入模力指数监控 API」以 [api调用prompt.md](../../../api调用prompt.md) 与 [docs/api/](../../api/) 为准

---

## Context

### 问题
windx 系统接入「模力指数监控 API」后,每次提交任务会触发多个子任务,完成时间通常 **5–30 分钟**。当前无任何定时机制,管理员只能通过手工方式反复提交,既容易遗漏也无法形成例行监控。

### 目标
为**超级管理员**提供「任务调度管理界面」,让管理员能在页面上:
1. 按客户/项目维度组织监控任务;
2. 设置每天 1–2 个时间点定时触发监控任务;
3. 查看调度执行历史,手动触发一次,启停调度;
4. 在项目下查看该项目的所有监控任务。

### 非目标(本期不做)
- **客户管理员(customer_admin)的结果展示界面**:在另一个 spec 中设计,本次仅预留权限模型与 API 数据隔离。
- **数据二次加工**:本次不涉及 answerContent 编辑、模板复用、AI 报告生成等,后续单独 spec。
- **告警与通知**(邮件/IM):失败仅写日志,不推送。
- **跨项目批量调度**:一个调度仅对应一个项目。
- **调度时间表的高级编辑**(cron 表达式):仅支持每日 1–2 个固定时间点。

---

## 决策摘要

| 议题 | 决定 |
|------|------|
| 后端技术栈 | **Python + FastAPI**(沿用) |
| 前端技术栈 | **React + Ant Design** |
| 调度语义 | **执行时间调度**(cron),非并发队列 |
| 使用角色 | **仅超级管理员**;客户管理员本期无 UI |
| 频率粒度 | 每调度 1–2 个时间点,默认 9:00 可改 |
| 多租户模型 | 客户/项目/竞品均为独立实体,竞品为被动收集不入参 |
| 入参映射 | prompts ← 项目问题;keywords ← 项目关键词;platforms ← 项目平台;callbackUrl ← MOLIZHISHU_CALLBACK_URL |
| 调度与项目 | 调度必须隶属于项目,创建时可用项目配置做默认值,可覆盖 |
| 调度引擎 | **APScheduler AsyncIOScheduler**,进程内 |
| 手动触发 | 需要 |
| 启用/停用 | 需要 |
| logo 存储 | 本地文件系统,DB 存相对路径 |
| 管理菜单组织 | prompts/keywords/platforms **嵌入项目详情页 tab**,不独立菜单 |

---

## §1 数据模型

### 新增表

#### `geo_customers`(客户)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| name | varchar(128) | 客户名 |
| code | varchar(64) UNIQUE | 客户编码 |
| logo_path | varchar(255) NULL | 相对路径,如 `logos/3.png` |
| contact | varchar(128) NULL | 联系人 |
| status | enum('active','disabled') | |
| created_at | datetime | Asia/Shanghai |
| updated_at | datetime | |

#### `geo_projects`(项目,**含调度字段,1:1 内嵌**)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| customer_id | int FK→geo_customers | |
| name | varchar(128) | |
| code | varchar(64) | 同客户内唯一 |
| status | enum('active','disabled') | 项目级启用状态 |
| description | text NULL | 项目描述 |
| **schedule_enabled** | bool DEFAULT FALSE | 调度是否启用 |
| **slot1_hour** | tinyint NULL | 第 1 个时间槽 - 小时(0-23) |
| **slot1_minute** | tinyint NULL | 第 1 个时间槽 - 分钟(0-59) |
| **slot2_hour** | tinyint NULL | 第 2 个时间槽 - 小时(NULL 表示只有 1 个槽) |
| **slot2_minute** | tinyint NULL | 第 2 个时间槽 - 分钟 |
| created_at / updated_at | datetime | |

唯一索引:`(customer_id, code)`

> **设计决定**:调度与项目 1:1,slots 内嵌进 `geo_projects`,无需单独 `geo_schedules` / `geo_schedule_slots` 表,前端也不暴露独立的"调度"实体。

#### `geo_project_prompts`(项目内问题)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| project_id | int FK | |
| prompt | text | |
| sort | int | |

#### `geo_project_keywords`(项目关键词)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| project_id | int FK | |
| keyword | varchar(255) | |
| sort | int | |

#### `geo_project_platforms`(项目用大模型)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| project_id | int FK | |
| platform | varchar(32) | 枚举见 docs/api |
| mode | varchar(32) | 枚举 |
| screenshot | tinyint | 0/1/2 |
| sort | int | |

**不**单独建 platform 实体表;枚举由 docs/api/submit-task.md 定义。

#### `geo_competitors`(竞品,**被动收集**)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| task_id | int FK→geo_tasks | |
| subtask_id | int FK→geo_subtasks | |
| name | varchar(255) | |
| source | enum('answer_content','reference_list') | 抽取来源 |
| raw_json | json | 原始上下文 |
| created_at | datetime | |

不入参,由后台从 `answerContent` / `referenceList` 抽取;**调度本期不实现抽取逻辑**,仅建表,留 hook 给后续 spec。

#### `geo_schedule_runs`(每次执行记录,**按项目**)
| 字段 | 类型 | 说明 |
|------|------|------|
| id | int PK | |
| project_id | int FK→geo_projects | |
| slot_index | tinyint | 触发时对应的 slot(1 或 2;手动触发时为 0) |
| trigger_type | enum('cron','manual') | |
| triggered_at | datetime | |
| started_at | datetime NULL | |
| finished_at | datetime NULL | |
| status | enum('queued','running','success','failed','skipped') | |
| task_id | int NULL FK→geo_tasks | 提交成功才有 |
| error_message | text NULL | |
| cooldown_key | varchar(64) NULL UNIQUE | 5 分钟去重键:`project-{id}-slot-{idx}-{YYYYMMDDHH}{floor(minute/5)}`,如 `project-3-slot-1-20260807090`(9:00–9:04 同一窗口) |

> **说明**:不再有独立的 `geo_schedules` / `geo_schedule_slots` 表。schedule 信息已内嵌到 `geo_projects`。

### `geo_admin_users` 扩展

| 新字段 | 类型 | 说明 |
|------|------|------|
| role | enum('super_admin','customer_admin') | 默认 super_admin |
| customer_id | int NULL FK→geo_customers | customer_admin 必填;super_admin 为 NULL |

### `geo_tasks` 扩展

| 新字段 | 类型 | 说明 |
|------|------|------|
| customer_id | int NULL | 冗余 |
| project_id | int NULL FK→geo_projects | 项目触发的任务必填 |
| schedule_run_id | int NULL FK→geo_schedule_runs | 调度/手动触发的任务必填 |

新增索引:`(customer_id, created_at)`、`(project_id, created_at)`

### 现有表
- `geo_subtasks` / `geo_callback_events` / `geo_compensation_events` 不变。
- `geo_tasks` 上面的扩展是**向后兼容**的(NULLable)。

---

## §2 API 接口

所有 `/api/customers*` 与 `/api/projects*` 的写接口仅 `super_admin`;客户管理员只能 `GET` 自己 `customer_id` 范围内的数据,越权返回 403。

### 客户管理
```
POST   /api/customers                创建
GET    /api/customers                列表(分页)
GET    /api/customers/{id}           详情
PUT    /api/customers/{id}           修改
POST   /api/customers/{id}/logo      multipart 上传 logo (PNG/JPG/WebP, ≤2MB)
DELETE /api/customers/{id}           软删除(有关联项目/调度时拒绝)
```

### 项目管理(合并调度)
```
POST   /api/customers/{id}/projects       创建项目(可含初始 schedule slots)
GET    /api/projects                       列表(可按 customer_id 过滤)
GET    /api/projects/{id}                  详情(含 prompts/keywords/platforms/schedule slots)
PUT    /api/projects/{id}                  修改基本信息
DELETE /api/projects/{id}                  软删除

# 项目配置 tab
PUT    /api/projects/{id}/prompts          整体替换 prompts 数组
PUT    /api/projects/{id}/keywords         整体替换 keywords 数组
PUT    /api/projects/{id}/platforms        整体替换 platforms 数组

# 项目调度(每个项目唯一 schedule,1–2 个 slots)
GET    /api/projects/{id}/schedule         读取 schedule(含 slots、enabled、上次 run 摘要)
PUT    /api/projects/{id}/schedule         修改 schedule(含 slots、enabled)
DELETE /api/projects/{id}/schedule         移除 schedule(回到未调度状态)
PUT    /api/projects/{id}/schedule/status  {status: enabled|disabled} 启用/停用
POST   /api/projects/{id}/schedule/trigger 手动触发,异步执行,返回 run_id

# 项目执行历史(原"调度执行历史")
GET    /api/projects/{id}/runs             项目执行记录(分页、status 过滤)
GET    /api/projects/runs/{run_id}         单次执行详情(含 task_id)

# 项目下监控任务列表
GET    /api/projects/{id}/tasks            项目下的监控任务列表(分页、status 过滤)
```

### 兼容现有
- `GET /api/tasks` 增加 customer_id 过滤参数;customer_admin 自动注入自己的 customer_id
- `GET /api/tasks/{taskId}` 返回中带 `customer_id` / `project_id` / `schedule_run_id`
- `POST /api/tasks` 允许可选 `project_id`;若提供则复用项目配置做默认值

---

## §3 调度器与执行流

### APScheduler 集成
- **引擎**:`AsyncIOScheduler`,时区 `Asia/Shanghai`
- **挂载**:FastAPI `lifespan` startup
- **JobStore**:`MemoryJobStore`(DB 为真相)
- **Job 通用配置**:`max_instances=1`,`coalesce=True`,`misfire_grace_time=600`

### 启动恢复
```
lifespan startup
  ├─ SELECT id, schedule_enabled, slot1_hour, slot1_minute, slot2_hour, slot2_minute
  │     FROM geo_projects
  │     WHERE schedule_enabled = TRUE AND status='active'
  └─ for each row, for each slot (1 or 2):
        scheduler.add_job(
          run_project,
          id=f"project-{id}-slot-{slot_index}",
          trigger="cron",
          hour=H, minute=M, timezone="Asia/Shanghai",
          replace_existing=True,
        )
```

### 单次执行流程
```
run_project(project_id, slot_index, trigger_type)
  1. 在 geo_schedule_runs INSERT 一条 queued 记录
     (cooldown_key = project-{id}-slot-{idx}-{YYYYMMDDHH}{floor(minute/5)},
      若 UNIQUE 冲突 → UPDATE status=skipped 并退出)
  2. UPDATE 该 run 的 status=running, started_at=now()
  3. 读 geo_projects + 项目 prompts/keywords/platforms + 配置
  4. 组装 SubmitTask 请求:
       prompts = 项目 prompts(geo_project_prompts)
       platforms = 项目 platforms(geo_project_platforms)
       monitorKeywords = ",".join(项目 keywords)
       callbackUrl = MOLIZHISHU_CALLBACK_URL(若配置)
       regionCode = 配置(若提供)
  5. 校验:prompts 不能为空(否则 failed,error="prompts 为空",**不调远端**)
  6. 调 MolizhishuClient.submit_task()
  7. INSERT/UPDATE geo_tasks (含 customer_id/project_id/schedule_run_id)
  8. INSERT geo_subtasks(初始摘要)
  9. UPDATE geo_schedule_runs SET task_id=?, status=success, finished_at=now()
  10. 失败:UPDATE run SET status=failed, error_message=?, finished_at=now()
```

### 手动触发
- `POST /api/projects/{id}/schedule/trigger`
- 同步返回 `run_id`(INSERT queued 记录后立即返回)
- 用 FastAPI `BackgroundTasks` 异步执行,具体逻辑与 cron 一致;slot_index=0 表示手动

### 容错
- 调度器抛错:`logger.exception`,不中断其他调度
- 项目被软删除时调度应停用:服务层校验 project.status='active' AND schedule_enabled=TRUE
- 调度器进程重启:lifespan 重新从 DB 加载
- 远端 5xx:不重试(留给后台轮询补偿机制;本调度只负责**首次提交**)
- 时区:所有 `now()` 使用 `datetime.now(ZoneInfo("Asia/Shanghai"))`

### 日志
每次执行一行:`[scheduler] source=schedule-run project_id=X slot=Y trigger=cron|manual duration=NNNms task_id=... status=success|failed`

---

## §4 UI 页面(侧边栏 3 项:工作台 / 项目管理 / 客户管理)

> **设计原则**:不再设独立的"调度管理"页面。调度作为项目的子能力,所有调度相关的 CRUD、启停、手动触发、执行历史都内嵌在项目详情页内。前端不需要暴露 "prompt" 概念,用户填的是"监控问题"(questions),系统自动当作 prompt 提交。

### §4.1 工作台 `/admin`(默认页)
- 4 个 KPI 卡(顶部一行):
  - 今日执行次数 / 今日成功(带成功率%) / 今日失败 / 启用项目数
- 最近执行时间线:跨项目聚合最新 N 条,显示项目名、状态印章、耗时摘要;点击进入项目详情
- 今日执行状态分布:堆叠条形图,5 个状态(成功 / 部分 / 失败 / 运行中 / 跳过)
- 即将执行列表:未来 24 小时内按调度计划自动执行的任务(项目名 + 时间 + 模型标签)

### §4.2 项目列表 `/admin/projects`
表格列(从左到右):
| 列 | 说明 |
|---|---|
| 项目 | 项目名(链接到详情) + 客户名 |
| 问题数 | 该项目下的监控问题数量 |
| 模型 | 已选平台标签(`deepseek` `doubao` `kimi` …),多于 3 个折叠为 `+N` |
| 调度 | 行内 toggle 开关(绿色=启用),点击立即切换(无需进入详情) |
| 下一执行 | `今天 14:00` / `明天 09:00` / `—`(停用时) |
| 最近一次 | 状态印章 + 时间 |
| 操作 | "立即执行" / "打开" / "…" |

顶部按钮:**+ 新建项目**(超管可指定客户;客户管理员只能为自己客户创建)
筛选:客户、状态(启用/停用)、模型

### §4.3 项目详情 `/admin/projects/{id}`(核心页)

#### 头部(项目级固定信息)
- 项目 logo + 项目名 + 客户名(可点击跳转)
- 元信息行:问题数 / 模型数 / 创建时间
- **调度时间槽展示**:每日执行时间(1-2 个 HH:MM,带时钟图标)+ `修改时间` 链接(弹出 modal)
- 右侧控件区:
  - 下次执行时间(蓝色高亮)
  - 调度开关(行内 toggle,切换立即生效)
  - `立即执行` 按钮(橙色主调)+ `查看结果` 按钮

#### 监控参数概览卡(头部下方,API 调用的关键参数)
三栏布局,顶部明确显示 `9 个问题 × 3 个模型 = 27 个子任务`:
1. **监控问题**(蓝色徽标 + 数字):展示第 1 个问题完整内容 + 后续 3 个问题摘要 + `+N 个问题` + `查看全部 →` 链接
2. **AI 模型**(橙色徽标 + 数字):以紧凑卡片列出已选模型(icon + 名称),`配置 →` 链接
3. **关键词**(紫色徽标 + 数字):以 tag 形式列出所有关键词,`配置 →` 链接
- 底部说明:"关键词用于结果高亮 + AI 回答中的品牌提及识别"

#### Tab 区(默认进入 `监控问题`)
Tab 顺序(从左到右):
1. **监控问题**(默认 active):问题列表 CRUD,每行含 `序号 / 问题文本 / 监控模型 / 最近一次回答字数 / 查看回答 →`
2. **AI 模型**:多选卡片网格(`deepseek` `doubao-pro` `kimi` `文心一言` `通义千问` `智谱 GLM` `混元` `Qwen-Max` `ERNIE-4.0`),顶部工具栏 `全选 / 反选 / 已选 N/M 个`,点击卡片切换选中状态
3. **关键词**:关键词列表 CRUD(每个含 `名称 / 出现次数 / 首次发现 / 最近一次`)
4. **竞品信息**:只读。顶部说明条:"竞品信息由系统在每次执行后从 AI 回答中自动提取,本页面仅展示,不可手动编辑"。表格列:竞品名称 / 出现次数 / 首次发现 / 最近一次 / 关联问题数
5. **执行历史**:时间线列表,每行:状态色点 + `第 N 次执行` + 状态印章 + 时间 + 触发方式 + 耗时 + 任务数统计 + `查看结果 / 查看详情` 操作
6. **基本信息**(最末):名称、客户、项目编号、创建时间、最近执行等;支持 `编辑基本信息` 按钮(打开 modal)

各 tab 独立 PUT 接口;切换 tab 不丢草稿;运行历史 tab 支持按状态 / 时间筛选。

### §4.4 客户管理 `/admin/customers`(仅 super_admin 可见)
- 表格:logo + 客户名 + 客户编号 + 联系人 + 邮箱 + 项目数 + 最近活跃 + 状态 + 操作
- 顶部按钮:**+ 新建客户**(弹窗含 logo 上传)
- logo 上传走 `POST /api/customers/{id}/logo`,multipart(PNG/JPG/WebP,≤2MB)
- logo 展示:`<img src="/static/logos/{customer_id}.png">`(FastAPI `StaticFiles` 挂 `/data/logos`)

### 鉴权与路由
- `/api/auth/me` 返回 `role` 与 `customer_id`(可空)
- 前端路由守卫:customer_admin 看不到 `/admin/customers`,但可看 `/admin`、`/admin/projects`(自动按 `customer_id` 过滤)
- 客户端:从 `/api/auth/me` 拿 `role`,首屏按角色隐藏菜单项(客户管理)

---

## §5 错误处理与测试

### 错误处理矩阵
| 场景 | 行为 |
|------|------|
| Token 失效 | run 标记 failed 并 alert 日志,后续 slot 继续 |
| 项目 prompts 为空 | run failed,error="prompts 为空",**不调远端** |
| 远端 `success=false` | run failed,保留 code/message |
| 远端 5xx / 网络超时 | run failed,记录 error_message |
| 同 slot 5 分钟内重复触发 | DB UNIQUE 冲突 → status=skipped |
| 调度器进程重启 | lifespan 重新从 DB 加载 enabled 调度 |
| Logo 超限(>2MB) | API 413 |
| Logo 类型非 png/jpg/webp | API 400 |
| 删除有调度/任务的客户/项目 | 拒绝,提示 |
| customer_admin 越权访问其他 customer_id | API 403,前端路由拦截 |

### 测试覆盖

**API 层(单测 + httpx AsyncClient)**
- 客户 CRUD(含 logo 上传、删除拒绝)
- 项目 CRUD + 4 tab 配置接口整体替换语义
- 调度 CRUD(1 slot / 2 slot 边界、覆盖项目配置)
- 手动触发 run(用 mocked `MolizhishuClient`)
- 权限隔离(customer_admin 越权 → 403)

**调度器层(集成 + freezegun)**
- 启用调度后启动 lifespan,验证 job 注册到 APScheduler
- cron 触发后,验证 SubmitTask 调用 + `geo_tasks` + `geo_schedule_runs` 写入
- 同 slot 5 分钟内重复触发 → UNIQUE 冲突 → skipped
- 项目 prompts 空 → run failed,远端**不**被调用
- 启停调度 → APScheduler job 添加/移除
- 重启 lifespan → 重新加载 enabled 调度

**回归**(沿用 [api调用prompt.md §16](../../api调用prompt.md))
- SubmitTask 保存 + Callback 幂等 + 手动同步等已有测试不重复

---

## 关键文件清单(实现时新建)

### 后端
- `alembic/versions/xxxx_add_schedule_management.py` — 数据库迁移(geo_customers / geo_projects 含调度字段 / geo_project_prompts / geo_project_keywords / geo_project_platforms / geo_competitors / geo_schedule_runs / geo_admin_users 扩展 / geo_tasks 扩展)
- `app/models/customer.py` / `project.py` / `prompt.py` / `keyword.py` / `platform.py` / `competitor.py` / `schedule_run.py` — SQLAlchemy 模型
- `app/services/molizhishu_client.py` — 沿用现有 SubmitTask 封装,无需改
- `app/services/scheduler.py` — APScheduler 集成 + `run_project` 逻辑
- `app/services/competitor_extractor.py` — 占位实现(本期不实现抽取,只暴露接口)
- `app/api/customers.py` / `projects.py` — 新增路由(含项目级 schedule/runs 子路由)
- `app/api/auth.py` — 修改 `/api/auth/me` 返回 role/customer_id
- `app/main.py` — lifespan startup 挂载 APScheduler;StaticFiles 挂 /data/logos
- `tests/test_scheduler.py` / `test_project_api.py` — 新增测试

### 前端(React + Ant Design)
- `frontend/` — Vite + React + TypeScript 工程根
- `frontend/src/api/` — axios 封装 + 客户/项目/项目调度/项目执行历史 API 客户端
- `frontend/src/pages/Dashboard/` — 工作台(KPI + 时间线 + 即将执行)
- `frontend/src/pages/Customers/` — 客户管理页面
- `frontend/src/pages/Projects/` — 项目列表 + 项目详情(头部调度控件 + 监控参数概览 + 6 个 tab)
- `frontend/src/components/` — 通用组件(LogoUpload、SlotTimePicker、ModelMultiSelect、MonitorParamsOverview)
- `frontend/src/auth/` — 登录、`AuthProvider`、按 role 路由守卫

---

## 开放问题

无。所有关键决策已与用户确认。

---

## 复审请求

Spec 已写入 `docs/superpowers/specs/2026-08-07-schedule-management-design.md`。

请复审后告知是否需要修改;通过后我会转入 **writing-plans** 技能,产出实现计划。