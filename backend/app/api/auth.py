"""Authentication helper endpoints.

Task 6 exposes ``GET /api/auth/me`` so the React frontend can decide whether
to render the customer-management surface (super_admin) or scope itself to
a single ``customer_id`` (customer_admin). Authentication is delegated to
``app.deps.get_current_user``; this module only shapes the response.

A disabled admin still authenticates (the JWT decodes) but ``/me`` rejects
them with 403 so the frontend forces a logout on its first authenticated
call. ``require_super_admin`` enforces the same rule for write paths.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import get_current_user
from app.models.customer import AdminUser
from app.models.enums import AdminStatus

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/me")
def me(user: AdminUser = Depends(get_current_user)):
    if user.status is not AdminStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin disabled")
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "customer_id": user.customer_id,
        "status": user.status.value,
    }