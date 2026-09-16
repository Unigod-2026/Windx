#!/usr/bin/env bash
# windx-backend 启动入口 —— PM2 调这个,不是直接调 uvicorn。
# 必须从 backend/ 目录运行(PM2 ecosystem config 的 cwd 已经是这个)。
#
# 干三件事:
# 1. source 仓库根 .env(数据库 URL / JWT_SECRET / LLM_API_KEY 等)
# 2. exec .venv/bin/uvicorn — `exec` 让 bash 进程被 uvicorn 替换,
#    PM2 看到的是 uvicorn PID 而不是 bash
# 3. uvicorn 起 4 worker —— Python 没有 PM2 cluster 模式,worker 数量
#    由 uvicorn 自己管(注意:LlmClient 全局 semaphore 限并发 4,见
#    memory feedback_llm_concurrency.md,改 workers 数不会提升吞吐)

set -euo pipefail

set -a
# 仓库根 .env:从 backend/ 上去一级
source ../.env
set +a

exec .venv/bin/uvicorn app.main:app \
  --host 0.0.0.0 \
  --port 5173 \
  --workers 4 \
  --proxy-headers \
  --no-access-log