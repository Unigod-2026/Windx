# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

本仓库**同时承载规范与实现代码**:根目录 `.md` 是接入「模力指数监控 API」与品牌提及分析的权威规范,实现代码位于 `backend/`(FastAPI)与 `frontend/`(React + AntD)。**所有路径、字段、状态值、错误码以 `docs/api/` 与 `docs/superpowers/specs/` 为准**。

## 业务目标

全栈 GEO 监控 + 品牌提及分析平台,核心功能:
1. 按项目配置的监控问题 / 关键词 / 模型,定时向 AI 平台(deepseek / doubao / kimi / 文心一言 等)提交问题并收集回答(由 `LLMClient` 走 Anthropic-compatible 端点实际执行;`MolizhishuClient` 现为兼容垫片)。
2. 对回答做品牌提及抽取:正则统计提及次数 + LLM 抽取排名/情感/推荐/顾虑,落 `geo_brand_mentions` 表;UI 工作台 OverviewTab / 问题提及分析直接消费。
3. 人工修改 / 二次加工监控数据,以及竞品维护(手工 + Agent 自动发现 pending)。
4. 多租户:`super_admin` 管全部客户;`customer_admin` 访问范围自动收窄到自身 `customer_id`。

技术栈: **Python 3.11 + FastAPI + SQLAlchemy 2 + APScheduler**(后端)、**React 18 + Vite + Ant Design 5**(前端)、**MySQL 8 (Asia/Shanghai)**。

## 文档结构与权威性

| 文件 | 用途 |
|------|------|
| `需求.md` | 业务需求 + 技术选型概要 |
| `api调用prompt.md` | 后端工程师接入 prompt,含 API 客户端、本地表结构、本地 API、后台同步、日志、安全、错误处理、测试 |
| `docs/api/overview.md` | Base URL、认证、统一响应格式、状态枚举、时间约定 |
| `docs/api/submit-task.md` | POST /task/batch/shared |
| `docs/api/get-task-status.md` | GET /task/status/{taskId} |
| `docs/api/get-task-result.md` | GET /task/result/{taskId} |
| `docs/api/stop-task.md` | PUT /task/stop/{taskId} |
| `docs/api/task-list.md` | GET /task/list(仅手动使用,不接入轮询) |
| `docs/api/callback-url.md` | GET/PUT /task/callback-url(全局回调) |
| `docs/api/callback.md` | 远端主动推送 payload + 幂等与 upsert 要求 |
| `docs/api/city-info.md` | GET /eip-edge/ports/city-info(独立域名) |
| `docs/api/errors.md` | 业务错误码(200/300001/403/404/500001/500)与传输错误处理 |
| `docs/superpowers/specs/2026-08-07-schedule-management-design.md` | 任务调度管理界面设计(多租户 + APScheduler + 4 个 UI 页面) |
| `docs/编辑监控项目.png` / `docs/球状监控页面需求.docx` | 项目详情页 / 监控项编辑 UI mockup(nightly snapshot 引入,后续 UI 改动的视觉依据) |

实现细节、字段含义、状态值、错误码必须先读 `docs/api/` 与相关 spec,再写代码。

### 关键模块速查

| 改… | 看 |
|-----|----|
| 调度入口 | `backend/app/services/scheduler.py` + `scheduler_runtime.py` |
| LLM 调用 / 工具协议 | `backend/app/services/llm_client.py` + `llm_tools.py` + `llm_prompts.py` |
| 品牌提及两阶段抽取 | `backend/app/services/extraction.py` |
| 远端同步 / 补偿日志 | `backend/app/services/sync.py` + `app/services/molizhishu_client.py`(兼容垫片) |
| 日志规范 | `backend/app/logging_setup.py` |
| 前端项目工作台 tab | `frontend/src/pages/Projects/{OverviewTab,QuestionTab,PromptsTab,CompetitorsTab}.tsx` + `AliasEditModal.tsx` + `TaskDetailModal.tsx` |
| 项目上下文(当前选中项目) | `frontend/src/auth/ProjectContext.tsx` |

## 关键环境变量

所有变量在 `.env` 中维护,实现代码统一通过 `app.config.get_settings()` 读取,**不要硬编码**:

- `DATABASE_URL` — 必填,MySQL 连接串(`mysql+pymysql://...`)
- `JWT_SECRET` — 必填,长度 ≥ 1,生产用 `openssl rand -hex 32`
- `APP_PORT=18083` / `TZ=Asia/Shanghai`
- `LOGO_STORAGE_DIR` / `LOGO_MAX_BYTES` — 客户 logo 存储
- `LOG_DIR` / `LOG_LEVEL` — `logging_setup.py` 落盘位置与级别

**LLM 后端(实际执行监控提问)**
- `LLM_MODE` / `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` — Anthropic-compatible 协议
- `LLM_TIMEOUT_SECONDS` / `LLM_MAX_TOOL_ROUNDS` / `LLM_MAX_CONCURRENCY` / `LLM_WEB_FETCH_MAX_BYTES`

**Molizhishu(兼容垫片,本期不再主动调用)**
- `MOLIZHISHU_TOKEN` — 仅服务端使用,不得写入代码/日志/前端/commit/stash
- `MOLIZHISHU_BASE_URL` / `_CITY_URL` / `_CALLBACK_URL` / `_TIMEOUT_SECONDS` / `_SYNC_*` / `_ALLOW_API_KEY_UPDATE` — 见 `docs/api/`

## 接入核心约定(写代码前必读)

1. **响应判断**:HTTP 200 也可能业务失败,必须用 `success` + `code`(Molizhishu 兼容路径;`LLMClient` 走 HTTP 状态码即可)。
2. **主任务终态**(`RunStatus`):`SUCCESS` / `FAILED` / `RUNNING`(`run_project` 写入 `geo_schedule_runs`)。
3. **品牌提及抽取状态**(`ExtractStatus`):`PENDING` → `SUCCESS` / `FAILED` / `SKIPPED`。**正则先写 row 给"总提及次数"用,LLM 失败不能删 row**;UI 据此显示"待抽取"而不是假装数据不存在。
4. **幂等**:Callback 用 `(taskId, payload_hash)` 去重,upsert,不抛错;`geo_brand_mentions` 用 `(subtask_id, brand_canonical)` UNIQUE 去重。
5. **数据落库**:`answerContent` 后端不洗,原样存 Markdown/HTML;`concern_hits_json` / `raw_extraction` 是 JSON 列,不要二次序列化。
6. **时区**:容器 + MySQL 都 `Asia/Shanghai`,业务时间一律 `app.models.common.now_local()`,**不要** `datetime.utcnow()`。
7. **同步策略**:APScheduler 周期跑 `sync_pending_tasks`(`app/services/sync.py`)刷新 in-flight Task;回调 `/webhooks/molizhishu` 是加速路径,但当前 LLM 后端是同步执行,Task 入库时通常已终态,polling 主要是触发抽取流水线。
8. **日志打标**:每条远端调用日志必须含 `source`(例 `local-api:submit-task` / `background-sync:poll` / `background-sync:refresh` / `extraction:regex` / `extraction:llm` / `callback`)。
9. **Token 安全**:`MOLIZHISHU_TOKEN` / `LLM_API_KEY` 不入代码、不入 commit、不入 stash message、不入日志、不入测试快照、不入前端;配置走环境变量。
10. **外键约定**:跨表关联列是普通 integer/string,**不**用 SQLAlchemy `ForeignKey`(删 Task 不能 cascade 删 mention 行)。

## 本地数据库表

表名统一 `geo_` 前缀,迁移文件 `backend/alembic/versions/` 从 `20260807_0001` 起到 `20260814_0001` 共 6 个 revision;**新增列/表必须新增 alembic revision,不要 `Base.metadata.create_all`**。

**多租户 / 调度(spec §1)**
- `geo_customers` — 客户(含 `logo_path`)
- `geo_admin_users` — 管理员(`super_admin` / `customer_admin`)
- `geo_projects` — 项目(隶属客户,内嵌 `schedule_enabled` + 1-2 个时间槽)
- `geo_project_prompts` / `geo_project_keywords` / `geo_project_platforms` — 项目内配置(`prompts` 加了 `category` / `status` 用于"引流感 / 场景类"分组与暂停单条)
- `geo_project_competitors` — 竞品(`origin` 区分 manual / auto_discovered,`status` 区分 confirmed / pending / dismissed)
- `geo_schedule_runs` — 每次执行记录(`cooldown_key` UNIQUE 防 5 分钟内重复)

**接入 LLM 后端 + 品牌提及抽取**
- `geo_tasks` — 主任务(`task_id` 用远端 `taskId` 字符串 PK)
- `geo_subtasks` — 子任务完整结果(含 `answer_content` / `raw_result_json`)
- `geo_callback_events` — 回调原始 payload + 幂等哈希
- `geo_compensation_events` — 轮询 / 抽取补偿日志(每行带 `source` 打标)
- `geo_brand_mentions` — 品牌提及:`(subtask_id, brand_canonical)` UNIQUE;`mention_count` 来自正则,`rank_position` / `sentiment_score` / `is_recommended` / `concern_hits_json` 来自 LLM,`extract_status` 反映流水线状态

## 交付物(本期已完成)

代码(`backend/` + `frontend/`)、alembic 迁移 6 个 revision、Docker Compose 一键启动、README + 本文件、pytest 全套(`uv run pytest -q`)。本期缺口见 `README.md` 「已知缺口」章节与本节末尾。