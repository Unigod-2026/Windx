#!/usr/bin/env bash
# 服务器端部署脚本 —— 增量更新 windx 到生产。
# 首次部署需要先做一次 bootstrap(创建 systemd unit / nginx site / .env),
# 之后每次代码更新跑这个就行。
#
# 前置:
#   - 仓库克隆在任意目录(脚本会从自身路径反推仓库根)
#   - .env 已填好真值在 $REPO_ROOT/.env
#   - uv / node / nginx / mysql-client 已装
#   - 有 sudo 权限(systemctl / nginx reload)
#   - 首次跑过 deploy/bootstrap.sh(创建了 /etc/systemd/system/windx-backend.service
#     和 /etc/nginx/sites-available/windx.conf)
#
# 用法:
#   sudo ./deploy/deploy.sh
#   REPO_ROOT=/custom/path ./deploy/deploy.sh --skip-build   # 只更后端
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

# --- 4. 重新加载 systemd unit + nginx(配置变了才需要) -----------------
if [[ -f deploy/windx-backend.service ]]; then
  echo "==> install systemd unit"
  install -m 0644 deploy/windx-backend.service /etc/systemd/system/windx-backend.service
  systemctl daemon-reload
  systemctl enable windx-backend
fi
if [[ -f deploy/nginx.conf ]]; then
  echo "==> install nginx site"
  install -m 0644 deploy/nginx.conf /etc/nginx/sites-available/windx.conf
  ln -sf /etc/nginx/sites-available/windx.conf /etc/nginx/sites-enabled/windx.conf
fi

# --- 5. 重启服务 --------------------------------------------------------
echo "==> restart windx-backend"
systemctl restart windx-backend

echo "==> nginx reload"
nginx -t && systemctl reload nginx

# --- 6. smoke check -----------------------------------------------------
sleep 3
if curl -fsS http://localhost/healthz >/dev/null; then
  echo "==> OK  http://localhost/healthz"
else
  echo "==> healthz failed,看日志:journalctl -u windx-backend -n 50" >&2
  exit 1
fi