#!/usr/bin/env bash
# 服务器端部署脚本 —— 直接在 host 上 build,不走 Docker / 不走 nginx。
#
# 形态:
#   - 后端 uvicorn 监听 5173(uvicorn 自己挂前端 dist/ 当静态文件)
#   - 前端 dist/ 由 host 上 `npm run build` 生成(backend/app/main.py
#     通过 parents[2] / "frontend" / "dist" 找到)
#   - PM2 拉起 / 重启后端进程
#   - 宿主机防火墙只放 5173
#
# 前置:
#   - 仓库已 clone,REPO_ROOT 默认 = 脚本父目录的父目录
#   - .env 已填好真值,且 LOGO_STORAGE_DIR / LOG_DIR 指向 host 上
#     实际存在的目录(如 /home/ubuntu/projects/Windx/data/{logos,logs})
#   - 服务器装好 python3.11 + uv + node + npm + pm2
#   - 防火墙只放 5173
#
# 用法:
#   ./deploy/deploy.sh
#   ./deploy/deploy.sh --help

set -euo pipefail

# REPO_ROOT 默认 = 脚本父目录的父目录(仓库根)。仍可 REPO_ROOT=... 覆盖。
_REPO_ROOT_DEFAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="${REPO_ROOT:-$_REPO_ROOT_DEFAULT}"
DEPLOY_USER="${SUDO_USER:-$(id -un)}"

usage() {
  sed -n '2,29p' "$0"
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --help|-h) usage ;;
    *) echo "unknown flag: $arg" >&2; exit 64 ;;
  esac
done

[[ -d "$REPO_ROOT" ]] || { echo "REPO_ROOT=$REPO_ROOT 不存在" >&2; exit 1; }
[[ -f "$REPO_ROOT/.env" ]] || { echo "缺少 $REPO_ROOT/.env" >&2; exit 1; }
cd "$REPO_ROOT"

# --- 1. 拉代码 ---------------------------------------------------------
echo "==> git pull"
git pull --ff-only

# --- 2. 准备持久化目录(./data/logos, ./data/logs)--------------------
mkdir -p data/logos data/logs

# --- 3. 同步 Python 依赖 + 跑 alembic --------------------------------
echo "==> uv sync (backend)"
(cd backend && uv sync --frozen --no-dev)

echo "==> alembic upgrade head"
(cd backend && uv run alembic upgrade head)

# --- 4. 在 host 上 build 前端 ----------------------------------------
# Vite + AntD + echarts + tsc -b 在 host 上跑,进度 / 报错肉眼可见。
echo "==> build frontend (host)"
(cd frontend && npm ci --no-audit --no-fund && npm run build)
[[ -f frontend/dist/index.html ]] || {
  echo "frontend/dist/index.html 没生成,前端 build 失败,中止部署" >&2
  exit 1
}

# --- 5. PM2 重启后端 ---------------------------------------------------
# PM2 ecosystem config 读 PM2_CONFIG_CWD 拿仓库根绝对路径(daemon cwd
# 不可靠,见 pm2.ecosystem.config.cjs 头部注释)。
export PM2_CONFIG_CWD="$REPO_ROOT"
echo "==> pm2 reload backend"
if pm2 describe windx-backend >/dev/null 2>&1; then
  pm2 reload windx-backend
else
  pm2 start "$REPO_ROOT/deploy/pm2.ecosystem.config.cjs"
fi
pm2 save --force || true

# --- 6. smoke check ----------------------------------------------------
sleep 3
# 直打 5173 验证 FastAPI /health,确认 uvicorn 在听 5173 + alembic 跑完。
if curl -fsS http://localhost:5173/health >/dev/null; then
  echo "==> OK  http://localhost:5173/health (后端 + 前端静态)"
else
  echo "==> health failed,排查:" >&2
  echo "    pm2 ls                            # 进程在不在" >&2
  echo "    pm2 logs --lines 80 windx-backend # 进程日志" >&2
  echo "    curl http://localhost:5173/health 直打本机" >&2
  echo "    ss -tlnp | grep 5173              # 端口监听状态" >&2
  exit 1
fi
