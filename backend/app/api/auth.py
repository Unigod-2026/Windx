"""Authentication helper endpoints.

Task 6 exposes ``GET /api/auth/me`` so the React frontend can decide whether
to render the customer-management surface (super_admin) or scope itself to
a single ``customer_id`` (customer_admin). Authentication is delegated to
``app.deps.get_current_user``; this module only shapes the response.

A disabled admin still authenticates (the JWT decodes) but ``/me`` rejects
them with 403 so the frontend forces a logout on its first authenticated
call. ``require_super_admin`` enforces the same rule for write paths.

``POST /api/auth/login`` (added with the frontend's Login page) accepts
``{username, password}`` and returns a signed JWT plus the user row.
Unknown username and wrong password share the same 401 to avoid leaking
which usernames exist; a disabled account gets 403 so the frontend can
distinguish "wrong creds" from "account locked".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import create_access_token, get_current_user
from app.models.common import now_local
from app.models.customer import AdminUser
from app.models.enums import AdminStatus
from app.schemas.auth import LoginIn, LoginOut
from app.services.password import verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=LoginOut)
def login(payload: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(AdminUser).where(AdminUser.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        # Same error for both branches so we don't leak whether a username exists.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid username or password",
        )
    if user.status is not AdminStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin disabled"
        )

    user.last_login_at = now_local()
    db.commit()
    db.refresh(user)

    return LoginOut(token=create_access_token(user.id), user=user)


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