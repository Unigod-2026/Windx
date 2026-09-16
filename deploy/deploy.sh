#!/usr/bin/env bash
# 服务器端部署脚本 —— Docker 化后的 windx-geo。
# 单一容器跑后端 + 前端 dist/(FastAPI 静态服务),对外只暴露 5173。
# 后端 18083 是容器内端口,宿主机不暴露。
#
# 前置:
#   - 仓库已 clone 在任意目录(脚本从自身路径反推仓库根)
#   - .env 已填好真值在 $REPO_ROOT/.env,且 LOGO_STORAGE_DIR / LOG_DIR
#     指向 /app/data/{logos,logs}(与 docker-compose.yml 的 volume 一致)
#   - 服务器装好 docker + docker compose plugin
#   - 防火墙只放 5173(参考 docs/)
#
# 用法:
#   ./deploy/deploy.sh
#   ./deploy/deploy.sh --help

set -euo pipefail

# docker compose 子命令在不同版本里叫 `docker compose` (v2) 或 `docker-compose`
# (v1 standalone)。先探测一下。
if docker compose version >/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
else
  echo "需要 docker + docker compose(>=v2 推荐),都没找到" >&2
  exit 1
fi

# REPO_ROOT 默认 = 脚本父目录的父目录(仓库根)。仍可 REPO_ROOT=... 覆盖。
_REPO_ROOT_DEFAULT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="${REPO_ROOT:-$_REPO_ROOT_DEFAULT}"
DEPLOY_USER="${SUDO_USER:-$(id -un)}"

usage() {
  sed -n '2,17p' "$0"
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

# --- 2. 清掉旧的 PM2 / systemd nginx(部署形态从 systemd 改成 Docker)---
# 老 backend windx-backend 由 PM2 管的,留着会和容器内 backend 重复。
# 老 nginx windx.conf 站点(80/443 + 5173)删掉,新形态全交给容器。
if command -v pm2 >/dev/null 2>&1 && pm2 describe windx-backend >/dev/null 2>&1; then
  echo "==> stop pm2 windx-backend"
  pm2 delete windx-backend || true
fi
if [[ -f /etc/nginx/sites-enabled/windx.conf ]]; then
  echo "==> disable old windx nginx site"
  sudo rm -f /etc/nginx/sites-enabled/windx.conf
  sudo rm -f /etc/nginx/sites-available/windx.conf
  sudo nginx -t && sudo systemctl reload nginx || true
fi

# --- 3. 准备持久化目录(./data/logos, ./data/logs)--------------------
mkdir -p data/logos data/logs

# --- 4. 构建 + 启动容器 ----------------------------------------------
echo "==> docker compose up -d --build"
$DC up -d --build

# --- 5. smoke check ----------------------------------------------------
sleep 3
# 直打 5173 验证 FastAPI /health,确认容器起来 + alembic 跑完 + uvicorn 在听。
if curl -fsS http://localhost:5173/health >/dev/null; then
  echo "==> OK  http://localhost:5173/health (容器 + 后端)"
else
  echo "==> health failed,排查:" >&2
  echo "    $DC ps                         # 容器在不在" >&2
  echo "    $DC logs --tail 50 windx-geo  # 容器日志" >&2
  echo "    curl http://localhost:5173/health 直打容器" >&2
  exit 1
fi