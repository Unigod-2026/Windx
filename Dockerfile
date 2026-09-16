# 单阶段 —— 前端 build 由 deploy.sh 在 host 上跑完,Docker 这里只 COPY 产物。
# 避开 Docker 内 Node 构建挂掉的盲区(看不到 npm/vite 实时输出)。

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

# 前端 dist 由 deploy.sh 在 host 跑 npm run build 生成。
# main.py 里 /app/frontend_dist 是 StaticFiles 的目录。
COPY frontend/dist ./frontend_dist

# 容器里 alembic 升级 + 启 uvicorn。exec 让 uvicorn 替换 shell,
# docker stop 的 SIGTERM 直接打给 uvicorn,优雅退出。
CMD uv run alembic upgrade head && exec uv run uvicorn app.main:app --host 0.0.0.0 --port 18083