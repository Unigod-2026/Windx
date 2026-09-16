# 多阶段 —— Node build 前端,Python 跑后端。
# deploy.sh 用 `docker compose up -d --build` 在服务器上原地构建,不需要预 push 镜像。

# --- stage 1: 前端 ----------------------------------------------------
FROM node:20-alpine AS frontend-builder
WORKDIR /build

# 单独 COPY package*.json 触发 npm ci 缓存,源码改动不会重装依赖。
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
RUN npm run build
# 产物:/build/dist → stage 2 拷到 /app/frontend_dist

# --- stage 2: 后端 ----------------------------------------------------
# 用 astral-sh 的 uv 镜像(内置 python + uv),省一层 pip install uv。
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim
WORKDIR /app

# pymysql / cryptography 需要 gcc;bookworm-slim 装一次就够,装完清 apt 缓存。
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# 同步 Python 依赖(--no-dev 不装 pytest 那些,生产镜像瘦一点)。
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --frozen --no-dev

# 拷后端源码。
COPY backend/ ./

# 拷前端产物。main.py 里 /app/frontend_dist 是 StaticFiles 的目录。
COPY --from=frontend-builder /build/dist ./frontend_dist

# 容器里 alembic 升级 + 启 uvicorn。exec 让 uvicorn 替换 shell,
# docker stop 的 SIGTERM 直接打给 uvicorn,优雅退出。
CMD uv run alembic upgrade head && exec uv run uvicorn app.main:app --host 0.0.0.0 --port 18083