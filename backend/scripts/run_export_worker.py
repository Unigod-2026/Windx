"""导出 worker 进程入口 —— 独立于 API 进程跑导出任务。

启动方式(生产):

    pm2 start deploy/pm2.ecosystem.config.cjs --only windx-export-worker

本地手工跑:

    cd backend && uv run python -m scripts.run_export_worker

为什么独立进程:生产 API 是 ``uvicorn --workers 4`` + pm2 单 app,导出
吃内存(几十 MB 文本 → 上百 MB 工作簿)会撞 API 的 ``max_memory_restart 1G``;
而且 4 个 worker 各跑一份轮询会同时跑 4 个导出,内存尖峰 ×4。独立进程
单进程串行,天然规避。
"""

from __future__ import annotations

import sys

from app.db import get_session_factory
from app.logging_setup import configure_logging
from app.services.export_worker import DEFAULT_DATA_ROOT, worker_loop


def main() -> int:
    configure_logging()
    print(f"export worker started, data_root={DEFAULT_DATA_ROOT}", flush=True)
    worker_loop(get_session_factory, DEFAULT_DATA_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
