#!/usr/bin/env bash
# 导出 worker 启动入口 —— PM2 调这个,不是直接调 python。
# 必须从 backend/ 目录运行(PM2 ecosystem config 的 cwd 已经是这个)。
#
# 跟 start-backend.sh 一样:先 source 仓库根 .env(DB URL / JWT_SECRET 等),
# 再 exec python。export worker 只连数据库,不需要 LLM 相关的 env,但
# 一起 source 省得两处维护。

set -euo pipefail

set -a
# 仓库根 .env:从 backend/ 上去一级
source ../.env
set +a

exec .venv/bin/python -m scripts.run_export_worker
