"""Customer CRUD + logo upload API.

Mounted at ``/api/customers`` by ``app.main``. All endpoints require an
active ``super_admin`` (``app.deps.require_super_admin``).

Per spec §5: ``DELETE /api/customers/{id}`` is a soft-disable — it flips
``status`` to ``disabled`` instead of removing the row, and refuses if
the customer still has any project (cascade would otherwise leak).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.deps import require_super_admin
from app.models.customer import AdminUser, Customer
from app.models.project import Project
from app.schemas.customer import (
    CustomerCreate,
    CustomerListOut,
    CustomerOut,
    CustomerUpdate,
)
from app.services.logo_storage import save_logo

router = APIRouter(prefix="/api/customers", tags=["customers"])
settings = get_settings()


def _to_out(c: Customer) -> CustomerOut:
    out = CustomerOut.model_validate(c)
    out.logo_url = f"/static/{c.logo_path}" if c.logo_path else None
    return out


@router.post("", response_model=CustomerOut)
def create_customer(
    payload: CustomerCreate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    if db.scalar(select(Customer).where(Customer.code == payload.code)):
        raise HTTPException(400, "code already exists")
    c = Customer(**payload.model_dump())
    db.add(c)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.get("", response_model=CustomerListOut)
def list_customers(
    page: int = 1,
    size: int = 20,
    status: str | None = None,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    page = max(1, page)
    size = min(100, max(1, size))
    stmt = select(Customer)
    if status:
        stmt = stmt.where(Customer.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(stmt.offset((page - 1) * size).limit(size)).all()
    return CustomerListOut(
        items=[_to_out(c) for c in items], total=total, page=page, size=size
    )


@router.get("/{customer_id}", response_model=CustomerOut)
def get_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "not found")
    return _to_out(c)


@router.put("/{customer_id}", response_model=CustomerOut)
def update_customer(
    customer_id: int,
    payload: CustomerUpdate,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.post("/{customer_id}/logo", response_model=CustomerOut)
async def upload_logo(
    customer_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "not found")
    content = await file.read()
    c.logo_path = save_logo(
        settings.logo_storage_dir,
        customer_id,
        file.content_type or "",
        content,
        settings.logo_max_bytes,
    )
    db.commit()
    db.refresh(c)
    return _to_out(c)


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: int,
    db: Session = Depends(get_db),
    _: AdminUser = Depends(require_super_admin),
):
    c = db.get(Customer, customer_id)
    if not c:
        raise HTTPException(404, "not found")
    # Block delete if the customer still owns projects (cascade would leak).
    if db.scalar(
        select(func.count()).select_from(Project).where(Project.customer_id == customer_id)
    ):
        raise HTTPException(400, "customer has related projects")
    # Soft-disable per spec §5.
    c.status = "disabled"
    db.commit()
    return {"ok": True}
