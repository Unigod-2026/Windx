# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目性质

本仓库目前是**规范与需求仓库**,不包含实现代码。代码应放在其他仓库或在本仓库新建子目录。根目录的 `.md` 文件是接入「模力指数监控 API」的权威规范,**所有路径、字段、状态值、错误码以 `docs/api/` 为准**。

## 业务目标

全栈系统,核心功能:
1. 调用模力指数监控 API 提交监控任务,获取 AI 平台(deepseek / doubao / kimi / 文心一言 等)对指定问题的回答数据。
2. 对获取到的监控数据进行人工修改和二次加工。
3. (拓展)竞品监控。

后端技术栈: **Python + FastAPI**;前端技术栈: **React + Ant Design**;数据库: **MySQL** (Asia/Shanghai 时区)。

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

实现细节、字段含义、状态值、错误码必须先读 `docs/api/`,再写代码。

## 关键环境变量

所有变量在 `.env` 中维护,未来实现代码必须通过配置层读取,**不要硬编码**:

- `MOLIZHISHU_TOKEN` — 仅服务端使用,不得写入代码/日志/前端
- `MOLIZHISHU_BASE_URL` — 默认 `https://business-api.molizhishu.com/api/business/monitor`
- `MOLIZHISHU_CITY_URL` — 独立域名,城市区域接口
- `MOLIZHISHU_CALLBACK_URL` — 全局回调地址(可选)
- `MOLIZHISHU_TIMEOUT_SECONDS` — 默认 30
- `MOLIZHISHU_SYNC_ENABLED` / `_INTERVAL_SECONDS` / `_LIMIT` — 后台轮询
- `MOLIZHISHU_ALLOW_API_KEY_UPDATE` — 是否允许前端修改 API Key
- `DATABASE_URL` — MySQL 连接串
- `APP_PORT=18083` / `TZ=Asia/Shanghai`

## 接入核心约定(写代码前必读)

1. **响应判断**:HTTP 200 也可能业务失败,必须用 `success` + `code`。
2. **主任务终态**:`completed` / `partial_completed` / `failed` / `stopped`。
3. **幂等**:Callback 用 `(taskId, payload_hash)` 去重,upsert,不抛错。
4. **数据落库**:`answerContent` 后端不洗,原样存 Markdown/HTML。
5. **时区**:容器与 MySQL 都按 Asia/Shanghai。
6. **同步策略**:Callback 是加速路径,后台轮询是最终一致性保障;`GET /api/tasks` 只读本地,`POST /api/tasks/{taskId}/sync` 才主动远端调用。
7. **日志打标**:每条远端调用日志必须含 `source`(例如 `local-api:submit-task` / `background-sync:result` / `callback`),便于追溯。
8. **Token 安全**:不在代码、README、commit、测试快照、日志中写 Token。

## 本地数据库表(规划)

表名统一 `geo_` 前缀,见 `api调用prompt.md` 第八节 + 调度管理 spec §1:

**接入模力指数 API**
- `geo_tasks` 主任务
- `geo_subtasks` 子任务完整结果(含 `raw_result_json`)
- `geo_callback_events` 回调原始 payload + 幂等哈希
- `geo_compensation_events` (可选)轮询补偿日志
- `geo_admin_users` 管理端登录

**调度管理(spec §1)**
- `geo_customers` 客户(含 `logo_path`)
- `geo_projects` 项目(隶属于客户)
- `geo_project_prompts` / `geo_project_keywords` / `geo_project_platforms` 项目内配置
- `geo_competitors` 竞品(被动收集,本期不实现抽取)
- `geo_schedules` 调度任务
- `geo_schedule_slots` 每调度 1–2 个时间点
- `geo_schedule_runs` 每次执行记录

## 交付物(接入完成后)

实现完成后应交付:代码、数据库迁移/建表脚本、README、Docker Compose、curl 示例、测试结果,以及「哪些接口调用远端 / 哪些只读本地 / 哪些接收 Callback」的清单。