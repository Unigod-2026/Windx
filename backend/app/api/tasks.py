from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.db import get_db
from app.deps import get_current_user
from app.models.customer import AdminUser
from app.models.task import Task
from app.models.enums import AdminRole

router = APIRouter(tags=["tasks"])


@router.get("/api/tasks")
def list_tasks(
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    customer_id: int | None = None,
    project_id: int | None = None,
    db: Session = Depends(get_db),
    user: AdminUser = Depends(get_current_user),
):
    page = max(1, page)
    size = min(100, max(1, size))
    stmt = select(Task)
    if user.role == AdminRole.CUSTOMER_ADMIN:
        stmt = stmt.where(Task.customer_id == user.customer_id)
    if status:
        stmt = stmt.where(Task.status == status)
    if customer_id is not None and user.role != AdminRole.CUSTOMER_ADMIN:
        stmt = stmt.where(Task.customer_id == customer_id)
    if project_id is not None:
        stmt = stmt.where(Task.project_id == project_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Task.id.desc()).offset((page - 1) * size).limit(size)
    ).all()
    return {
        "items": [
            {
                "task_id": t.task_id,
                "status": t.status,
                "total_items": t.total_items,
                "completed_items": t.completed_items,
                "failed_items": t.failed_items,
                "customer_id": t.customer_id,
                "project_id": t.project_id,
                "schedule_run_id": t.schedule_run_id,
                "created_local_at": t.created_local_at.isoformat() if t.created_local_at else None,
            }
            for t in items
        ],
        "total": total,
        "page": page,
        "size": size,
    }