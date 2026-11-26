"""导出 worker —— 在独立进程里把 pending 任务跑成 xlsx。

形态:一个进程、一个 while 循环、一次一个任务(串行)。串行是刻意的 ——
xlsx 生成的内存峰值不低,并发跑几个会撞 pm2 的内存上限。

抢占用一条 UPDATE 完成「选一个 + 占住」,靠受影响行数判断有没有抢到,
所以即使不小心起了两个 worker,同一个任务也只会被跑一次。

三个职责:
1. :func:`claim_next_pending` —— 原子抢占;
2. :func:`run_once` —— 跑一个任务(成功落盘 / 失败写错误);
3. :func:`cleanup_expired` —— 删过保留期的文件。
"""

from __future__ import annotations

import logging
import time
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models.common import now_local
from app.models.export_task import ExportTask
from app.services.export_generator import write_export_workbook
from app.services.export_query import collect_export_data, parse_export_params
from app.services.export_storage import (
    DEFAULT_DATA_ROOT,
    relative_path_for,
    resolve_export_path,
)

logger = logging.getLogger("app.export")

#: running 超过这么久还没结果,认为是 worker 被 kill 了,重新排队。
STALE_RUNNING_MINUTES = 30

#: 文件保留天数。
RETENTION_DAYS = 7


def claim_next_pending(db: Session) -> ExportTask | None:
    """原子地抢一个 pending 任务并置为 running;没有则返回 None。

    单条 UPDATE 完成「选一个 + 占住」—— 靠 rowcount 判断是否抢到,
    多 worker 并发时也不会重复跑同一个任务。
    """
    candidate = db.execute(
        select(ExportTask.id)
        .where(ExportTask.status == "pending")
        .order_by(ExportTask.id)
        .limit(1)
    ).scalar_one_or_none()
    if candidate is None:
        return None
    now = now_local()
    result = db.execute(
        update(ExportTask)
        .where(ExportTask.id == candidate, ExportTask.status == "pending")
        .values(status="running", started_at=now, updated_at=now)
    )
    db.commit()
    if result.rowcount != 1:
        # 别人先抢到了
        return None
    task = db.get(ExportTask, candidate)
    logger.info("source=export:worker task_id=%s claimed", candidate)
    return task


def mark_success(
    db: Session, task: ExportTask, relative_path: str, size: int, file_name: str
) -> None:
    task.status = "success"
    task.file_path = relative_path
    task.file_size = size
    task.file_name = file_name
    task.error = None
    task.finished_at = now_local()
    db.commit()
    logger.info(
        "source=export:worker task_id=%s success size=%s path=%s",
        task.id, size, relative_path,
    )


def mark_failed(db: Session, task: ExportTask, message: str) -> None:
    task.status = "failed"
    task.error = message
    task.finished_at = now_local()
    db.commit()
    logger.warning(
        "source=export:worker task_id=%s failed: %s", task.id, message
    )


def reset_stale_running(db: Session, stale_minutes: int = STALE_RUNNING_MINUTES) -> int:
    """把僵死的 running 重置回 pending。返回处理条数。

    worker 被 pm2 重启 / 机器断电时,任务会永远卡在 running —— 前端永远
    转圈。所以启动时先扫一遍,把超过 ``stale_minutes`` 没动静的重新排队。
    """
    cutoff = now_local() - timedelta(minutes=stale_minutes)
    rows = db.execute(
        select(ExportTask).where(
            ExportTask.status == "running",
            ExportTask.started_at.isnot(None),
            ExportTask.started_at < cutoff,
        )
    ).scalars().all()
    for task in rows:
        task.status = "pending"
        task.started_at = None
    db.commit()
    if rows:
        logger.info(
            "source=export:worker requeued %s stale task(s)", len(rows)
        )
    return len(rows)


def cleanup_expired(
    db: Session,
    retention_days: int = RETENTION_DAYS,
    data_root: Path = DEFAULT_DATA_ROOT,
) -> int:
    """删过保留期的文件,并把任务的 ``file_path`` 置 NULL。返回清理条数。

    任务行保留 —— 历史记录比文件重要;前端据此显示「文件已过期」。
    """
    cutoff = now_local() - timedelta(days=retention_days)
    rows = db.execute(
        select(ExportTask).where(
            ExportTask.status == "success",
            ExportTask.file_path.isnot(None),
            ExportTask.finished_at.isnot(None),
            ExportTask.finished_at < cutoff,
        )
    ).scalars().all()
    for task in rows:
        if task.file_path:
            resolve_export_path(task.file_path, data_root).unlink(missing_ok=True)
        task.file_path = None
    db.commit()
    if rows:
        logger.info("source=export:cleanup purged %s expired file(s)", len(rows))
    return len(rows)


def generate_for_task(
    db: Session, task: ExportTask, data_root: Path
) -> tuple[str, int, str]:
    """跑生成。返回 ``(相对路径, 字节数, 下载文件名)``。

    落盘用**相对路径**入库 —— 本地开发与生产共用同一个 MySQL,绝对路径
    只在生成它的那台机器上有意义,另一台读到就 404。详见
    ``app/services/export_storage.py``。

    参数不合法 / 项目没了都算失败 —— 抛异常,调用方转成 failed。
    """
    params = parse_export_params(task.params_json or {})
    data = collect_export_data(db, task.project_id, params)
    target_dir = Path(data_root) / str(task.project_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / f"{task.id}.xlsx"
    write_export_workbook(data, path)
    file_name = f"{data.project_name}_提及率导出_{params.start}_{params.end}.xlsx"
    return relative_path_for(task.project_id, task.id), path.stat().st_size, file_name


def run_once(db: Session, data_root: Path = DEFAULT_DATA_ROOT) -> bool:
    """抢一个任务并跑掉。跑了返回 True,没任务返回 False。"""
    task = claim_next_pending(db)
    if task is None:
        return False
    try:
        relative_path, size, file_name = generate_for_task(db, task, Path(data_root))
    except Exception as exc:  # 任何失败都要落到 failed,不能让 worker 死
        logger.exception("source=export:worker task_id=%s crashed", task.id)
        mark_failed(db, task, str(exc) or exc.__class__.__name__)
        return True
    mark_success(db, task, relative_path, size, file_name)
    return True


def worker_loop(
    session_factory,
    data_root: Path = DEFAULT_DATA_ROOT,
    poll_seconds: float = 3.0,
) -> None:
    """死循环 —— 给 ``scripts/run_export_worker.py`` 用。

    ``session_factory`` 是 **sessionmaker**(不是 session)—— 调用它得到一个
    新 Session,用完即弃。worker 进程不持有长连接,避免会话被远端 MySQL 掐断。
    """
    while True:
        try:
            with session_factory() as db:
                reset_stale_running(db)
                worked = run_once(db, data_root)
                if not worked:
                    cleanup_expired(db)
        except Exception:  # 循环不能因为一次异常就退出
            logger.exception("source=export:worker loop error")
        time.sleep(poll_seconds)
