# windx 全栈系统

多租户 GEO 监控平台:对接「模力指数监控 API」,按项目配置问题 / 关键词 / 模型与每日 1-2 个执行时间点,自动定时向 AI 平台(deepseek / doubao / kimi 等)提交问题、收集回答,后台管理执行历史与竞品。

## 技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11 · FastAPI · SQLAlchemy 2 · Alembic · APScheduler 3 (AsyncIOScheduler) |
| 前端 | React 18 · Vite 5 · TypeScript 5 · Ant Design 5 · Axios · dayjs |
| 数据库 | MySQL 8 (Asia/Shanghai) |
| 反代 | nginx(把 `/api` 和 `/static` 反代到后端) |

## 仓库结构

```
windx/
├── backend/                # FastAPI 后端
│   ├── app/
│   │   ├── api/            # 路由(auth/customers/projects/tasks/dashboard)
│   │   ├── models/         # SQLAlchemy ORM(geo_* 表)
│   │   ├── schemas/        # Pydantic 响应模型
│   │   ├── services/       # 业务逻辑(scheduler、molizhishu 客户端、logo 存储)
│   │   ├── main.py         # FastAPI 入口 + lifespan(挂载 AsyncIOScheduler)
│   │   ├── config.py       # pydantic-settings 配置
│   │   └── deps.py         # JWT 解析与依赖注入
│   ├── alembic/            # 数据库迁移
│   ├── tests/              # pytest(142 用例)
│   ├── pyproject.toml
├── frontend/               # React + AntD 前端
│   ├── src/
│   │   ├── api/            # axios 封装 + 类型
│   │   ├── pages/          # Dashboard / Projects / Customers
│   │   ├── components/     # SlotTimePicker / ModelMultiSelect / AppLayout …
│   │   └── App.tsx         # 路由
│   ├── nginx.conf          # 反代 /api /static 到后端
│   ├── vite.config.ts
├── docs/
│   ├── api/                # 模力指数 API 规范(权威)
│   └── superpowers/
│       ├── specs/          # 设计文档
│       └── plans/          # 实施计划
├── api调用prompt.md         # 后端接入 prompt(原始规范)
├── 需求.md                  # 业务需求
├── CLAUDE.md               # 项目级 Claude 指令
└── README.md
```

## 快速启动

### 1. 准备 MySQL

任意一台 MySQL 8(本机、局域网或云 RDS),建一个空库即可:

```sql
CREATE DATABASE geo DEFAULT CHARACTER SET utf8mb4;
```

### 2. 配置环境变量

仓库根目录新建 `.env`(已 `.gitignore`,不会进 git):

```ini
APP_PORT=18083
TZ=Asia/Shanghai
DATABASE_URL=mysql+pymysql://USER:PASSWORD@HOST:3306/geo?charset=utf8mb4
JWT_SECRET=<openssl rand -hex 32 的输出>
MOLIZHISHU_TOKEN=<向模力指数申请的真实 Token>
```

`JWT_SECRET` 必须设置且足够随机;`MOLIZHISHU_TOKEN` 仅服务端使用,不写代码 / 日志 / 前端 / commit。

### 3. 装依赖、建表、起后端

```bash
cd backend
uv sync                              # 按 uv.lock 装依赖
uv run alembic upgrade head          # 建表(11 个 alembic revision)
uv run uvicorn app.main:app --host 0.0.0.0 --port 18083 --reload
```

服务端口:

| 服务 | 地址 |
|---|---|
| 后端 API | http://localhost:18083 |
| 后端 OpenAPI 文档 | http://localhost:18083/docs |
| MySQL | `localhost:3306`(账号 / 密码 / 库名按 `DATABASE_URL` 实际值) |

### 4. 初始化超级管理员

```bash
cd backend
uv run python - <<'PY'
from passlib.hash import bcrypt
from sqlalchemy import select
from app.db import SessionLocal
from app.models.customer import AdminUser
from app.models.enums import AdminRole, AdminStatus

with SessionLocal() as db:
    if db.scalar(select(AdminUser).where(AdminUser.username == "admin")):
        print("admin already exists")
    else:
        u = AdminUser(
            username="admin",
            password_hash=bcrypt.hash("changeme"),
            display_name="超级管理员",
            role=AdminRole.SUPER_ADMIN,
            status=AdminStatus.ACTIVE,
        )
        db.add(u)
        db.commit()
        print(f"created admin id={u.id}, password=changeme (请立即改密码)")
PY
```

> ⚠️ 生产环境必须修改默认密码。

### 5. 启动前端 + 登录

```bash
cd frontend
npm ci
npm run dev       # http://localhost:5173,vite proxy 已在 vite.config.ts 配好
```

浏览器打开 `http://localhost:5173/login`,用户名 `admin` 密码 `changeme` 登录。

## 本地开发

### 后端

```bash
cd backend
uv sync                                    # 按 uv.lock 装依赖
uv run alembic upgrade head                # 仅首次 / 升级时跑
uv run uvicorn app.main:app --reload --port 18083
```

`DATABASE_URL` / `JWT_SECRET` 走根目录 `.env`,同快速启动步骤 2。

### 前端

```bash
cd frontend
npm ci
npm run dev
```

### 测试

```bash
cd backend
uv run pytest -v
uv run ruff check .
```

## 接入模力指数监控 API(关键约定)

写入代码前必读 [`docs/api/`](docs/api/),这里只列最容易踩坑的:

1. **业务码 ≠ HTTP 码**:HTTP 200 也可能业务失败,必须用 `success` + `code` 判断(`docs/api/errors.md`)
2. **主任务终态**:`completed` / `partial_completed` / `failed` / `stopped`
3. **幂等**:回调用 `(taskId, payload_hash)` 去重,upsert 不抛错
4. **answerContent 不洗**:后端原样存储 Markdown / HTML
5. **时区**:容器与 MySQL 都按 Asia/Shanghai(`TZ=Asia/Shanghai` + `--default-time-zone=+08:00`)
6. **Token 安全**:`MOLIZHISHU_TOKEN` 仅服务端使用,不写代码 / 日志 / 前端 / commit

## API 接口清单(v2)

所有受保护接口需在 Header 带 `Authorization: Bearer <jwt>`。

### 鉴权

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → `{token, user}`,未知用户名与错密码同返 401,停用账号返 403 |
| GET | `/api/auth/me` | 返回当前用户 `{id, username, role, customer_id, status}` |

### 客户(超管)

| 方法 | 路径 |
|---|---|
| POST | `/api/customers` |
| GET | `/api/customers?page=&size=&status=` |
| GET | `/api/customers/{id}` |
| PUT | `/api/customers/{id}` |
| POST | `/api/customers/{id}/logo`(multipart `file`) |
| DELETE | `/api/customers/{id}`(软删除,要求无在管项目) |

### 项目

| 方法 | 路径 |
|---|---|
| POST | `/api/customers/{customer_id}/projects` |
| GET | `/api/projects?page=&size=&customer_id=&status=` |
| GET | `/api/projects/{id}` |
| PUT | `/api/projects/{id}` |
| DELETE | `/api/projects/{id}` |
| PUT | `/api/projects/{id}/prompts` |
| PUT | `/api/projects/{id}/keywords` |
| PUT | `/api/projects/{id}/platforms` |

### 调度(嵌入项目)

| 方法 | 路径 |
|---|---|
| GET | `/api/projects/{id}/schedule` |
| PUT | `/api/projects/{id}/schedule` |
| DELETE | `/api/projects/{id}/schedule` |
| PUT | `/api/projects/{id}/schedule/status`(`{status: "enabled"\|"disabled"}`) |
| POST | `/api/projects/{id}/schedule/trigger`(立即执行) |

### 执行记录

| 方法 | 路径 |
|---|---|
| GET | `/api/projects/{id}/runs?page=&size=` |
| GET | `/api/projects/runs/{run_id}` |
| GET | `/api/projects/{id}/tasks?page=&size=` |

### 任务列表(原 molizhishu 主任务)

| 方法 | 路径 |
|---|---|
| GET | `/api/tasks?page=&size=&status=&customer_id=&project_id=`(customer_admin 自动按自身 customer 过滤) |

### 工作台

| 方法 | 路径 |
|---|---|
| GET | `/api/dashboard` |

### 静态文件

| 路径 | 说明 |
|---|---|
| `/static/{logo_path}` | 客户 logo(由 `LOGO_STORAGE_DIR` 映射) |

## 调用矩阵:本地 vs 远端 vs Callback

| 行为 | 实现 |
|---|---|
| 只读本地 DB | `GET /api/tasks`、`GET /api/tasks/{taskId}`、`GET /api/projects/{id}/tasks`、`GET /api/projects/{id}/runs`、`GET /api/projects/runs/{run_id}` |
| 调用远端 SubmitTask | `POST /api/projects/{id}/schedule/trigger`(内部 → `MolizhishuClient.submit_task`) |
| 接收 Callback | `POST /webhooks/molizhishu`(沿用 [`docs/api/callback.md`](docs/api/callback.md) 规范) |
| 后台轮询 | 本期未实现;Callback 是唯一加速路径。完整轮询逻辑见 [`api调用prompt.md`](api调用prompt.md) §十 |

## 数据模型概览

| 表 | 说明 |
|---|---|
| `geo_customers` | 客户(多租户边界),含 logo_path |
| `geo_admin_users` | 管理员(super_admin / customer_admin) |
| `geo_projects` | 项目,隶属客户,**调度字段内嵌**:`schedule_enabled` + `slot1_hour/minute` + `slot2_hour/minute` |
| `geo_project_prompts` | 监控问题列表 |
| `geo_project_keywords` | 关键词列表 |
| `geo_project_platforms` | 模型 + 模式 + 是否截图 |
| `geo_competitors` | 竞品(本期被动写入,无自动抽取) |
| `geo_schedules` | 调度(已删除,v2 改为内嵌于 `geo_projects`) |
| `geo_schedule_slots` | 时间槽(已删除,v2 内嵌) |
| `geo_schedule_runs` | 每次执行记录,`cooldown_key` UNIQUE 防 5 分钟内重复 |
| `geo_tasks` | 模力指数主任务 |
| `geo_subtasks` | 子任务完整结果(含 `raw_result_json`) |
| `geo_callback_events` | 回调原始 payload + 幂等哈希 |

## 验收清单(对应 plan 附录 A.8 + 核心交付)

启动后请逐项确认:

- [ ] **侧边栏只有 3 项菜单**:工作台 / 项目管理 / 客户管理
- [ ] **`customer_admin` 看不到"客户管理"**
- [ ] **工作台 `/admin` 渲染 4 个区块**:KPI(今日执行 / 成功 / 失败 / 启用项目)+ 最近执行时间线 + 状态分布(成功 / 失败 / 跳过 / 运行中)+ 即将执行列表
- [ ] **项目列表行内 toggle** 可直接切换 schedule 开关(无需进入详情)
- [ ] **项目列表列**:调度开关 / 下一执行 / 最近一次 状态 + 时间
- [ ] **项目详情头部含**:调度开关 + 立即执行按钮 + 1-2 个时间槽 chip
- [ ] **项目详情头部下方含"监控参数概览"卡**
- [ ] **项目详情默认 Tab 为"监控问题"**
- [ ] **项目详情 6 个 Tab 顺序**:监控问题 / AI 模型 / 关键词 / 竞品信息 / 执行历史 / 基本信息
- [ ] **项目详情不出现 prompt 输入框**:用户填的是"监控问题",后端自动包装为 prompt
- [ ] **配色**:品牌蓝 `#1a55e8` + 品牌橙 `#ff6b1a` + PingFang SC

## 已知缺口 / 下一步

| 项 | 状态 | 备注 |
|---|---|---|
| `POST /api/auth/login` | ✅ 已实现 | bcrypt 校验 + JWT 签发,前端 Login 页可直接走真实流程 |
| `last_login_ip` 记录 | ❌ 未实现 | v2 模型未含此列,加列需新 alembic migration |
| 客户详情页(旗下项目列表) | ❌ 未实现 | 仅有客户列表 + 编辑 |
| 竞品信息抽取(项目详情 Tab5) | ❌ 占位 | 需 NLP / 规则抽取 |
| 后台轮询(同步最终一致性) | ❌ 未实现 | 当前只走 Callback |
| `/healthz` 健康检查端点 | ⚠️ 后端缺 | 仅 `/health`,建议加 `/healthz` 给上游探针 |
| 前端单元测试 | ❌ 未配 | 仅手动目检 |

## 文档索引

| 文档 | 用途 |
|---|---|
| [需求.md](需求.md) | 业务需求 + 技术选型 |
| [api调用prompt.md](api调用prompt.md) | 接入 prompt(原规范) |
| [docs/api/](docs/api/) | 模力指数 API 规范(权威) |
| [docs/superpowers/specs/2026-08-07-schedule-management-design.md](docs/superpowers/specs/2026-08-07-schedule-management-design.md) | 调度管理界面设计 |
| [docs/superpowers/plans/2026-08-07-schedule-management.md](docs/superpowers/plans/2026-08-07-schedule-management.md) | 17 任务实施计划 |
| [CLAUDE.md](CLAUDE.md) | 项目级 Claude 指令 |

## 开发约定

1. 提交前 `cd backend && uv run ruff check .` + `uv run pytest -q`
2. 提交粒度:每任务一次 commit,前缀 `feat:` / `fix:` / `chore:` / `docs:`
3. 数据库 schema 变更必须新增 alembic revision,**不要**直接 `Base.metadata.create_all`
4. 新 API 必须配 Pydantic 响应模型,不要直接返回 ORM 对象
5. 受保护接口必须经过 `get_current_user` 或 `require_super_admin`,不要裸用
6. TZ 一律 `Asia/Shanghai`,后端通过 `app.models.common.now_local()` 取得朴素 wall clock