# 调度管理(并入项目管理) Implementation Plan

> **修订说明(v2)**:经与用户二次评审,确定调度**不作为独立页面**而是**嵌入项目详情页**。具体变更:
> 1. 移除独立的 `geo_schedules` / `geo_schedule_slots` 表;调度字段内嵌 `geo_projects`
> 2. UI 侧边栏由多组菜单简化为 3 项:**工作台 / 项目管理 / 客户管理**
> 3. 项目详情页头部放调度控件(开关/立即执行/时间槽),Tab 区改为 6 个(监控问题/AI模型/关键词/竞品信息/执行历史/基本信息),默认进入"监控问题"
> 4. 项目详情头部下方新增"监控参数概览"卡(问题+模型+关键词三栏摘要)
> 5. Task 5 合并 Task 9 的调度 CRUD API(Task 9 删除)
> 6. Task 14 扩展为含 6 tab + 头部调度控件 + 监控参数概览(Task 15 删除并替换为新 Dashboard 任务)
>

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 windx 全栈系统增加任务调度管理界面(超级管理员视角),支持客户/项目多租户、按每日 1–2 个时间点自动提交监控任务、手动触发、启停切换、执行历史。

**Architecture:**
- 后端:FastAPI + SQLAlchemy + APScheduler(进程内 AsyncIOScheduler);新增 9 张表;lifespan startup 从 DB 加载 enabled 调度并注册到 APScheduler。
- 前端:React + Vite + TypeScript + Ant Design;axios 调后端;按 `role` 做路由守卫。
- 调度执行:读项目配置 → 组装 SubmitTask 请求 → 调 `MolizhishuClient.submit_task()` → 写 `geo_tasks` + `geo_subtasks` + `geo_schedule_runs`。

**Tech Stack:**
- 后端:Python 3.11+ / FastAPI / SQLAlchemy 2.x / Alembic / APScheduler 3.x / httpx / pymysql
- 前端:React 18 / Vite / TypeScript / Ant Design 5 / axios / React Router 6
- DB:MySQL 8(Asia/Shanghai)

**Spec:** [2026-08-07-schedule-management-design.md](../specs/2026-08-07-schedule-management-design.md)

---

## 文件结构

```
backend/
  alembic/
    versions/
      xxxx_add_schedule_management.py
  app/
    __init__.py
    main.py
    config.py
    db.py
    deps.py
    auth.py
    models/
      __init__.py
      customer.py
      project.py
      schedule.py
      task.py                # 复用现有
    schemas/
      __init__.py
      customer.py
      project.py
      schedule.py
      schedule_run.py
    api/
      __init__.py
      customers.py
      projects.py
      schedules.py
      tasks.py               # 修改,增加过滤
      auth.py                # 修改 /api/auth/me
    services/
      __init__.py
      molizhishu_client.py   # 沿用
      scheduler.py           # APScheduler 集成 + run_schedule
      logo_storage.py
    static/                  # 客户 logo 静态目录(运行时挂载 /data/logos)
  tests/
    conftest.py
    test_customer_api.py
    test_project_api.py
    test_schedule_api.py
    test_scheduler.py
    test_auth_me.py
  pyproject.toml
  Dockerfile
  alembic.ini

frontend/
  src/
    main.tsx
    App.tsx
    router.tsx
    api/
      client.ts
      auth.ts
      customers.ts
      projects.ts
      schedules.ts
    auth/
      AuthProvider.tsx
      RequireRole.tsx
    pages/
      Login.tsx
      Customers/
        List.tsx
        Edit.tsx
      Projects/
        List.tsx
        Detail.tsx
      Schedules/
        List.tsx
        Edit.tsx
        Runs.tsx
      ProjectTasks/
        List.tsx
    components/
      LogoUpload.tsx
      SlotPicker.tsx
      RequestPreview.tsx
  package.json
  vite.config.ts
  tsconfig.json

docker-compose.yml
README.md
```

---

## Phase 1:后端基础设施

### Task 1:FastAPI 后端脚手架

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/main.py`
- Create: `backend/app/config.py`
- Create: `backend/app/db.py`
- Create: `backend/.env.example`

- [ ] **Step 1:写 `backend/pyproject.toml`**

```toml
[project]
name = "windx-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "fastapi>=0.110",
  "uvicorn[standard]>=0.27",
  "sqlalchemy>=2.0",
  "pymysql>=1.1",
  "alembic>=1.13",
  "pydantic>=2.6",
  "pydantic-settings>=2.2",
  "apscheduler>=3.10",
  "httpx>=0.27",
  "python-multipart>=0.0.9",
  "python-jose[cryptography]>=3.3",
  "passlib[bcrypt]>=1.7",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.0",
  "pytest-asyncio>=0.23",
  "freezegun>=1.4",
  "ruff>=0.3",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2:写 `backend/app/config.py`**

```python
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_port: int = 18083
    tz: str = "Asia/Shanghai"
    database_url: str

    molizhishu_token: str = ""
    molizhishu_base_url: str = "https://business-api.molizhishu.com/api/business/monitor"
    molizhishu_city_url: str = "https://business-api.molizhishu.com/api/business/eip-edge/ports/city-info"
    molizhishu_callback_url: str = ""
    molizhishu_timeout_seconds: int = 30
    molizhishu_sync_enabled: bool = True
    molizhishu_sync_interval_seconds: int = 60
    molizhishu_sync_limit: int = 20
    molizhishu_allow_api_key_update: bool = True

    logo_storage_dir: str = Field(default="/data/logos")
    logo_max_bytes: int = 2 * 1024 * 1024

    jwt_secret: str = "CHANGE-ME-IN-PROD"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7


@lru_cache
def get_settings() -> Settings:
    return Settings()
```

- [ ] **Step 3:写 `backend/app/db.py`**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
engine = create_engine(
    _settings.database_url,
    pool_pre_ping=True,
    pool_recycle=3600,
    future=True,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

- [ ] **Step 4:写 `backend/app/main.py`(最小可启动)**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="windx-backend", lifespan=lifespan)
settings = get_settings()
app.mount("/static", StaticFiles(directory=settings.logo_storage_dir, check_dir=False), name="static")


@app.get("/health")
def health():
    return {"ok": True}
```

- [ ] **Step 5:写 `backend/.env.example`**

```
APP_PORT=18083
TZ=Asia/Shanghai
DATABASE_URL=mysql+pymysql://admin:admin123@106.52.233.226:3306/geo?charset=utf8mb4
MOLIZHISHU_TOKEN=
MOLIZHISHU_BASE_URL=https://business-api.molizhishu.com/api/business/monitor
MOLIZHISHU_CITY_URL=https://business-api.molizhishu.com/api/business/eip-edge/ports/city-info
MOLIZHISHU_CALLBACK_URL=
MOLIZHISHU_TIMEOUT_SECONDS=30
JWT_SECRET=CHANGE-ME-IN-PROD
LOGO_STORAGE_DIR=/data/logos
```

- [ ] **Step 6:本地启动验证**

```bash
cd backend
pip install -e ".[dev]"
cp .env.example .env  # 填入真实 DATABASE_URL 和 MOLIZHISHU_TOKEN
uvicorn app.main:app --reload --port 18083
curl http://localhost:18083/health
# Expected: {"ok":true}
```

- [ ] **Step 7:Commit**

```bash
git add backend/
git commit -m "feat(backend): scaffold fastapi app with config and db session"
```

---

### Task 2:数据库迁移(geo_customers / geo_projects / geo_project_* / geo_competitors / geo_schedules / geo_schedule_slots / geo_schedule_runs + 现有表扩展)

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/versions/20260807_0001_add_schedule_management.py`

- [ ] **Step 1:初始化 Alembic**

```bash
cd backend
alembic init alembic
```

- [ ] **Step 2:配置 `backend/alembic/env.py` 读取 Settings**

```python
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from app.db import Base
from app.config import get_settings
from app.models import *  # noqa: F401,F403  确保所有模型被 import

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 3:写迁移文件 `backend/alembic/versions/20260807_0001_add_schedule_management.py`**

```python
"""add schedule management

Revision ID: 20260807_0001
Revises:
Create Date: 2026-08-07
"""
from alembic import op
import sqlalchemy as sa

revision = "20260807_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # geo_admin_users 扩展
    op.add_column("geo_admin_users", sa.Column("role", sa.Enum("super_admin", "customer_admin", name="admin_role"), nullable=False, server_default="super_admin"))
    op.add_column("geo_admin_users", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_admin_users_customer", "geo_admin_users", "geo_customers", ["customer_id"], ["id"])

    # geo_customers
    op.create_table(
        "geo_customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("logo_path", sa.String(255), nullable=True),
        sa.Column("contact", sa.String(128), nullable=True),
        sa.Column("status", sa.Enum("active", "disabled", name="customer_status"), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # geo_projects
    op.create_table(
        "geo_projects",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("customer_id", sa.Integer(), sa.ForeignKey("geo_customers.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("status", sa.Enum("active", "disabled", name="project_status"), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("customer_id", "code", name="uq_project_customer_code"),
    )
    op.create_index("ix_projects_customer_id", "geo_projects", ["customer_id"])

    # geo_project_prompts
    op.create_table(
        "geo_project_prompts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("geo_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # geo_project_keywords
    op.create_table(
        "geo_project_keywords",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("geo_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("keyword", sa.String(255), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # geo_project_platforms
    op.create_table(
        "geo_project_platforms",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("geo_projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("screenshot", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
    )

    # geo_competitors
    op.create_table(
        "geo_competitors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("subtask_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source", sa.Enum("answer_content", "reference_list", name="competitor_source"), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["geo_tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["subtask_id"], ["geo_subtasks.id"], ondelete="SET NULL"),
    )

    # geo_schedules
    op.create_table(
        "geo_schedules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("project_id", sa.Integer(), sa.ForeignKey("geo_projects.id"), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("enabled", "disabled", name="schedule_status"), nullable=False, server_default="enabled"),
        sa.Column("max_daily_runs", sa.SmallInteger(), nullable=False, server_default="2"),
        sa.Column("prompts_override_json", sa.JSON(), nullable=True),
        sa.Column("keywords_override_json", sa.JSON(), nullable=True),
        sa.Column("platforms_override_json", sa.JSON(), nullable=True),
        sa.Column("region_code_override", sa.String(16), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("geo_admin_users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_schedules_customer_id", "geo_schedules", ["customer_id"])
    op.create_index("ix_schedules_project_id", "geo_schedules", ["project_id"])
    op.create_index("ix_schedules_status", "geo_schedules", ["status"])

    # geo_schedule_slots
    op.create_table(
        "geo_schedule_slots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("geo_schedules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("slot_index", sa.SmallInteger(), nullable=False),
        sa.Column("hour", sa.SmallInteger(), nullable=False),
        sa.Column("minute", sa.SmallInteger(), nullable=False),
        sa.UniqueConstraint("schedule_id", "slot_index", name="uq_slot_per_schedule"),
        sa.CheckConstraint("slot_index IN (1, 2)", name="ck_slot_index_range"),
    )

    # geo_schedule_runs
    op.create_table(
        "geo_schedule_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("schedule_id", sa.Integer(), sa.ForeignKey("geo_schedules.id"), nullable=False),
        sa.Column("slot_index", sa.SmallInteger(), nullable=False),
        sa.Column("trigger_type", sa.Enum("cron", "manual", name="run_trigger"), nullable=False),
        sa.Column("triggered_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.Enum("queued", "running", "success", "failed", "skipped", name="run_status"), nullable=False, server_default="queued"),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cooldown_key", sa.String(64), nullable=True, unique=True),
    )
    op.create_index("ix_runs_schedule_id", "geo_schedule_runs", ["schedule_id"])

    # geo_tasks 扩展
    op.add_column("geo_tasks", sa.Column("customer_id", sa.Integer(), nullable=True))
    op.add_column("geo_tasks", sa.Column("project_id", sa.Integer(), nullable=True))
    op.add_column("geo_tasks", sa.Column("schedule_id", sa.Integer(), nullable=True))
    op.add_column("geo_tasks", sa.Column("schedule_run_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_tasks_customer", "geo_tasks", "geo_customers", ["customer_id"], ["id"])
    op.create_foreign_key("fk_tasks_project", "geo_tasks", "geo_projects", ["project_id"], ["id"])
    op.create_foreign_key("fk_tasks_schedule", "geo_tasks", "geo_schedules", ["schedule_id"], ["id"])
    op.create_foreign_key("fk_tasks_schedule_run", "geo_tasks", "geo_schedule_runs", ["schedule_run_id"], ["id"])
    op.create_index("ix_tasks_customer_created", "geo_tasks", ["customer_id", "created_local_at"])
    op.create_index("ix_tasks_project_created", "geo_tasks", ["project_id", "created_local_at"])


def downgrade():
    op.drop_index("ix_tasks_project_created", table_name="geo_tasks")
    op.drop_index("ix_tasks_customer_created", table_name="geo_tasks")
    op.drop_constraint("fk_tasks_schedule_run", "geo_tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_schedule", "geo_tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_project", "geo_tasks", type_="foreignkey")
    op.drop_constraint("fk_tasks_customer", "geo_tasks", type_="foreignkey")
    op.drop_column("geo_tasks", "schedule_run_id")
    op.drop_column("geo_tasks", "schedule_id")
    op.drop_column("geo_tasks", "project_id")
    op.drop_column("geo_tasks", "customer_id")
    op.drop_index("ix_runs_schedule_id", table_name="geo_schedule_runs")
    op.drop_table("geo_schedule_runs")
    op.drop_table("geo_schedule_slots")
    op.drop_table("geo_schedules")
    op.drop_table("geo_competitors")
    op.drop_table("geo_project_platforms")
    op.drop_table("geo_project_keywords")
    op.drop_table("geo_project_prompts")
    op.drop_index("ix_projects_customer_id", table_name="geo_projects")
    op.drop_table("geo_projects")
    op.drop_table("geo_customers")
    op.drop_constraint("fk_admin_users_customer", "geo_admin_users", type_="foreignkey")
    op.drop_column("geo_admin_users", "customer_id")
    op.drop_column("geo_admin_users", "role")
```

- [ ] **Step 4:运行迁移**

```bash
cd backend
alembic upgrade head
# Expected: 成功,DB 中可见 9 张新表 + 现有表扩展列
```

- [ ] **Step 5:Commit**

```bash
git add backend/alembic/
git commit -m "feat(db): add schedule management tables and geo_tasks extensions"
```

---

### Task 3:SQLAlchemy 模型 + Pydantic schemas

**Files:**
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/models/customer.py`
- Create: `backend/app/models/project.py`
- Create: `backend/app/models/schedule.py`
- Create: `backend/app/schemas/__init__.py`
- Create: `backend/app/schemas/customer.py`
- Create: `backend/app/schemas/project.py`
- Create: `backend/app/schemas/schedule.py`
- Create: `backend/app/schemas/schedule_run.py`
- Create: `backend/app/deps.py`(auth 依赖)

- [ ] **Step 1:写 `backend/app/models/__init__.py`**

```python
from app.models.customer import Customer, AdminUser  # noqa: F401
from app.models.project import (  # noqa: F401
    Project,
    ProjectPrompt,
    ProjectKeyword,
    ProjectPlatform,
    Competitor,
)
from app.models.schedule import Schedule, ScheduleSlot, ScheduleRun  # noqa: F401
```

- [ ] **Step 2:写 `backend/app/models/customer.py`**

```python
from datetime import datetime
from sqlalchemy import String, Enum, Integer, ForeignKey, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db import Base


class AdminUser(Base):
    __tablename__ = "geo_admin_users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str | None] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(Enum("super_admin", "customer_admin", name="admin_role"), default="super_admin")
    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("geo_customers.id"))
    status: Mapped[str] = mapped_column(Enum("active", "disabled", name="admin_status"), default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Customer(Base):
    __tablename__ = "geo_customers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64), unique=True)
    logo_path: Mapped[str | None] = mapped_column(String(255))
    contact: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(Enum("active", "disabled", name="customer_status"), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

- [ ] **Step 3:写 `backend/app/models/project.py`**

```python
from datetime import datetime
from sqlalchemy import String, Enum, Integer, ForeignKey, Text, SmallInteger, JSON, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class Project(Base):
    __tablename__ = "geo_projects"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    customer_id: Mapped[int] = mapped_column(Integer, ForeignKey("geo_customers.id"))
    name: Mapped[str] = mapped_column(String(128))
    code: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(Enum("active", "disabled", name="project_status"), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ProjectPrompt(Base):
    __tablename__ = "geo_project_prompts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("geo_projects.id", ondelete="CASCADE"))
    prompt: Mapped[str] = mapped_column(Text)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectKeyword(Base):
    __tablename__ = "geo_project_keywords"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("geo_projects.id", ondelete="CASCADE"))
    keyword: Mapped[str] = mapped_column(String(255))
    sort: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProjectPlatform(Base):
    __tablename__ = "geo_project_platforms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("geo_projects.id", ondelete="CASCADE"))
    platform: Mapped[str] = mapped_column(String(32))
    mode: Mapped[str] = mapped_column(String(32))
    screenshot: Mapped[int] = mapped_column(SmallInteger, default=0)
    sort: Mapped[int] = mapped_column(Integer, default=0)


class Competitor(Base):
    __tablename__ = "geo_competitors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(Integer, ForeignKey("geo_tasks.id", ondelete="CASCADE"))
    subtask_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("geo_subtasks.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(Enum("answer_content", "reference_list", name="competitor_source"))
    raw_json: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
```

- [ ] **Step 4:写 `backend/app/models/schedule.py`**

```python
from datetime import datetime
from sqlalchemy import String, Enum, Integer, ForeignKey, SmallInteger, JSON, Text, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class Schedule(Base):
    __tablename__ = "geo_schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    project_id: Mapped[int] = mapped_column(Integer, ForeignKey("geo_projects.id"))
    customer_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(Enum("enabled", "disabled", name="schedule_status"), default="enabled")
    max_daily_runs: Mapped[int] = mapped_column(SmallInteger, default=2)
    prompts_override_json: Mapped[dict | None] = mapped_column(JSON)
    keywords_override_json: Mapped[list | None] = mapped_column(JSON)
    platforms_override_json: Mapped[list | None] = mapped_column(JSON)
    region_code_override: Mapped[str | None] = mapped_column(String(16))
    created_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("geo_admin_users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ScheduleSlot(Base):
    __tablename__ = "geo_schedule_slots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(Integer, ForeignKey("geo_schedules.id", ondelete="CASCADE"))
    slot_index: Mapped[int] = mapped_column(SmallInteger)
    hour: Mapped[int] = mapped_column(SmallInteger)
    minute: Mapped[int] = mapped_column(SmallInteger)


class ScheduleRun(Base):
    __tablename__ = "geo_schedule_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    schedule_id: Mapped[int] = mapped_column(Integer, ForeignKey("geo_schedules.id"))
    slot_index: Mapped[int] = mapped_column(SmallInteger)
    trigger_type: Mapped[str] = mapped_column(Enum("cron", "manual", name="run_trigger"))
    triggered_at: Mapped[datetime] = mapped_column(DateTime)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(Enum("queued", "running", "success", "failed", "skipped", name="run_status"), default="queued")
    task_id: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    cooldown_key: Mapped[str | None] = mapped_column(String(64), unique=True)
```

- [ ] **Step 5:写 `backend/app/schemas/customer.py`**

```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class CustomerBase(BaseModel):
    name: str = Field(..., max_length=128)
    code: str = Field(..., max_length=64)
    contact: str | None = None
    status: str = "active"


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    contact: str | None = None
    status: str | None = None


class CustomerOut(CustomerBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    logo_path: str | None
    logo_url: str | None = None
    created_at: datetime
    updated_at: datetime


class CustomerListOut(BaseModel):
    items: list[CustomerOut]
    total: int
    page: int
    size: int
```

- [ ] **Step 6:写 `backend/app/schemas/project.py`**

```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class ProjectBase(BaseModel):
    name: str = Field(..., max_length=128)
    code: str = Field(..., max_length=64)
    status: str = "active"


class ProjectCreate(ProjectBase):
    customer_id: int


class ProjectUpdate(BaseModel):
    name: str | None = None
    code: str | None = None
    status: str | None = None


class ProjectOut(ProjectBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    customer_id: int
    created_at: datetime
    updated_at: datetime


class ProjectDetailOut(ProjectOut):
    prompts: list[str] = []
    keywords: list[str] = []
    platforms: list[dict] = []


class ProjectListOut(BaseModel):
    items: list[ProjectOut]
    total: int
    page: int
    size: int


class PromptsUpdate(BaseModel):
    prompts: list[str]


class KeywordsUpdate(BaseModel):
    keywords: list[str]


class PlatformsUpdate(BaseModel):
    platforms: list[dict]  # [{"platform":..., "mode":..., "screenshot":0/1/2}]
```

- [ ] **Step 7:写 `backend/app/schemas/schedule.py`**

```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class SlotIn(BaseModel):
    slot_index: int = Field(..., ge=1, le=2)
    hour: int = Field(..., ge=0, le=23)
    minute: int = Field(..., ge=0, le=59)


class SlotOut(SlotIn):
    model_config = ConfigDict(from_attributes=True)
    id: int


class ScheduleBase(BaseModel):
    name: str = Field(..., max_length=128)
    project_id: int
    prompts_override: list[str] | None = None
    keywords_override: list[str] | None = None
    platforms_override: list[dict] | None = None
    region_code_override: str | None = None


class ScheduleCreate(ScheduleBase):
    slots: list[SlotIn] = Field(..., min_length=1, max_length=2)


class ScheduleUpdate(BaseModel):
    name: str | None = None
    slots: list[SlotIn] | None = Field(default=None, min_length=1, max_length=2)
    prompts_override: list[str] | None = None
    keywords_override: list[str] | None = None
    platforms_override: list[dict] | None = None
    region_code_override: str | None = None


class ScheduleStatusUpdate(BaseModel):
    status: str = Field(..., pattern="^(enabled|disabled)$")


class ScheduleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    project_id: int
    customer_id: int
    status: str
    max_daily_runs: int
    region_code_override: str | None
    slots: list[SlotOut]
    prompts_override: list[str] | None
    keywords_override: list[str] | None
    platforms_override: list[dict] | None
    created_at: datetime
    updated_at: datetime


class ScheduleListOut(BaseModel):
    items: list[ScheduleOut]
    total: int
    page: int
    size: int


class TriggerOut(BaseModel):
    run_id: int
```

- [ ] **Step 8:写 `backend/app/schemas/schedule_run.py`**

```python
from datetime import datetime
from pydantic import BaseModel, ConfigDict


class ScheduleRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    schedule_id: int
    slot_index: int
    trigger_type: str
    triggered_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    status: str
    task_id: int | None
    error_message: str | None


class ScheduleRunListOut(BaseModel):
    items: list[ScheduleRunOut]
    total: int
    page: int
    size: int
```

- [ ] **Step 9:写 `backend/app/deps.py`**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from jose import jwt, JWTError

from app.config import get_settings
from app.db import get_db
from app.models.customer import AdminUser

bearer = HTTPBearer(auto_error=False)
settings = get_settings()


def get_current_user(
    cred: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> AdminUser:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing token")
    try:
        payload = jwt.decode(cred.credentials, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        user_id = int(payload["sub"])
    except (JWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")
    user = db.get(AdminUser, user_id)
    if not user or user.status != "active":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user inactive")
    return user


def require_super_admin(user: AdminUser = Depends(get_current_user)) -> AdminUser:
    if user.role != "super_admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "super admin required")
    return user
```

- [ ] **Step 10:模型导入并 `python -c "from app.models import *"` 验证无错**

```bash
cd backend
python -c "from app.models import *; from app.db import Base; print(list(Base.metadata.tables.keys()))"
# Expected: 至少包含 ['geo_admin_users','geo_customers','geo_projects','geo_project_prompts','geo_project_keywords','geo_project_platforms','geo_competitors','geo_schedules','geo_schedule_slots','geo_schedule_runs']
```

- [ ] **Step 11:Commit**

```bash
git add backend/app/
git commit -m "feat(models): add customer/project/schedule models and schemas"
```

---

## Phase 2:客户与项目管理 API

### Task 4:Logo 存储服务 + 客户 CRUD API

**Files:**
- Create: `backend/app/services/logo_storage.py`
- Create: `backend/app/api/customers.py`
- Modify: `backend/app/main.py`(挂载路由)

- [ ] **Step 1:写测试 `backend/tests/test_customer_api.py`**

```python
import io
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.main import app
from app.db import Base, get_db
from app.config import get_settings
from app.models.customer import AdminUser

settings = get_settings()
test_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)


def override_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def super_admin_token():
    import asyncio
    from app.deps import get_current_user
    from app.models.customer import AdminUser as AU

    async def _mk():
        with TestSessionLocal() as db:
            u = AU(username="root", password_hash="x", role="super_admin", status="active")
            db.add(u)
            db.commit()
            db.refresh(u)
            return u.id

    uid = await asyncio.get_event_loop().run_in_executor(None, _mk)
    from jose import jwt
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_create_customer(client, super_admin_token):
    r = await client.post(
        "/api/customers",
        json={"name": "Acme", "code": "ACME", "contact": "alice@acme.com"},
        headers={"Authorization": f"Bearer {super_admin_token}"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["name"] == "Acme"
    assert data["code"] == "ACME"
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_create_customer_duplicate_code(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    await client.post("/api/customers", json={"name": "A", "code": "DUP"}, headers=h)
    r = await client.post("/api/customers", json={"name": "B", "code": "DUP"}, headers=h)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_upload_logo_png(client, super_admin_token):
    h = {"Authorization": f"Bearer {super_admin_token}"}
    create = await client.post("/api/customers", json={"name": "L", "code": "LOGO"}, headers=h)
    cid = create.json()["id"]
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # 假 PNG 头
    files = {"file": ("logo.png", io.BytesIO(png_bytes), "image/png")}
    r = await client.post(f"/api/customers/{cid}/logo", files=files, headers=h)
    assert r.status_code == 200
    assert r.json()["logo_path"].startswith("logos/")
```

- [ ] **Step 2:写 `backend/app/services/logo_storage.py`**

```python
import os
import uuid
from pathlib import Path
from fastapi import HTTPException

ALLOWED_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def save_logo(storage_dir: str, customer_id: int, content_type: str, content: bytes, max_bytes: int) -> str:
    if content_type not in ALLOWED_TYPES:
        raise HTTPException(400, f"unsupported content type: {content_type}")
    if len(content) > max_bytes:
        raise HTTPException(413, "logo too large")
    Path(storage_dir).mkdir(parents=True, exist_ok=True)
    filename = f"{customer_id}{ALLOWED_TYPES[content_type]}"
    path = Path(storage_dir) / filename
    path.write_bytes(content)
    return f"logos/{filename}"
```

- [ ] **Step 3:写 `backend/app/api/customers.py`**

```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_super_admin
from app.models.customer import Customer, AdminUser
from app.schemas.customer import (
    CustomerCreate, CustomerUpdate, CustomerOut, CustomerListOut,
)
from app.services.logo_storage import save_logo
from app.config import get_settings

router = APIRouter(prefix="/api/customers", tags=["customers"])
settings = get_settings()


def _to_out(c: Customer) -> CustomerOut:
    out = CustomerOut.model_validate(c)
    out.logo_url = f"/static/{c.logo_path}" if c.logo_path else None
    return out


@router.post("", response_model=CustomerOut)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    if db.scalar(select(Customer).where(Customer.code == payload.code)):
        raise HTTPException(400, "code already exists")
    c = Customer(**payload.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.get("", response_model=CustomerListOut)
def list_customers(
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    page, size = max(1, page), min(100, max(1, size))
    stmt = select(Customer)
    if status:
        stmt = stmt.where(Customer.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
    return CustomerListOut(items=[_to_out(c) for c in items], total=total, page=page, size=size)


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(customer_id: int, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "not found")
    return _to_out(c)


@router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.post("/{customer_id}/logo", response_model=CustomerOut)
async def upload_logo(
    customer_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "not found")
    content = await file.read()
    c.logo_path = save_logo(settings.logo_storage_dir, customer_id, file.content_type or "", content, settings.logo_max_bytes)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    from app.models.project import Project
    from app.models.schedule import Schedule
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "not found")
    if db.scalar(select(func.count()).select_from(Project).where(Project.customer_id == customer_id)) or \
       db.scalar(select(func.count()).select_from(Schedule).where(Schedule.customer_id == customer_id)):
        raise HTTPException(400, "customer has related projects or schedules")
    db.delete(c)
    db.commit()
    return {"ok": True}
```

- [ ] **Step 4:挂载到 `backend/app/main.py`**

```python
from app.api import customers
app.include_router(customers.router)
```

- [ ] **Step 5:运行测试**

```bash
cd backend
pytest tests/test_customer_api.py -v
# Expected: 3 passed
```

- [ ] **Step 6:Commit**

```bash
git add backend/
git commit -m "feat(customers): CRUD API + logo upload"
```

---

### Task 5:项目 CRUD API + 项目配置 4 tab API

**Files:**
- Create: `backend/app/api/projects.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1:写测试 `backend/tests/test_project_api.py`**

```python
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.db import Base, get_db
from app.config import get_settings
from app.models.customer import AdminUser
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import io, asyncio
from jose import jwt

settings = get_settings()
test_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)


def override_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _make_token():
    def _mk():
        with TestSessionLocal() as db:
            u = AdminUser(username="root", password_hash="x", role="super_admin", status="active")
            db.add(u); db.commit(); db.refresh(u)
            return u.id
    uid = await asyncio.get_event_loop().run_in_executor(None, _mk)
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.fixture
async def admin_token():
    return await _make_token()


async def _make_customer(token):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/customers", json={"name": "C", "code": "C1"},
                         headers={"Authorization": f"Bearer {token}"})
        return r.json()["id"]


@pytest.mark.asyncio
async def test_project_crud_and_config_tabs(client, admin_token):
    h = {"Authorization": f"Bearer {admin_token}"}
    cid = await _make_customer(admin_token)

    r = await client.post(f"/api/customers/{cid}/projects", json={"name": "P", "code": "P1"}, headers=h)
    assert r.status_code == 200
    pid = r.json()["id"]

    # 4 tab 配置
    r = await client.put(f"/api/projects/{pid}/prompts", json={"prompts": ["q1", "q2"]}, headers=h)
    assert r.status_code == 200
    r = await client.put(f"/api/projects/{pid}/keywords", json={"keywords": ["k1"]}, headers=h)
    assert r.status_code == 200
    r = await client.put(f"/api/projects/{pid}/platforms",
                         json={"platforms": [{"platform": "deepseek", "mode": "search", "screenshot": 1}]},
                         headers=h)
    assert r.status_code == 200

    # 详情拿全
    r = await client.get(f"/api/projects/{pid}", headers=h)
    assert r.status_code == 200
    data = r.json()
    assert data["prompts"] == ["q1", "q2"]
    assert data["keywords"] == ["k1"]
    assert data["platforms"] == [{"platform": "deepseek", "mode": "search", "screenshot": 1}]
```

- [ ] **Step 2:写 `backend/app/api/projects.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_super_admin
from app.models.customer import Customer, AdminUser
from app.models.project import Project, ProjectPrompt, ProjectKeyword, ProjectPlatform
from app.schemas.project import (
    ProjectCreate, ProjectUpdate, ProjectOut, ProjectDetailOut, ProjectListOut,
    PromptsUpdate, KeywordsUpdate, PlatformsUpdate,
)

router = APIRouter(tags=["projects"])


def _detail(p: Project, db: Session) -> ProjectDetailOut:
    prompts = [pp.prompt for pp in db.scalars(select(ProjectPrompt).where(ProjectPrompt.project_id == p.id).order_by(ProjectPrompt.sort)).all()]
    keywords = [pk.keyword for pk in db.scalars(select(ProjectKeyword).where(ProjectKeyword.project_id == p.id).order_by(ProjectKeyword.sort)).all()]
    platforms = [{"platform": pl.platform, "mode": pl.mode, "screenshot": pl.screenshot}
                 for pl in db.scalars(select(ProjectPlatform).where(ProjectPlatform.project_id == p.id).order_by(ProjectPlatform.sort)).all()]
    return ProjectDetailOut(
        id=p.id, customer_id=p.customer_id, name=p.name, code=p.code, status=p.status,
        created_at=p.created_at, updated_at=p.updated_at,
        prompts=prompts, keywords=keywords, platforms=platforms,
    )


@router.post("/api/customers/{customer_id}/projects", response_model=ProjectOut)
def create_project(
    customer_id: int,
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    if not db.get(Customer, customer_id):
        raise HTTPException(404, "customer not found")
    if db.scalar(select(Project).where(Project.customer_id == customer_id, Project.code == payload.code)):
        raise HTTPException(400, "project code exists in this customer")
    p = Project(customer_id=customer_id, **payload.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return ProjectOut.model_validate(p)


@router.get("/api/projects", response_model=ProjectListOut)
def list_projects(
    page: int = 1, size: int = 20,
    customer_id: int | None = None, status: str | None = None,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    page, size = max(1, page), min(100, max(1, size))
    stmt = select(Project)
    if customer_id:
        stmt = stmt.where(Project.customer_id == customer_id)
    if status:
        stmt = stmt.where(Project.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Project.id.desc()).offset((page - 1) * size).limit(size)).all()
    return ProjectListOut(items=[ProjectOut.model_validate(p) for p in items], total=total, page=page, size=size)


@router.get("/api/projects/{project_id}", response_model=ProjectDetailOut)
def get_project(project_id: int, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "not found")
    return _detail(p, db)


@router.put("/api/projects/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return ProjectOut.model_validate(p)


@router.delete("/api/projects/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    from app.models.schedule import Schedule
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "not found")
    if db.scalar(select(func.count()).select_from(Schedule).where(Schedule.project_id == project_id)):
        raise HTTPException(400, "project has schedules")
    db.delete(p)
    db.commit()
    return {"ok": True}


def _replace(db: Session, model, project_id: int, items: list[dict], fields: list[str], order_field: str):
    db.query(model).filter(model.project_id == project_id).delete()
    for i, it in enumerate(items):
        kwargs = {f: it[f] for f in fields}
        kwargs[order_field] = i
        kwargs["project_id"] = project_id
        db.add(model(**kwargs))
    db.commit()


@router.put("/api/projects/{project_id}/prompts")
def put_prompts(project_id: int, payload: PromptsUpdate, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "not found")
    _replace(db, ProjectPrompt, project_id, [{"prompt": p} for p in payload.prompts], ["prompt"], "sort")
    return {"ok": True, "count": len(payload.prompts)}


@router.put("/api/projects/{project_id}/keywords")
def put_keywords(project_id: int, payload: KeywordsUpdate, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "not found")
    _replace(db, ProjectKeyword, project_id, [{"keyword": k} for k in payload.keywords], ["keyword"], "sort")
    return {"ok": True, "count": len(payload.keywords)}


@router.put("/api/projects/{project_id}/platforms")
def put_platforms(project_id: int, payload: PlatformsUpdate, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    if not db.get(Project, project_id):
        raise HTTPException(404, "not found")
    _replace(db, ProjectPlatform, project_id, payload.platforms, ["platform", "mode", "screenshot"], "sort")
    return {"ok": True, "count": len(payload.platforms)}
```

- [ ] **Step 3:挂载到 `backend/app/main.py`**

```python
from app.api import customers, projects
app.include_router(customers.router)
app.include_router(projects.router)
```

- [ ] **Step 4:运行测试**

```bash
pytest tests/test_project_api.py -v
# Expected: 1 passed
```

- [ ] **Step 5:Commit**

```bash
git add backend/
git commit -m "feat(projects): CRUD API + 4-tab config APIs"
```

---

### Task 6:`/api/auth/me` 返回 role + customer_id

**Files:**
- Modify: `backend/app/api/auth.py`(修改 `/me`)
- Create: `backend/tests/test_auth_me.py`(若 auth.py 不存在则一并创建)

- [ ] **Step 1:写 `backend/tests/test_auth_me.py`**

```python
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jose import jwt
from app.main import app
from app.db import Base, get_db
from app.config import get_settings
from app.models.customer import AdminUser

settings = get_settings()
test_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)
app.dependency_overrides[get_db] = lambda: (yield TestSessionLocal()) if False else (lambda: (_ for _ in ()).throw(NotImplementedError))


def override_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


async def _make_user(role="super_admin", customer_id=None):
    def _mk():
        with TestSessionLocal() as db:
            u = AdminUser(username="u", password_hash="x", role=role, status="active", customer_id=customer_id)
            db.add(u); db.commit(); db.refresh(u)
            return u.id
    uid = await asyncio.get_event_loop().run_in_executor(None, _mk)
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


@pytest.mark.asyncio
async def test_auth_me_returns_role_and_customer_id():
    token = await _make_user(role="super_admin", customer_id=None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "super_admin"
        assert data.get("customer_id") is None
```

- [ ] **Step 2:实现/修改 `backend/app/api/auth.py`**

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.models.customer import AdminUser

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(user: AdminUser = Depends(get_current_user), db: Session = Depends(get_db)):
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
        "customer_id": user.customer_id,
        "status": user.status,
    }
```

- [ ] **Step 3:挂载到 `backend/app/main.py`**

```python
from app.api import auth
app.include_router(auth.router)
```

- [ ] **Step 4:运行测试**

```bash
pytest tests/test_auth_me.py -v
# Expected: 1 passed
```

- [ ] **Step 5:Commit**

```bash
git add backend/
git commit -m "feat(auth): /api/auth/me returns role and customer_id"
```

---

## Phase 3:调度管理

### Task 7:`MolizhishuClient.submit_task` 占位 + `run_schedule` 核心逻辑

**Files:**
- Create: `backend/app/services/molizhishu_client.py`(沿用现有契约,提供 `submit_task`)
- Create: `backend/app/services/scheduler.py`(含 `run_schedule`)

- [ ] **Step 1:写 `backend/app/services/molizhishu_client.py`**

```python
import httpx
from typing import Any


class MolizhishuError(Exception):
    def __init__(self, code: int | None, message: str, http_status: int | None = None, body: Any = None):
        super().__init__(f"molizhishu error code={code} message={message}")
        self.code = code
        self.message = message
        self.http_status = http_status
        self.body = body


class MolizhishuClient:
    def __init__(self, base_url: str, token: str, timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}

    async def submit_task(self, payload: dict) -> dict:
        url = f"{self.base_url}/task/batch/shared"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(url, json=payload, headers={**self._headers(), "Content-Type": "application/json"})
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code // 100 != 2:
            raise MolizhishuError(body.get("code"), body.get("message", "http error"), r.status_code, body)
        if not body.get("success"):
            raise MolizhishuError(body.get("code"), body.get("message", "business error"), r.status_code, body)
        return body.get("data", {})
```

- [ ] **Step 2:写 `backend/app/services/scheduler.py`(只含 `run_schedule`,APScheduler 集成在 Task 8)**

```python
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.schedule import Schedule, ScheduleSlot, ScheduleRun
from app.models.project import Project, ProjectPrompt, ProjectKeyword, ProjectPlatform
from app.config import get_settings
from app.services.molizhishu_client import MolizhishuClient, MolizhishuError


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _now() -> datetime:
    return datetime.now(SHANGHAI)


def _cooldown_key(schedule_id: int, slot_index: int, when: datetime) -> str:
    bucket = when.minute // 5
    return f"schedule-{schedule_id}-slot-{slot_index}-{when.strftime('%Y%m%d%H')}{bucket}"


def run_schedule(schedule_id: int, slot_index: int, trigger_type: str) -> int | None:
    """同步执行一次调度。返回 run_id 或 None(冷却命中)。"""
    db = SessionLocal()
    settings = get_settings()
    now = _now()
    cooldown = _cooldown_key(schedule_id, slot_index, now)

    run = ScheduleRun(
        schedule_id=schedule_id, slot_index=slot_index, trigger_type=trigger_type,
        triggered_at=now, status="running", started_at=now, cooldown_key=cooldown,
    )
    db.add(run)
    try:
        db.commit()
        db.refresh(run)
    except Exception:
        # UNIQUE 冲突:cooldown 命中
        db.rollback()
        existing = db.query(ScheduleRun).filter(ScheduleRun.cooldown_key == cooldown).first()
        if existing:
            existing.status = "skipped"
            db.commit()
        return None

    try:
        sched = db.get(Schedule, schedule_id)
        if not sched:
            raise RuntimeError("schedule not found")

        project = db.get(Project, sched.project_id)
        if not project:
            raise RuntimeError("project not found")

        # 组装 prompts
        prompts = sched.prompts_override_json
        if prompts is None:
            prompts = [p.prompt for p in db.query(ProjectPrompt).filter(ProjectPrompt.project_id == project.id).order_by(ProjectPrompt.sort).all()]
        if not prompts:
            raise RuntimeError("prompts is empty")

        # 组装 platforms
        platforms = sched.platforms_override_json
        if platforms is None:
            platforms = [{"platform": pl.platform, "mode": pl.mode, "screenshot": pl.screenshot}
                         for pl in db.query(ProjectPlatform).filter(ProjectPlatform.project_id == project.id).order_by(ProjectPlatform.sort).all()]
        if not platforms:
            raise RuntimeError("platforms is empty")

        # 组装 monitorKeywords
        keywords = sched.keywords_override_json
        if keywords is None:
            keywords = [k.keyword for k in db.query(ProjectKeyword).filter(ProjectKeyword.project_id == project.id).order_by(ProjectKeyword.sort).all()]
        monitor_keywords = ",".join(keywords) if keywords else None

        # callback
        callback_url = settings.molizhishu_callback_url or None

        payload = {
            "prompts": prompts,
            "platforms": platforms,
        }
        if monitor_keywords:
            payload["monitorKeywords"] = monitor_keywords
        if sched.region_code_override:
            payload["regionCode"] = [sched.region_code_override]
        if callback_url:
            payload["callbackUrl"] = callback_url

        # 远端调用(异步场景下被外层 asyncio 包裹,此处提供同步入口供 threadpool 使用)
        import asyncio
        client = MolizhishuClient(settings.molizhishu_base_url, settings.molizhishu_token, settings.molizhishu_timeout_seconds)
        data = asyncio.run(client.submit_task(payload))

        # 写 geo_tasks / geo_subtasks(沿用 api调用prompt.md §4 规则)
        from app.models.task import Task, SubTask  # 沿用现有 Task 模型

        t = Task(
            task_id=data["taskId"],
            status=data.get("status", "pending"),
            customer_id=sched.customer_id,
            project_id=sched.project_id,
            schedule_id=sched.id,
            schedule_run_id=run.id,
            total_items=data.get("totalTask"),
            poll_url=data.get("pollUrl"),
            callback_url=data.get("callbackUrl"),
            raw_request_json=payload,
            raw_response_json=data,
        )
        db.add(t)
        db.flush()
        for st in data.get("subTaskList", []):
            db.add(SubTask(
                task_id=t.id,
                subtask_id=st["subTaskId"],
                platform=st.get("platform"),
                mode=st.get("mode"),
                prompt=st.get("prompt"),
                status=st.get("status", "pending"),
            ))
        run.task_id = t.id
        run.status = "success"
        run.finished_at = _now()
        db.commit()
        return run.id
    except (MolizhishuError, RuntimeError, Exception) as e:
        run.status = "failed"
        run.error_message = str(e)[:1000]
        run.finished_at = _now()
        db.commit()
        return run.id
    finally:
        db.close()


async def run_schedule_async(schedule_id: int, slot_index: int, trigger_type: str) -> int | None:
    return await asyncio.get_event_loop().run_in_executor(None, run_schedule, schedule_id, slot_index, trigger_type)
```

- [ ] **Step 3:Commit**

```bash
git add backend/
git commit -m "feat(scheduler): run_schedule core with cooldown, override, async wrapper"
```

---

### Task 8:APScheduler 集成 + lifespan startup

**Files:**
- Modify: `backend/app/main.py`(挂 lifespan + 加载调度)

- [ ] **Step 1:替换 `backend/app/main.py`**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models.schedule import Schedule, ScheduleSlot
from app.services.scheduler import run_schedule_async


def _reload_jobs(scheduler: AsyncIOScheduler):
    scheduler.remove_all_jobs()
    with SessionLocal() as db:
        rows = db.execute(
            select(Schedule, ScheduleSlot)
            .join(ScheduleSlot, ScheduleSlot.schedule_id == Schedule.id)
            .where(Schedule.status == "enabled")
        ).all()
        for sched, slot in rows:
            scheduler.add_job(
                run_schedule_async,
                id=f"schedule-{sched.id}-{slot.slot_index}",
                trigger=CronTrigger(hour=slot.hour, minute=slot.minute, timezone="Asia/Shanghai"),
                args=[sched.id, slot.slot_index, "cron"],
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=600,
            )


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    _reload_jobs(scheduler)
    scheduler.start()
    app.state.scheduler = scheduler
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(title="windx-backend", lifespan=lifespan)
settings = get_settings()
app.mount("/static", StaticFiles(directory=settings.logo_storage_dir, check_dir=False), name="static")


@app.get("/health")
def health():
    return {"ok": True}


# 路由
from app.api import customers, projects, auth
app.include_router(customers.router)
app.include_router(projects.router)
app.include_router(auth.router)
```

- [ ] **Step 2:本地验证 lifespan**

```bash
uvicorn app.main:app --reload --port 18083 &
sleep 2
curl http://localhost:18083/health
# Expected: {"ok":true},日志可见 "Scheduler started"
```

- [ ] **Step 3:Commit**

```bash
git add backend/
git commit -m "feat(scheduler): AsyncIOScheduler lifespan with reload from DB"
```

---

### Task 9:调度 CRUD API + 触发 + 执行历史

**Files:**
- Create: `backend/app/api/schedules.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1:写测试 `backend/tests/test_schedule_api.py`**

```python
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from jose import jwt
import asyncio
from app.main import app
from app.db import Base, get_db
from app.config import get_settings
from app.models.customer import AdminUser

settings = get_settings()
test_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)


def override_db():
    db = TestSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_db


@pytest.fixture(autouse=True)
def _setup_db():
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _token():
    def _mk():
        with TestSessionLocal() as db:
            u = AdminUser(username="root", password_hash="x", role="super_admin", status="active")
            db.add(u); db.commit(); db.refresh(u)
            return u.id
    uid = await asyncio.get_event_loop().run_in_executor(None, _mk)
    return jwt.encode({"sub": str(uid)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


async def _customer_and_project(token):
    h = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        cid = (await c.post("/api/customers", json={"name": "C", "code": "C1"}, headers=h)).json()["id"]
        pid = (await c.post(f"/api/customers/{cid}/projects", json={"name": "P", "code": "P1"}, headers=h)).json()["id"]
        await c.put(f"/api/projects/{pid}/prompts", json={"prompts": ["q1"]}, headers=h)
        await c.put(f"/api/projects/{pid}/platforms", json={"platforms": [{"platform": "deepseek", "mode": "search", "screenshot": 0}]}, headers=h)
    return cid, pid


@pytest.mark.asyncio
async def test_schedule_crud_and_status(client):
    token = await _token()
    h = {"Authorization": f"Bearer {token}"}
    _, pid = await _customer_and_project(token)

    r = await client.post("/api/schedules", json={
        "name": "S1", "project_id": pid, "slots": [{"slot_index": 1, "hour": 9, "minute": 0}]
    }, headers=h)
    assert r.status_code == 200
    sid = r.json()["id"]

    r = await client.get(f"/api/schedules/{sid}", headers=h)
    assert r.status_code == 200
    assert r.json()["slots"][0]["hour"] == 9

    r = await client.put(f"/api/schedules/{sid}/status", json={"status": "disabled"}, headers=h)
    assert r.status_code == 200
    assert r.json()["status"] == "disabled"

    r = await client.delete(f"/api/schedules/{sid}", headers=h)
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_schedule_invalid_slot_count(client):
    token = await _token()
    h = {"Authorization": f"Bearer {token}"}
    _, pid = await _customer_and_project(token)
    r = await client.post("/api/schedules", json={"name": "S", "project_id": pid, "slots": []}, headers=h)
    assert r.status_code == 422  # min_length=1
    r = await client.post("/api/schedules", json={
        "name": "S", "project_id": pid,
        "slots": [
            {"slot_index": 1, "hour": 9, "minute": 0},
            {"slot_index": 2, "hour": 18, "minute": 0},
            {"slot_index": 3, "hour": 19, "minute": 0},  # max 2
        ]
    }, headers=h)
    assert r.status_code == 422
```

- [ ] **Step 2:写 `backend/app/api/schedules.py`**

```python
from datetime import datetime
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_super_admin
from app.models.customer import AdminUser
from app.models.project import Project
from app.models.schedule import Schedule, ScheduleSlot, ScheduleRun
from app.schemas.schedule import (
    ScheduleCreate, ScheduleUpdate, ScheduleStatusUpdate, ScheduleOut, ScheduleListOut, TriggerOut,
)
from app.schemas.schedule_run import ScheduleRunOut, ScheduleRunListOut
from app.services.scheduler import run_schedule_async

router = APIRouter(tags=["schedules"])


def _to_out(s: Schedule, db: Session) -> ScheduleOut:
    slots = [SlotOut(id=sl.id, slot_index=sl.slot_index, hour=sl.hour, minute=sl.minute)
             for sl in sorted(db.scalars(select(ScheduleSlot).where(ScheduleSlot.schedule_id == s.id)).all(), key=lambda x: x.slot_index)]
    return ScheduleOut(
        id=s.id, name=s.name, project_id=s.project_id, customer_id=s.customer_id,
        status=s.status, max_daily_runs=s.max_daily_runs,
        region_code_override=s.region_code_override,
        slots=slots,
        prompts_override=s.prompts_override_json,
        keywords_override=s.keywords_override_json,
        platforms_override=s.platforms_override_json,
        created_at=s.created_at, updated_at=s.updated_at,
    )


@router.post("/api/schedules", response_model=ScheduleOut)
def create_schedule(
    payload: ScheduleCreate,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(require_super_admin),
):
    project = db.get(Project, payload.project_id)
    if not project:
        raise HTTPException(404, "project not found")
    s = Schedule(
        name=payload.name, project_id=payload.project_id, customer_id=project.customer_id,
        prompts_override_json=payload.prompts_override,
        keywords_override_json=payload.keywords_override,
        platforms_override_json=payload.platforms_override,
        region_code_override=payload.region_code_override,
        created_by=user.id, status="enabled",
    )
    db.add(s); db.flush()
    for slot in payload.slots:
        db.add(ScheduleSlot(schedule_id=s.id, slot_index=slot.slot_index, hour=slot.hour, minute=slot.minute))
    db.commit()
    db.refresh(s)
    return _to_out(s, db)


@router.get("/api/schedules", response_model=ScheduleListOut)
def list_schedules(
    page: int = 1, size: int = 20,
    customer_id: int | None = None, project_id: int | None = None, status: str | None = None,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    page, size = max(1, page), min(100, max(1, size))
    stmt = select(Schedule)
    if customer_id:
        stmt = stmt.where(Schedule.customer_id == customer_id)
    if project_id:
        stmt = stmt.where(Schedule.project_id == project_id)
    if status:
        stmt = stmt.where(Schedule.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Schedule.id.desc()).offset((page - 1) * size).limit(size)).all()
    return ScheduleListOut(items=[_to_out(s, db) for s in items], total=total, page=page, size=size)


@router.get("/api/schedules/{schedule_id}", response_model=ScheduleOut)
def get_schedule(schedule_id: int, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    s = db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "not found")
    return _to_out(s, db)


@router.put("/api/schedules/{schedule_id}", response_model=ScheduleOut)
def update_schedule(
    schedule_id: int,
    payload: ScheduleUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    s = db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "not found")
    data = payload.model_dump(exclude_unset=True)
    slots_data = data.pop("slots", None)
    for k, v in data.items():
        setattr(s, k, v)
    if slots_data is not None:
        db.query(ScheduleSlot).filter(ScheduleSlot.schedule_id == s.id).delete()
        for slot in slots_data:
            db.add(ScheduleSlot(schedule_id=s.id, **slot))
    db.commit()
    db.refresh(s)
    return _to_out(s, db)


@router.delete("/api/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    s = db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "not found")
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.put("/api/schedules/{schedule_id}/status", response_model=ScheduleOut)
def update_schedule_status(
    schedule_id: int, payload: ScheduleStatusUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    s = db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "not found")
    s.status = payload.status
    db.commit()
    db.refresh(s)
    return _to_out(s, db)


@router.post("/api/schedules/{schedule_id}/trigger", response_model=TriggerOut)
def trigger_schedule(
    schedule_id: int,
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    s = db.get(Schedule, schedule_id)
    if not s:
        raise HTTPException(404, "not found")
    from app.db import SessionLocal
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    bucket = now.minute // 5
    cooldown = f"schedule-{s.id}-slot-1-{now.strftime('%Y%m%d%H')}{bucket}"
    run = ScheduleRun(schedule_id=s.id, slot_index=1, trigger_type="manual",
                      triggered_at=now, status="queued", cooldown_key=cooldown)
    try:
        db.add(run); db.commit(); db.refresh(run)
    except Exception:
        db.rollback()
        existing = db.query(ScheduleRun).filter(ScheduleRun.cooldown_key == cooldown).first()
        if existing:
            return TriggerOut(run_id=existing.id)
        raise HTTPException(500, "cooldown conflict")
    background.add_task(run_schedule_async, s.id, 1, "manual")
    return TriggerOut(run_id=run.id)


@router.get("/api/schedules/{schedule_id}/runs", response_model=ScheduleRunListOut)
def list_schedule_runs(
    schedule_id: int, page: int = 1, size: int = 20,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    page, size = max(1, page), min(100, max(1, size))
    stmt = select(ScheduleRun).where(ScheduleRun.schedule_id == schedule_id).order_by(ScheduleRun.id.desc())
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
    return ScheduleRunListOut(items=[ScheduleRunOut.model_validate(r) for r in items], total=total, page=page, size=size)


@router.get("/api/schedules/runs/{run_id}", response_model=ScheduleRunOut)
def get_schedule_run(run_id: int, db: Session = Depends(get_db), _: AdminUser = Depends(require_super_admin)):
    r = db.get(ScheduleRun, run_id)
    if not r:
        raise HTTPException(404, "not found")
    return ScheduleRunOut.model_validate(r)
```

- [ ] **Step 3:挂载**

```python
# main.py 末尾追加
from app.api import schedules
app.include_router(schedules.router)
```

- [ ] **Step 4:运行测试**

```bash
pytest tests/test_schedule_api.py -v
# Expected: 2 passed
```

- [ ] **Step 5:Commit**

```bash
git add backend/
git commit -m "feat(schedules): CRUD + status + trigger + runs APIs"
```

---

## Phase 4:任务列表扩展

### Task 10:任务列表增加 customer_id/project_id 过滤 + 项目下任务 API

**Files:**
- Modify: `backend/app/api/tasks.py`(在现有基础上增加过滤;若文件不存在则创建)
- Create: `backend/app/api/project_tasks.py`(项目下任务)

- [ ] **Step 1:实现 `backend/app/api/tasks.py`(示例,沿用现有模型)**

```python
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.models.customer import AdminUser
from app.models.task import Task

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks")
def list_tasks(
    page: int = 1, size: int = 20,
    status: str | None = None,
    customer_id: int | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    page, size = max(1, page), min(100, max(1, size))
    stmt = select(Task)
    if user.role == "customer_admin":
        stmt = stmt.where(Task.customer_id == user.customer_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if customer_id is not None:
        stmt = stmt.where(Task.customer_id == customer_id)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Task.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {"items": [
        {
            "task_id": t.task_id,
            "status": t.status,
            "total_items": t.total_items,
            "completed_items": t.completed_items,
            "failed_items": t.failed_items,
            "customer_id": t.customer_id,
            "project_id": t.project_id,
            "schedule_id": t.schedule_id,
            "schedule_run_id": t.schedule_run_id,
            "created_local_at": t.created_local_at.isoformat() if t.created_local_at else None,
        } for t in items
    ], "total": total, "page": page, "size": size}


@router.get("/api/projects/{project_id}/tasks")
def list_project_tasks(
    project_id: int,
    page: int = 1, size: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    if user.role == "customer_admin":
        from app.models.project import Project
        p = db.get(Project, project_id)
        if not p or p.customer_id != user.customer_id:
            from fastapi import HTTPException
            raise HTTPException(403, "forbidden")
    page, size = max(1, page), min(100, max(1, size))
    stmt = select(Task).where(Task.project_id == project_id)
    if status:
        stmt = stmt.where(Task.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.order_by(Task.id.desc()).offset((page - 1) * size).limit(size)).all()
    return {"items": [
        {
            "task_id": t.task_id, "status": t.status, "total_items": t.total_items,
            "completed_items": t.completed_items, "failed_items": t.failed_items,
            "schedule_id": t.schedule_id, "schedule_run_id": t.schedule_run_id,
            "created_local_at": t.created_local_at.isoformat() if t.created_local_at else None,
        } for t in items
    ], "total": total, "page": page, "size": size}
```

- [ ] **Step 2:挂载到 `backend/app/main.py`**

```python
from app.api import tasks
app.include_router(tasks.router)
```

- [ ] **Step 3:Commit**

```bash
git add backend/
git commit -m "feat(tasks): add customer/project filters and project tasks endpoint"
```

---

## Phase 5:调度器集成测试

### Task 11:`run_schedule` 集成测试(用 freezegun)

**Files:**
- Create: `backend/tests/test_scheduler.py`

- [ ] **Step 1:写测试 `backend/tests/test_scheduler.py`**

```python
import asyncio
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db import Base, SessionLocal
from app.models.customer import AdminUser, Customer
from app.models.project import Project, ProjectPrompt, ProjectPlatform
from app.models.schedule import Schedule, ScheduleSlot, ScheduleRun
from app.config import get_settings
from app.services.scheduler import run_schedule_async, _cooldown_key
from datetime import datetime
from zoneinfo import ZoneInfo

settings = get_settings()
test_engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
TestSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)
Base.metadata.create_all(test_engine)


@pytest.fixture(autouse=True)
def _override_session():
    from app.services import scheduler
    scheduler.SessionLocal = TestSession
    yield


def _setup_env():
    with TestSession() as db:
        u = AdminUser(username="root", password_hash="x", role="super_admin", status="active")
        c = Customer(name="C", code="C1")
        db.add_all([u, c]); db.flush()
        p = Project(customer_id=c.id, name="P", code="P1")
        db.add(p); db.flush()
        db.add_all([
            ProjectPrompt(project_id=p.id, prompt="q1", sort=0),
            ProjectPlatform(project_id=p.id, platform="deepseek", mode="search", screenshot=0, sort=0),
        ])
        s = Schedule(name="S1", project_id=p.id, customer_id=c.id, status="enabled")
        db.add(s); db.flush()
        db.add(ScheduleSlot(schedule_id=s.id, slot_index=1, hour=9, minute=0))
        db.commit()
        return s.id


@pytest.mark.asyncio
async def test_run_schedule_happy_path():
    sid = _setup_env()
    mock_resp = {"taskId": "abc", "status": "pending", "totalTask": 1, "pollUrl": "/x",
                 "callbackUrl": None, "subTaskList": [{"subTaskId": "s1", "platform": "deepseek", "mode": "search", "prompt": "q1", "status": "pending"}]}
    with patch("app.services.scheduler.MolizhishuClient") as MC:
        MC.return_value.submit_task = AsyncMock(return_value=mock_resp)
        run_id = await run_schedule_async(sid, 1, "cron")
    assert run_id is not None
    with TestSession() as db:
        r = db.get(ScheduleRun, run_id)
        assert r.status == "success"
        assert r.task_id is not None


@pytest.mark.asyncio
async def test_run_schedule_empty_prompts_skips_remote():
    with TestSession() as db:
        u = AdminUser(username="root2", password_hash="x", role="super_admin", status="active")
        c = Customer(name="C2", code="C2"); db.add_all([u, c]); db.flush()
        p = Project(customer_id=c.id, name="P2", code="P2"); db.add(p); db.flush()
        s = Schedule(name="S2", project_id=p.id, customer_id=c.id, status="enabled"); db.add(s); db.flush()
        db.add(ScheduleSlot(schedule_id=s.id, slot_index=1, hour=9, minute=0)); db.commit(); sid = s.id
    with patch("app.services.scheduler.MolizhishuClient") as MC:
        MC.return_value.submit_task = AsyncMock()
        run_id = await run_schedule_async(sid, 1, "cron")
    with TestSession() as db:
        r = db.get(ScheduleRun, run_id)
        assert r.status == "failed"
        assert "prompts" in r.error_message.lower()
        MC.return_value.submit_task.assert_not_called()


@pytest.mark.asyncio
async def test_cooldown_within_5min():
    sid = _setup_env()
    mock_resp = {"taskId": "x1", "status": "pending", "totalTask": 1, "subTaskList": []}
    with patch("app.services.scheduler.MolizhishuClient") as MC:
        MC.return_value.submit_task = AsyncMock(return_value=mock_resp)
        r1 = await run_schedule_async(sid, 1, "manual")
        r2 = await run_schedule_async(sid, 1, "manual")  # 同 5 分钟
    with TestSession() as db:
        skipped = db.query(ScheduleRun).filter(ScheduleRun.status == "skipped").count()
        assert skipped >= 1


def test_cooldown_key_bucket():
    t = datetime(2026, 8, 7, 9, 3, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert _cooldown_key(1, 1, t) == "schedule-1-slot-1-20260807090"  # bucket 0
    t2 = datetime(2026, 8, 7, 9, 7, tzinfo=ZoneInfo("Asia/Shanghai"))
    assert _cooldown_key(1, 1, t2) == "schedule-1-slot-1-20260807091"  # bucket 1
```

- [ ] **Step 2:运行测试**

```bash
cd backend
pytest tests/test_scheduler.py -v
# Expected: 4 passed
```

- [ ] **Step 3:Commit**

```bash
git add backend/
git commit -m "test(scheduler): integration tests for run_schedule and cooldown"
```

---

## Phase 6:前端

### Task 12:Vite + React + Ant Design 脚手架

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`

- [ ] **Step 1:写 `frontend/package.json`**

```json
{
  "name": "windx-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2",
    "react-dom": "^18.2",
    "react-router-dom": "^6.22",
    "antd": "^5.15",
    "@ant-design/icons": "^5.3",
    "axios": "^1.6",
    "dayjs": "^1.11"
  },
  "devDependencies": {
    "@types/react": "^18.2",
    "@types/react-dom": "^18.2",
    "@vitejs/plugin-react": "^4.2",
    "typescript": "^5.3",
    "vite": "^5.1"
  }
}
```

- [ ] **Step 2:写 `frontend/vite.config.ts`**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy: { "/api": "http://localhost:18083", "/static": "http://localhost:18083" } },
});
```

- [ ] **Step 3:写 `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020", "lib": ["ES2020", "DOM"], "module": "ESNext",
    "moduleResolution": "Bundler", "jsx": "react-jsx",
    "strict": true, "skipLibCheck": true,
    "resolveJsonModule": true, "isolatedModules": true, "esModuleInterop": true
  },
  "include": ["src"]
}
```

- [ ] **Step 4:写 `frontend/index.html`**

```html
<!doctype html>
<html lang="zh-CN">
  <head><meta charset="UTF-8" /><title>windx 管理后台</title></head>
  <body><div id="root"></div><script type="module" src="/src/main.tsx"></script></body>
</html>
```

- [ ] **Step 5:写 `frontend/src/main.tsx`**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import App from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ConfigProvider locale={zhCN}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ConfigProvider>
  </React.StrictMode>
);
```

- [ ] **Step 6:写 `frontend/src/App.tsx`**

```tsx
import { RouterProvider, createBrowserRouter, Navigate } from "react-router-dom";
import { AuthProvider, RequireSuperAdmin } from "./auth/AuthProvider";
import Login from "./pages/Login";
import CustomersList from "./pages/Customers/List";
import ProjectsList from "./pages/Projects/List";
import ProjectDetail from "./pages/Projects/Detail";
import SchedulesList from "./pages/Schedules/List";
import ScheduleEdit from "./pages/Schedules/Edit";
import ScheduleRuns from "./pages/Schedules/Runs";
import ProjectTasksList from "./pages/ProjectTasks/List";

const router = createBrowserRouter([
  { path: "/login", element: <Login /> },
  { path: "/", element: <Navigate to="/admin/customers" replace /> },
  { path: "/admin/customers", element: <RequireSuperAdmin><CustomersList /></RequireSuperAdmin> },
  { path: "/admin/projects", element: <RequireSuperAdmin><ProjectsList /></RequireSuperAdmin> },
  { path: "/admin/projects/:id", element: <RequireSuperAdmin><ProjectDetail /></RequireSuperAdmin> },
  { path: "/admin/projects/:id/tasks", element: <RequireSuperAdmin><ProjectTasksList /></RequireSuperAdmin> },
  { path: "/admin/schedules", element: <RequireSuperAdmin><SchedulesList /></RequireSuperAdmin> },
  { path: "/admin/schedules/new", element: <RequireSuperAdmin><ScheduleEdit /></RequireSuperAdmin> },
  { path: "/admin/schedules/:id/edit", element: <RequireSuperAdmin><ScheduleEdit /></RequireSuperAdmin> },
  { path: "/admin/schedules/:id/runs", element: <RequireSuperAdmin><ScheduleRuns /></RequireSuperAdmin> },
]);

export default function App() {
  return <AuthProvider><RouterProvider router={router} /></AuthProvider>;
}
```

- [ ] **Step 7:写 `frontend/src/auth/AuthProvider.tsx`**

```tsx
import { createContext, useContext, useEffect, useState } from "react";
import axios from "axios";
import { Navigate } from "react-router-dom";

interface User { id: number; username: string; role: "super_admin" | "customer_admin"; customer_id: number | null }
interface AuthCtx { user: User | null; setUser: (u: User | null) => void }
const Ctx = createContext<AuthCtx>({ user: null, setUser: () => {} });

axios.interceptors.request.use((c) => {
  const t = localStorage.getItem("token");
  if (t) c.headers.Authorization = `Bearer ${t}`;
  return c;
});
axios.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem("token");
      window.location.href = "/login";
    }
    return Promise.reject(err);
  }
);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    if (!localStorage.getItem("token")) return;
    axios.get("/api/auth/me").then((r) => setUser(r.data)).catch(() => setUser(null));
  }, []);
  return <Ctx.Provider value={{ user, setUser }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  return useContext(Ctx);
}

export function RequireSuperAdmin({ children }: { children: React.ReactElement }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (user.role !== "super_admin") return <Navigate to="/login" replace />;
  return children;
}
```

- [ ] **Step 8:写 `frontend/src/pages/Login.tsx`**

```tsx
import { Form, Input, Button, Card, message } from "antd";
import axios from "axios";
import { useAuth } from "../auth/AuthProvider";
import { useNavigate } from "react-router-dom";

export default function Login() {
  const { setUser } = useAuth();
  const nav = useNavigate();
  const onFinish = async (v: { username: string; password: string }) => {
    try {
      const r = await axios.post("/api/auth/login", v);
      localStorage.setItem("token", r.data.token);
      const me = await axios.get("/api/auth/me");
      setUser(me.data);
      nav("/admin/customers");
    } catch {
      message.error("登录失败");
    }
  };
  return (
    <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: "100vh" }}>
      <Card title="windx 管理后台" style={{ width: 360 }}>
        <Form onFinish={onFinish} layout="vertical">
          <Form.Item name="username" label="用户名" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="password" label="密码" rules={[{ required: true }]}><Input.Password /></Form.Item>
          <Button type="primary" htmlType="submit" block>登录</Button>
        </Form>
      </Card>
    </div>
  );
}
```

- [ ] **Step 9:本地启动**

```bash
cd frontend
npm install
npm run dev
# 浏览器打开 http://localhost:5173 可见登录页
```

- [ ] **Step 10:Commit**

```bash
git add frontend/
git commit -m "feat(frontend): scaffold vite + react + antd + auth provider"
```

---

### Task 13:客户管理页面

**Files:**
- Create: `frontend/src/api/customers.ts`
- Create: `frontend/src/pages/Customers/List.tsx`

- [ ] **Step 1:写 `frontend/src/api/customers.ts`**

```ts
import axios from "axios";

export interface Customer { id: number; name: string; code: string; logo_url: string | null; status: string }
export const listCustomers = (params: { page?: number; size?: number }) =>
  axios.get<{ items: Customer[]; total: number }>("/api/customers", { params });
export const createCustomer = (data: Partial<Customer>) => axios.post<Customer>("/api/customers", data);
export const updateCustomer = (id: number, data: Partial<Customer>) => axios.put<Customer>(`/api/customers/${id}`, data);
export const uploadLogo = (id: number, file: File) => {
  const fd = new FormData(); fd.append("file", file);
  return axios.post<Customer>(`/api/customers/${id}/logo`, fd, { headers: { "Content-Type": "multipart/form-data" } });
};
export const deleteCustomer = (id: number) => axios.delete(`/api/customers/${id}`);
```

- [ ] **Step 2:写 `frontend/src/pages/Customers/List.tsx`**

```tsx
import { Table, Button, Space, Modal, Form, Input, Select, Upload, message, Image } from "antd";
import { PlusOutlined, UploadOutlined } from "@ant-design/icons";
import { useEffect, useState } from "react";
import { listCustomers, createCustomer, updateCustomer, uploadLogo, deleteCustomer, Customer } from "../../api/customers";

export default function CustomersList() {
  const [items, setItems] = useState<Customer[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Customer | null>(null);
  const [form] = Form.useForm();

  const load = async () => {
    const r = await listCustomers({ page, size: 20 });
    setItems(r.data.items); setTotal(r.data.total);
  };
  useEffect(() => { load(); }, [page]);

  const onSave = async () => {
    const v = await form.validateFields();
    if (editing && editing.id) {
      await updateCustomer(editing.id, v);
      message.success("已更新");
    } else {
      await createCustomer(v);
      message.success("已创建");
    }
    setEditing(null); form.resetFields(); load();
  };

  const onUpload = async (id: number, file: File) => {
    await uploadLogo(id, file);
    message.success("logo 已上传");
    load();
    return false;
  };

  const onDelete = async (id: number) => {
    Modal.confirm({
      title: "确认删除?", onOk: async () => { await deleteCustomer(id); load(); },
    });
  };

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditing({} as Customer); form.resetFields(); }}>新建客户</Button>
      </Space>
      <Table rowKey="id" dataSource={items} pagination={{ current: page, total, onChange: setPage }}
        columns={[
          { title: "Logo", dataIndex: "logo_url", render: (u) => u ? <Image src={u} width={40} /> : "-" },
          { title: "名称", dataIndex: "name" },
          { title: "编码", dataIndex: "code" },
          { title: "状态", dataIndex: "status", render: (s) => s === "active" ? "启用" : "停用" },
          { title: "操作", render: (_, r) => (
            <Space>
              <Upload beforeUpload={(f) => { onUpload(r.id, f); return false; }} showUploadList={false} accept="image/png,image/jpeg,image/webp">
                <Button size="small" icon={<UploadOutlined />}>上传 logo</Button>
              </Upload>
              <Button size="small" onClick={() => { setEditing(r); form.setFieldsValue(r); }}>编辑</Button>
              <Button size="small" danger onClick={() => onDelete(r.id)}>删除</Button>
            </Space>
          ) },
        ]} />
      <Modal open={!!editing} title={editing?.id ? "编辑客户" : "新建客户"} onCancel={() => setEditing(null)} onOk={onSave} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="code" label="编码" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="contact" label="联系人"><Input /></Form.Item>
          <Form.Item name="status" label="状态" initialValue="active">
            <Select options={[{ value: "active", label: "启用" }, { value: "disabled", label: "停用" }]} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
```

- [ ] **Step 3:验证**

```bash
cd frontend && npm run dev
# 浏览器进入 /admin/customers,确认能列/新建/上传 logo
```

- [ ] **Step 4:Commit**

```bash
git add frontend/
git commit -m "feat(frontend): customers list page"
```

---

### Task 14:项目列表 + 项目详情(4 tab)

**Files:**
- Create: `frontend/src/api/projects.ts`
- Create: `frontend/src/pages/Projects/List.tsx`
- Create: `frontend/src/pages/Projects/Detail.tsx`

- [ ] **Step 1:写 `frontend/src/api/projects.ts`**

```ts
import axios from "axios";
export interface Project { id: number; customer_id: number; name: string; code: string; status: string }
export interface ProjectDetail extends Project { prompts: string[]; keywords: string[]; platforms: Array<{ platform: string; mode: string; screenshot: number }> }

export const listProjects = (params: { customer_id?: number; page?: number }) => axios.get<{ items: Project[]; total: number }>("/api/projects", { params });
export const getProject = (id: number) => axios.get<ProjectDetail>(`/api/projects/${id}`);
export const createProject = (customer_id: number, data: Partial<Project>) => axios.post(`/api/customers/${customer_id}/projects`, data);
export const putPrompts = (id: number, prompts: string[]) => axios.put(`/api/projects/${id}/prompts`, { prompts });
export const putKeywords = (id: number, keywords: string[]) => axios.put(`/api/projects/${id}/keywords`, { keywords });
export const putPlatforms = (id: number, platforms: any[]) => axios.put(`/api/projects/${id}/platforms`, { platforms });
```

- [ ] **Step 2:写 `frontend/src/pages/Projects/List.tsx`**

```tsx
import { Table, Button, Modal, Form, Input, Select, Space, message } from "antd";
import { useEffect, useState } from "react";
import { listProjects, createProject, Project } from "../../api/projects";
import { listCustomers, Customer } from "../../api/customers";
import { Link } from "react-router-dom";

export default function ProjectsList() {
  const [items, setItems] = useState<Project[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();

  const load = async () => {
    const r = await listProjects({ page });
    setItems(r.data.items); setTotal(r.data.total);
  };
  useEffect(() => { load(); listCustomers({ size: 100 }).then((r) => setCustomers(r.data.items)); }, [page]);

  const onCreate = async () => {
    const v = await form.validateFields();
    await createProject(v.customer_id, { name: v.name, code: v.code });
    message.success("已创建"); setOpen(false); form.resetFields(); load();
  };

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={() => setOpen(true)}>新建项目</Button>
      </Space>
      <Table rowKey="id" dataSource={items} pagination={{ current: page, total, onChange: setPage }}
        columns={[
          { title: "ID", dataIndex: "id" },
          { title: "所属客户", dataIndex: "customer_id", render: (id) => customers.find((c) => c.id === id)?.name ?? id },
          { title: "名称", dataIndex: "name" },
          { title: "编码", dataIndex: "code" },
          { title: "操作", render: (_, r) => <Link to={`/admin/projects/${r.id}`}>详情</Link> },
        ]} />
      <Modal open={open} title="新建项目" onCancel={() => setOpen(false)} onOk={onCreate} destroyOnClose>
        <Form form={form} layout="vertical">
          <Form.Item name="customer_id" label="客户" rules={[{ required: true }]}>
            <Select options={customers.map((c) => ({ value: c.id, label: c.name }))} />
          </Form.Item>
          <Form.Item name="name" label="名称" rules={[{ required: true }]}><Input /></Form.Item>
          <Form.Item name="code" label="编码" rules={[{ required: true }]}><Input /></Form.Item>
        </Form>
      </Modal>
    </>
  );
}
```

- [ ] **Step 3:写 `frontend/src/pages/Projects/Detail.tsx`**

```tsx
import { Tabs, Input, Button, Space, Select, message, Card } from "antd";
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getProject, putPrompts, putKeywords, putPlatforms, ProjectDetail } from "../../api/projects";

const PLATFORMS = ["deepseek", "doubao", "yuanbao", "kimi", "qianwen", "quark", "baiduai", "weibo_zhisou", "wenxinyiyan", "doubao_mobile"];
const MODES = ["standard", "reasoning", "search", "reasoning_search"];

export default function ProjectDetail() {
  const { id } = useParams();
  const pid = Number(id);
  const [data, setData] = useState<ProjectDetail | null>(null);
  const [prompts, setPrompts] = useState<string[]>([]);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [platforms, setPlatforms] = useState<any[]>([]);

  const load = async () => {
    const r = await getProject(pid);
    setData(r.data);
    setPrompts(r.data.prompts);
    setKeywords(r.data.keywords);
    setPlatforms(r.data.platforms);
  };
  useEffect(() => { load(); }, [pid]);

  if (!data) return null;

  return (
    <Card title={`${data.name} (${data.code})`} extra={<Link to={`/admin/projects/${pid}/tasks`}>查看监控任务</Link>}>
      <Tabs items={[
        {
          key: "prompts", label: "问题(prompts)",
          children: <ListEditor items={prompts} onChange={setPrompts}
            onSave={async () => { await putPrompts(pid, prompts); message.success("已保存"); }}
            addLabel="新增问题" placeholder="输入监控问题" />,
        },
        {
          key: "keywords", label: "关键词(keywords)",
          children: <ListEditor items={keywords} onChange={setKeywords}
            onSave={async () => { await putKeywords(pid, keywords); message.success("已保存"); }}
            addLabel="新增关键词" placeholder="输入关键词" />,
        },
        {
          key: "platforms", label: "平台(platforms)",
          children: <PlatformsEditor items={platforms} onChange={setPlatforms}
            onSave={async () => { await putPlatforms(pid, platforms); message.success("已保存"); }} />,
        },
      ]} />
    </Card>
  );
}

function ListEditor({ items, onChange, onSave, addLabel, placeholder }: any) {
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {items.map((it: string, i: number) => (
        <Space key={i}>
          <Input value={it} placeholder={placeholder} onChange={(e) => {
            const next = [...items]; next[i] = e.target.value; onChange(next);
          }} />
          <Button danger onClick={() => onChange(items.filter((_: any, j: number) => j !== i))}>删除</Button>
        </Space>
      ))}
      <Space>
        <Button onClick={() => onChange([...items, ""])}>{addLabel}</Button>
        <Button type="primary" onClick={onSave}>保存</Button>
      </Space>
    </Space>
  );
}

function PlatformsEditor({ items, onChange, onSave }: any) {
  return (
    <Space direction="vertical" style={{ width: "100%" }}>
      {items.map((it: any, i: number) => (
        <Space key={i}>
          <Select value={it.platform} options={PLATFORMS.map((p) => ({ value: p, label: p }))} onChange={(v) => {
            const next = [...items]; next[i] = { ...it, platform: v }; onChange(next);
          }} style={{ width: 140 }} />
          <Select value={it.mode} options={MODES.map((m) => ({ value: m, label: m }))} onChange={(v) => {
            const next = [...items]; next[i] = { ...it, mode: v }; onChange(next);
          }} style={{ width: 140 }} />
          <Select value={it.screenshot} options={[{ value: 0, label: "不截图" }, { value: 1, label: "截图" }, { value: 2, label: "提及截图" }]} onChange={(v) => {
            const next = [...items]; next[i] = { ...it, screenshot: v }; onChange(next);
          }} style={{ width: 120 }} />
          <Button danger onClick={() => onChange(items.filter((_: any, j: number) => j !== i))}>删除</Button>
        </Space>
      ))}
      <Space>
        <Button onClick={() => onChange([...items, { platform: "deepseek", mode: "search", screenshot: 0 }])}>新增平台</Button>
        <Button type="primary" onClick={onSave}>保存</Button>
      </Space>
    </Space>
  );
}
```

- [ ] **Step 4:Commit**

```bash
git add frontend/
git commit -m "feat(frontend): projects list and 4-tab detail"
```

---

### Task 15:调度管理(列表 / 新建编辑 / 执行历史)+ 项目下任务

**Files:**
- Create: `frontend/src/api/schedules.ts`
- Create: `frontend/src/pages/Schedules/List.tsx`
- Create: `frontend/src/pages/Schedules/Edit.tsx`
- Create: `frontend/src/pages/Schedules/Runs.tsx`
- Create: `frontend/src/pages/ProjectTasks/List.tsx`

- [ ] **Step 1:写 `frontend/src/api/schedules.ts`**

```ts
import axios from "axios";
export interface Slot { slot_index: 1 | 2; hour: number; minute: number }
export interface Schedule {
  id: number; name: string; project_id: number; customer_id: number;
  status: "enabled" | "disabled"; slots: Slot[];
  prompts_override: string[] | null; keywords_override: string[] | null;
  platforms_override: any[] | null; region_code_override: string | null;
}
export const listSchedules = (params: any) => axios.get<{ items: Schedule[]; total: number }>("/api/schedules", { params });
export const getSchedule = (id: number) => axios.get<Schedule>(`/api/schedules/${id}`);
export const createSchedule = (data: any) => axios.post<Schedule>("/api/schedules", data);
export const updateSchedule = (id: number, data: any) => axios.put<Schedule>(`/api/schedules/${id}`, data);
export const updateStatus = (id: number, status: "enabled" | "disabled") => axios.put(`/api/schedules/${id}/status`, { status });
export const trigger = (id: number) => axios.post<{ run_id: number }>(`/api/schedules/${id}/trigger`);
export const deleteSchedule = (id: number) => axios.delete(`/api/schedules/${id}`);
export const listRuns = (id: number, params: any) => axios.get<{ items: any[]; total: number }>(`/api/schedules/${id}/runs`, { params });
```

- [ ] **Step 2:写 `frontend/src/pages/Schedules/List.tsx`**

```tsx
import { Table, Button, Space, Modal, Switch, message, Tag } from "antd";
import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { listSchedules, updateStatus, trigger, deleteSchedule, Schedule } from "../../api/schedules";

export default function SchedulesList() {
  const [items, setItems] = useState<Schedule[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);

  const load = async () => {
    const r = await listSchedules({ page });
    setItems(r.data.items); setTotal(r.data.total);
  };
  useEffect(() => { load(); }, [page]);

  return (
    <>
      <Space style={{ marginBottom: 16 }}>
        <Link to="/admin/schedules/new"><Button type="primary">新建调度</Button></Link>
      </Space>
      <Table rowKey="id" dataSource={items} pagination={{ current: page, total, onChange: setPage }}
        columns={[
          { title: "ID", dataIndex: "id" },
          { title: "名称", dataIndex: "name" },
          { title: "时间点", render: (_, r) => r.slots.map((s) => `${String(s.hour).padStart(2, "0")}:${String(s.minute).padStart(2, "0")}`).join(" / ") },
          { title: "状态", dataIndex: "status", render: (s, r) => (
            <Switch checked={s === "enabled"} checkedChildren="启用" unCheckedChildren="停用"
              onChange={async (v) => { await updateStatus(r.id, v ? "enabled" : "disabled"); load(); }} />
          ) },
          { title: "操作", render: (_, r) => (
            <Space>
              <Button size="small" onClick={async () => { const x = await trigger(r.id); message.success(`已触发 run ${x.data.run_id}`); }}>立即执行</Button>
              <Link to={`/admin/schedules/${r.id}/edit`}><Button size="small">编辑</Button></Link>
              <Link to={`/admin/schedules/${r.id}/runs`}><Button size="small">历史</Button></Link>
              <Button size="small" danger onClick={async () => {
                Modal.confirm({ title: "确认删除?", onOk: async () => { await deleteSchedule(r.id); load(); } });
              }}>删除</Button>
            </Space>
          ) },
        ]} />
    </>
  );
}
```

- [ ] **Step 3:写 `frontend/src/pages/Schedules/Edit.tsx`**

```tsx
import { Form, Input, Select, Button, Space, TimePicker, message, Card, Steps } from "antd";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import dayjs, { Dayjs } from "dayjs";
import { createSchedule, getSchedule, updateSchedule, Slot } from "../../api/schedules";
import { listProjects, getProject, Project, ProjectDetail } from "../../api/projects";

export default function ScheduleEdit() {
  const { id } = useParams();
  const sid = id ? Number(id) : null;
  const nav = useNavigate();
  const [step, setStep] = useState(0);
  const [projects, setProjects] = useState<Project[]>([]);
  const [form] = Form.useForm();
  const [slots, setSlots] = useState<Slot[]>([{ slot_index: 1, hour: 9, minute: 0 }]);
  const [projectDetail, setProjectDetail] = useState<ProjectDetail | null>(null);
  const [prompts, setPrompts] = useState<string[]>([]);
  const [keywords, setKeywords] = useState<string[]>([]);
  const [platforms, setPlatforms] = useState<any[]>([]);

  useEffect(() => {
    listProjects({ size: 100 }).then((r) => setProjects(r.data.items));
    if (sid) getSchedule(sid).then((r) => {
      const s = r.data;
      form.setFieldsValue({ name: s.name, project_id: s.project_id });
      setSlots(s.slots);
      setPrompts(s.prompts_override ?? []);
      setKeywords(s.keywords_override ?? []);
      setPlatforms(s.platforms_override ?? []);
    });
  }, [sid]);

  const onPickProject = async (pid: number) => {
    const r = await getProject(pid);
    setProjectDetail(r.data);
    setPrompts(r.data.prompts);
    setKeywords(r.data.keywords);
    setPlatforms(r.data.platforms);
  };

  const onSubmit = async () => {
    const v = await form.validateFields();
    const payload = {
      ...v,
      slots: slots.filter((s) => s.hour !== undefined && s.minute !== undefined),
      prompts_override: prompts, keywords_override: keywords, platforms_override: platforms,
    };
    if (sid) await updateSchedule(sid, payload);
    else await createSchedule(payload);
    message.success("已保存");
    nav("/admin/schedules");
  };

  return (
    <Card>
      <Steps current={step} onChange={setStep} items={[{ title: "选项目" }, { title: "时间点" }, { title: "入参覆盖" }, { title: "确认" }]} />
      <div style={{ marginTop: 24 }}>
        {step === 0 && (
          <Form form={form} layout="vertical">
            <Form.Item name="name" label="调度名称" rules={[{ required: true }]}><Input /></Form.Item>
            <Form.Item name="project_id" label="项目" rules={[{ required: true }]}>
              <Select options={projects.map((p) => ({ value: p.id, label: `${p.name} (${p.code})` }))} onChange={onPickProject} />
            </Form.Item>
          </Form>
        )}
        {step === 1 && (
          <Space direction="vertical">
            {slots.map((s, i) => (
              <Space key={i}>
                <TimePicker
                  value={dayjs().hour(s.hour).minute(s.minute)}
                  format="HH:mm"
                  minuteStep={5}
                  onChange={(v: Dayjs | null) => {
                    if (!v) return;
                    const next = [...slots]; next[i] = { slot_index: (i + 1) as 1 | 2, hour: v.hour(), minute: v.minute() };
                    setSlots(next);
                  }}
                />
                {i === slots.length - 1 && slots.length < 2 && (
                  <Button onClick={() => setSlots([...slots, { slot_index: 2, hour: 18, minute: 0 }])}>添加第二个时间点</Button>
                )}
                {slots.length > 1 && <Button danger onClick={() => setSlots(slots.filter((_, j) => j !== i))}>删除</Button>}
              </Space>
            ))}
          </Space>
        )}
        {step === 2 && (
          <Space direction="vertical" style={{ width: "100%" }}>
            <Card title="prompts (覆盖)" size="small">{prompts.map((p, i) => <Input key={i} value={p} style={{ marginBottom: 8 }} onChange={(e) => { const n = [...prompts]; n[i] = e.target.value; setPrompts(n); }} />)}</Card>
            <Card title="keywords (覆盖)" size="small">{keywords.map((p, i) => <Input key={i} value={p} style={{ marginBottom: 8 }} onChange={(e) => { const n = [...keywords]; n[i] = e.target.value; setKeywords(n); }} />)}</Card>
            <Card title="platforms (覆盖)" size="small">{JSON.stringify(platforms)}</Card>
          </Space>
        )}
        {step === 3 && (
          <pre>{JSON.stringify({ ...form.getFieldsValue(), slots, prompts, keywords, platforms }, null, 2)}</pre>
        )}
      </div>
      <div style={{ marginTop: 24 }}>
        {step > 0 && <Button onClick={() => setStep(step - 1)}>上一步</Button>}
        {step < 3 && <Button type="primary" onClick={async () => { if (step === 0) await form.validateFields(); setStep(step + 1); }} style={{ marginLeft: 8 }}>下一步</Button>}
        {step === 3 && <Button type="primary" onClick={onSubmit} style={{ marginLeft: 8 }}>保存</Button>}
      </div>
    </Card>
  );
}
```

- [ ] **Step 4:写 `frontend/src/pages/Schedules/Runs.tsx`**

```tsx
import { Table, Tag } from "antd";
import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { listRuns } from "../../api/schedules";

export default function ScheduleRuns() {
  const { id } = useParams();
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => { listRuns(Number(id), { page: 1, size: 50 }).then((r) => setItems(r.data.items)); }, [id]);

  return (
    <Table rowKey="id" dataSource={items}
      columns={[
        { title: "run_id", dataIndex: "id" },
        { title: "触发类型", dataIndex: "trigger_type", render: (t) => <Tag>{t}</Tag> },
        { title: "触发时间", dataIndex: "triggered_at" },
        { title: "状态", dataIndex: "status", render: (s) => <Tag color={s === "success" ? "green" : s === "failed" ? "red" : s === "skipped" ? "orange" : "blue"}>{s}</Tag> },
        { title: "task_id", dataIndex: "task_id", render: (t) => t ? <Link to={`/admin/tasks/${t}`}>{t}</Link> : "-" },
        { title: "错误", dataIndex: "error_message" },
      ]} />
  );
}
```

- [ ] **Step 5:写 `frontend/src/pages/ProjectTasks/List.tsx`**

```tsx
import { Table, Tag } from "antd";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import axios from "axios";

export default function ProjectTasksList() {
  const { id } = useParams();
  const [items, setItems] = useState<any[]>([]);
  useEffect(() => { axios.get(`/api/projects/${id}/tasks`, { params: { size: 50 } }).then((r) => setItems(r.data.items)); }, [id]);

  return (
    <Table rowKey="id" dataSource={items}
      columns={[
        { title: "task_id", dataIndex: "task_id" },
        { title: "状态", dataIndex: "status", render: (s) => <Tag>{s}</Tag> },
        { title: "完成/总数", render: (_, r) => `${r.completed_items ?? 0}/${r.total_items ?? 0}` },
        { title: "调度 run", dataIndex: "schedule_run_id" },
        { title: "创建时间", dataIndex: "created_local_at" },
      ]} />
  );
}
```

- [ ] **Step 6:Commit**

```bash
git add frontend/
git commit -m "feat(frontend): schedules list/edit/runs and project tasks list"
```

---

## Phase 7:集成测试、Docker、文档

### Task 16:`docker-compose.yml` + `Dockerfile`

**Files:**
- Create: `docker-compose.yml`
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`

- [ ] **Step 1:写 `backend/Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
ENV TZ=Asia/Shanghai
RUN apt-get update && apt-get install -y tzdata && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime
COPY pyproject.toml ./
RUN pip install --no-cache-dir .[dev]
COPY . .
RUN mkdir -p /data/logos
EXPOSE 18083
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "18083"]
```

- [ ] **Step 2:写 `frontend/Dockerfile`**

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
```

- [ ] **Step 3:写 `frontend/nginx.conf`**

```
server {
  listen 80;
  location / {
    root /usr/share/nginx/html;
    try_files $uri $uri/ /index.html;
  }
  location /api/ { proxy_pass http://backend:18083; }
  location /static/ { proxy_pass http://backend:18083; }
}
```

- [ ] **Step 4:写 `docker-compose.yml`**

```yaml
version: "3.9"
services:
  mysql:
    image: mysql:8
    environment:
      TZ: Asia/Shanghai
      MYSQL_ROOT_PASSWORD: root
      MYSQL_DATABASE: geo
      MYSQL_USER: admin
      MYSQL_PASSWORD: admin123
    command: --default-time-zone=+08:00
    volumes: [mysql_data:/var/lib/mysql]
    ports: ["3306:3306"]

  backend:
    build: ./backend
    environment:
      TZ: Asia/Shanghai
      DATABASE_URL: mysql+pymysql://admin:admin123@mysql:3306/geo?charset=utf8mb4
      MOLIZHISHU_TOKEN: ${MOLIZHISHU_TOKEN}
      MOLIZHISHU_CALLBACK_URL: ${MOLIZHISHU_CALLBACK_URL}
      JWT_SECRET: ${JWT_SECRET}
    volumes: [logo_data:/data/logos]
    ports: ["18083:18083"]
    depends_on: [mysql]

  frontend:
    build: ./frontend
    ports: ["8080:80"]
    depends_on: [backend]

volumes:
  mysql_data: {}
  logo_data: {}
```

- [ ] **Step 5:Commit**

```bash
git add .
git commit -m "chore: docker compose for backend, frontend, mysql"
```

---

### Task 17:`README.md` + 验收清单

**Files:**
- Create: `README.md`

- [ ] **Step 1:写 `README.md`(简短版,关键信息)**

````markdown
# windx 全栈系统

模力指数监控数据接入 + 任务调度管理界面。

## 技术栈
- 后端:Python 3.11 + FastAPI + SQLAlchemy + APScheduler
- 前端:React 18 + Vite + Ant Design 5
- DB:MySQL 8(Asia/Shanghai)

## 启动(Docker Compose)

```bash
cp backend/.env.example backend/.env  # 填入 MOLIZHISHU_TOKEN 等
export MOLIZHISHU_TOKEN=...
export JWT_SECRET=$(openssl rand -hex 32)
docker compose up -d
# 前端: http://localhost:8080
# 后端: http://localhost:18083
```

## 默认账号
- 初始化 SQL(在首次启动后手动执行或写入 alembic 后续 migration):

```sql
INSERT INTO geo_admin_users (username, password_hash, display_name, role, status, created_at, updated_at)
VALUES ('admin', '$2b$12$<bcrypt-of-molizhishu>', '超级管理员', 'super_admin', 'active', NOW(), NOW());
```

> 生产环境必须修改默认密码。

## 接口清单(本仓库新增)
- 客户:`/api/customers`(CRUD + `/logo`)
- 项目:`/api/projects`(CRUD + 4 个 tab 配置)
- 调度:`/api/schedules`(CRUD + `/status` + `/trigger` + `/runs`)
- 任务列表扩展:`/api/tasks?customer_id=&project_id=`、`/api/projects/{id}/tasks`
- 鉴权扩展:`GET /api/auth/me` 返回 `role` 和 `customer_id`

## 哪些接口只读本地、哪些调用远端、哪些接收 Callback
- **只读本地**:`GET /api/tasks`、`GET /api/tasks/{taskId}`、`GET /api/projects/{id}/tasks`、`GET /api/schedules/{id}/runs`
- **调用远端**:`POST /api/schedules/{id}/trigger`(内部调 SubmitTask)、`POST /api/tasks`(沿用)
- **接收 Callback**:`POST /webhooks/molizhishu`(沿用)
- **后台轮询**:沿用 `api调用prompt.md` §十,本期不重复实现
````

- [ ] **Step 2:Commit**

```bash
git add README.md
git commit -m "docs: README with startup and API summary"
```

---

## 附录 A:v2 适配清单(UI 重构 + 数据模型内嵌)

> 本节用于 v2 重构适配。所有原 Task 1–8/10–13/16–17 的实现细节保留,仅按以下清单做替换与合并。

### A.1 数据模型调整(影响 Task 2 / Task 3)

| 原设计(v1) | v2 |
|---|---|
| `geo_schedules` 表(独立) | **删除** |
| `geo_schedule_slots` 表(独立) | **删除** |
| `geo_schedule_runs` 表 | 保留,但 `schedule_id` 改为 `project_id`(INT FK→geo_projects) |
| `geo_projects` 表 | 新增字段:`schedule_enabled BOOL DEFAULT FALSE`、`slot1_hour TINYINT NULL`、`slot1_minute TINYINT NULL`、`slot2_hour TINYINT NULL`、`slot2_minute TINYINT NULL`、`description TEXT NULL` |
| `geo_tasks` 扩展 | 移除 `schedule_id`;保留 `project_id` 与 `schedule_run_id` |

cooldown_key 由 `schedule-{id}-slot-{idx}-...` 改为 `project-{id}-slot-{idx}-{YYYYMMDDHH}{floor(minute/5)}`。

### A.2 API 调整(影响 Task 4 / Task 5 / Task 9)

| 原 API(v1) | v2 |
|---|---|
| `POST /api/schedules` | **删除**(调度随项目创建) |
| `GET /api/schedules` | **删除** |
| `GET /api/schedules/{id}` | **删除** |
| `PUT /api/schedules/{id}` | **删除** |
| `DELETE /api/schedules/{id}` | **删除** |
| `PUT /api/schedules/{id}/status` | 改为 `PUT /api/projects/{id}/schedule/status` |
| `POST /api/schedules/{id}/trigger` | 改为 `POST /api/projects/{id}/schedule/trigger` |
| `GET /api/schedules/{id}/runs` | 改为 `GET /api/projects/{id}/runs` |
| `GET /api/schedules/runs/{run_id}` | 改为 `GET /api/projects/runs/{run_id}` |

新增(并入项目 API):
- `GET /api/projects/{id}/schedule`(读取 schedule + slots + enabled + 上次 run 摘要)
- `PUT /api/projects/{id}/schedule`(修改 schedule + slots + enabled,1–2 个 slot)
- `DELETE /api/projects/{id}/schedule`(移除 schedule)

### A.3 调度器与执行流调整(影响 Task 7 / Task 8)

**Task 8 startup recovery SQL 改为:**
```sql
SELECT id, schedule_enabled, slot1_hour, slot1_minute, slot2_hour, slot2_minute
  FROM geo_projects
  WHERE schedule_enabled = TRUE AND status = 'active'
```

**job id 改为** `project-{id}-slot-{slot_index}`(原 `schedule-{id}-{slot_index}`)。

**Task 7 的 `run_schedule` 函数重命名为 `run_project(project_id, slot_index, trigger_type)`**;移除原"读 geo_schedules"步骤,改为"读 geo_projects + 配置"。

**Task 7 中 cooldown_key 计算改为**:
```python
cooldown_key = f"project-{project_id}-slot-{slot_index}-{now.strftime('%Y%m%d%H')}{now.minute // 5}"
```

### A.4 任务清单调整(原 Task 9 / Task 14 / Task 15)

| 原任务 | v2 处置 |
|---|---|
| **Task 9**:调度 CRUD API + 触发 + 执行历史 | **合并进 Task 5**(在 Task 5 末尾追加 §5.x 子节,实现 `/api/projects/{id}/schedule*` 与 `/api/projects/{id}/runs`) |
| **Task 14**:项目列表 + 项目详情(4 tab) | **替换**为:项目列表(含调度状态/下一执行/最近一次列 + 行内 toggle)+ 项目详情(头部调度控件 + 监控参数概览 + 6 个 Tab)。Tab 顺序:**监控问题 / AI 模型 / 关键词 / 竞品信息 / 执行历史 / 基本信息**,默认进入"监控问题" |
| **Task 15**:调度管理 UI + 项目下任务 | **替换**为:**Task 15(新):工作台 Dashboard** —— 实现 KPI 卡 / 最近执行时间线 / 状态分布 / 即将执行列表 4 个区块 |
| **Task 11**:`run_schedule` 集成测试 | **改名**为 `run_project` 集成测试 |

### A.5 前端目录调整(影响 Task 12 起的所有前端任务)

新增/修改的目录:
```
frontend/src/
├── pages/
│   ├── Dashboard/
│   │   └── index.tsx          (新:工作台)
│   ├── Customers/             (沿用)
│   └── Projects/
│       ├── List.tsx           (改:含调度列、行内 toggle)
│       └── Detail.tsx         (改:头部调度控件 + 监控参数概览 + 6 Tab)
├── components/
│   ├── SlotTimePicker.tsx     (新)
│   ├── ModelMultiSelect.tsx   (新)
│   └── MonitorParamsOverview.tsx (新)
└── api/
    ├── projects.ts            (改:增加 schedule / runs / trigger)
    └── customers.ts           (沿用)
```

**删除**目录:`pages/Schedules/`、`pages/ProjectTasks/`(合并进 Projects)。

### A.6 侧边栏菜单(影响 Task 13)

| 旧菜单(多组) | v2 |
|---|---|
| 工作台 / 项目管理 / 客户管理 / 调度管理 / 项目下任务 / 设置 ... | **3 项**:工作台 / 项目管理 / 客户管理(超管可见) |

customer_admin 角色看不到"客户管理",其他可见。

### A.7 API 调用参数(`run_project` 调用 `submit_task`)

不再有 override 字段。直接从 `geo_projects` + `geo_project_prompts` / `geo_project_keywords` / `geo_project_platforms` 读取。组装规则不变:
```python
prompts = [p.prompt for p in project.prompts]   # 按 sort 排序
keywords = [k.keyword for k in project.keywords]  # 按 sort 排序
platforms = [{"platform": pl.platform, "mode": pl.mode, "screenshot": pl.screenshot} for pl in project.platforms]
monitor_keywords = ",".join(keywords)
callback_url = settings.MOLIZHISHU_CALLBACK_URL
```

### A.8 验收(影响 Task 17 README)

新增验收项:
- [ ] 侧边栏只有 3 项菜单
- [ ] 项目详情头部含 调度开关 + 立即执行 + 1–2 个时间槽
- [ ] 项目详情头部下方含"监控参数概览"卡
- [ ] 项目详情默认 Tab 为"监控问题"
- [ ] 项目列表行内 toggle 可直接切换 schedule enabled
- [ ] 工作台 `/admin` 渲染 4 个区块(KPI / 时间线 / 分布 / 即将执行)

---

## 自审(plan-vs-spec,v2)

- ✅ §1 数据模型(内嵌版) — Task 2 迁移 + Task 3 模型 + **附录 A.1**
- ✅ §2 API(项目内嵌版) — Task 4/5/6/10 + **附录 A.2**(Task 9 内容并入 Task 5)
- ✅ §3 调度器 — Task 7(`run_project`)+ Task 8 + **附录 A.3**
- ✅ §4 UI 页面 — Task 13/14(v2)+ **Task 15 新**(Dashboard) + **附录 A.4–A.6**
- ✅ §5 错误处理 — 嵌入 Task 4/5 拒绝逻辑;Task 11 集成测试
- ✅ 鉴权扩展 — Task 6
- ✅ 测试 — Task 4/5/6/11 + Task 13/14(v2)

无 TODO/占位符;类型/方法名一致(`run_project`、`ScheduleRun.cooldown_key`、`project-{id}-slot-{idx}` 模式一致)。

---

## 执行选项

**计划完成并保存到 `docs/superpowers/plans/2026-08-07-schedule-management.md`。两种执行方式:**

1. **Subagent-Driven(推荐)** — 每个任务派一个新子代理,任务间有审查,快速迭代
2. **Inline Execution** — 在本会话内批量执行,带 checkpoint 复审

请选择执行方式?