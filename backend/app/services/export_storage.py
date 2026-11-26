"""导出产物放在哪 —— 相对路径 ↔ 绝对路径。

**为什么任务行里存相对路径而不是绝对路径**:本地开发与生产共用同一个
MySQL(本地的 13306 是到远端的 SSH 隧道,``.env`` 的 DATABASE_URL 指它)。
绝对路径只在**生成它的那台机器**上有意义 —— 生产机读到一条本地生成的
任务,拿到 ``/home/wangjh/...`` 这个路径,文件不在它磁盘上,下载就 404;
反过来也一样。

所以任务行里存的是**相对数据根**的路径(``62/17.xlsx``),由**提供下载的
那台机器**用自己的数据根解析成绝对路径。两个环境各自自洽:
本地 worker 生成的 → 本地 API 能下;生产 worker 生成的 → 生产 API 能下。

历史行里可能还留着绝对路径 —— pathlib 遇到绝对路径会直接覆盖基路径,
所以旧行不用做数据迁移也能照常解析。

数据根默认是 ``backend/data/exports``(``.gitignore`` 已忽略整个
``backend/data/``)。一个项目一个子目录:``{project_id}/{task_id}.xlsx``。
"""

from __future__ import annotations

from pathlib import Path

#: 导出产物的数据根 —— backend/data/exports。
DEFAULT_DATA_ROOT = Path(__file__).resolve().parents[2] / "data" / "exports"


def relative_path_for(project_id: int, task_id: int) -> str:
    """任务产物的相对路径(写进 ``geo_export_tasks.file_path``)。"""
    return f"{project_id}/{task_id}.xlsx"


def resolve_export_path(file_path: str, data_root: Path = DEFAULT_DATA_ROOT) -> Path:
    """把任务行里的路径解析成本机的绝对路径。

    相对路径 → 拼到本机的数据根下面;绝对路径(历史行)→ 原样返回。
    """
    return Path(data_root) / file_path
