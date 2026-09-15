#!/usr/bin/env bash
# 服务器端部署脚本 —— 增量更新 windx 到生产。
# 后端进程用 PM2 管(不放 systemd),nginx 仍走 sites-enabled。
# 首次部署需要先 bootstrap:装 nginx + pm2 register windx-backend,
# 之后每次代码更新跑这个就行。
#
# 前置:
#   - 仓库克隆在任意目录(脚本会从自身路径反推仓库根)
#   - .env 已填好真值在 $REPO_ROOT/.env
#   - uv / node / nginx / pm2 / mysql-client 已装
#   - 首次跑过 deploy/bootstrap.sh(创建了 nginx site + pm2 注册 windx-backend)
#
# 用法:
#   ./deploy/deploy.sh
#   ./deploy/deploy.sh --skip-build   # 只更后端
#   ./deploy/deploy.sh --skip-migrate # 跳过 alembic 升级
#   ./deploy/deploy.sh --help

set -euo pipefail

# REPO_ROOT 默认 = 脚本父目录的父目录(也就是仓库根)。
# `cd dirname` 反推,不依赖固定 /opt/windx 路径,本地 / 任意部署目录都能用。
# 仍可通过 REPO_ROOT=... 显式覆盖。
_REPO_ROOT_DEFAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="${REPO_ROOT:-$_REPO_ROOT_DEFAULT}"
SKIP_FRONTEND=0
SKIP_BACKEND_MIGRATE=0
DEPLOY_USER="${SUDO_USER:-$(id -un)}"

usage() {
  sed -n '2,18p' "$0"
  exit 0
}

for arg in "$@"; do
  case "$arg" in
    --help|-h) usage ;;
    --skip-build) SKIP_FRONTEND=1 ;;
    --skip-migrate) SKIP_BACKEND_MIGRATE=1 ;;
    *) echo "unknown flag: $arg" >&2; exit 64 ;;
  esac
done

[[ -d "$REPO_ROOT" ]] || { echo "REPO_ROOT=$REPO_ROOT 不存在" >&2; exit 1; }
[[ -f "$REPO_ROOT/.env" ]] || { echo "缺少 $REPO_ROOT/.env" >&2; exit 1; }
cd "$REPO_ROOT"

# --- 1. 拉代码 ---------------------------------------------------------
echo "==> git pull"
git pull --ff-only

# --- 2. 后端:同步依赖 + 跑迁移 -----------------------------------------
echo "==> uv sync"
(cd backend && uv sync)

if [[ $SKIP_BACKEND_MIGRATE -eq 0 ]]; then
  echo "==> alembic upgrade head"
  (cd backend && uv run alembic upgrade head)
fi

# --- 3. 前端:重建静态文件 ----------------------------------------------
if [[ $SKIP_FRONTEND -eq 0 ]]; then
  echo "==> frontend build"
  (cd frontend && npm ci && npm run build)
fi

# --- 4. 重启后端(PM2)+ reload nginx ---------------------------------
# 后端走 PM2 而非 systemd —— 本机以 ubuntu 用户跑 pm2 daemon,不需要 root。
# 优先用 deploy/pm2.ecosystem.config.cjs + start-backend.sh(声明式),
# 若该文件不存在,fall back 到「假设 windx-backend 已经在 PM2 里注册」的
# reloadOrRestart(命令式,适合手动 pm2 start 起来的进程)。
if [[ -f deploy/pm2.ecosystem.config.cjs && -f deploy/start-backend.sh ]]; then
  echo "==> pm2 reloadOrStart (ecosystem)"
  pm2 reloadOrStart deploy/pm2.ecosystem.config.cjs
elif command -v pm2 >/dev/null && pm2 describe windx-backend >/dev/null 2>&1; then
  echo "==> pm2 reloadOrRestart windx-backend"
  pm2 reloadOrRestart windx-backend
else
  echo "==> no pm2 process 'windx-backend' registered; skip"
  echo "    bootstrap with: pm2 start <ecosystem or script>"
fi
if [[ -f deploy/nginx.conf ]]; then
  # nginx install / reload 需要 root。脚本整体以普通用户跑(PM2 daemon 属
  # ubuntu),所以这一步要么 sudo 整段跑、要么已经装过就跳过 reload。
  # sudo -n true:无密码 sudo 才能继续;有密码 sudo 会卡在询问上。
  if (( EUID == 0 )) || sudo -n true 2>/dev/null; then
    SUDO=""
    [[ $EUID -ne 0 ]] && SUDO="sudo"
    echo "==> install nginx site"
    $SUDO install -m 0644 deploy/nginx.conf /etc/nginx/sites-available/windx.conf
    $SUDO ln -sf /etc/nginx/sites-available/windx.conf /etc/nginx/sites-enabled/windx.conf
    $SUDO nginx -t && $SUDO systemctl reload nginx
  else
    echo "==> nginx install skipped (no root / passwordless sudo)"
    echo "    改用: sudo ./deploy/deploy.sh 重跑,或手动:"
    echo "      sudo cp deploy/nginx.conf /etc/nginx/sites-available/windx.conf"
    echo "      sudo ln -sf /etc/nginx/sites-available/windx.conf /etc/nginx/sites-enabled/windx.conf"
    echo "      sudo nginx -t && sudo systemctl reload nginx"
  fi
fi

# --- 6. smoke check -----------------------------------------------------
sleep 3
if curl -fsS http://localhost/healthz >/dev/null; then
  echo "==> OK  http://localhost/healthz"
else
  echo "==> healthz failed,排查:" >&2
  echo "    pm2 status                  # 进程在不在" >&2
  echo "    pm2 logs windx-backend --lines 50  # 后端日志" >&2
  echo "    nginx 没装?curl http://localhost:18083/healthz 直打后端" >&2
  exit 1
fi