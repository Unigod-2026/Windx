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

2026-10-08 扩展:SettingsPane 个人中心三件套(邮箱 / 手机 / 通知偏好)
真实落库。新增两个 endpoint:
- ``PATCH /api/auth/me`` —— 更新 email / phone / notification_prefs。
  super_admin 强制 readonly email / phone(只许改 display_name,这里
  暂不开放 display_name,留 TODO),保证「自身客户」永远绑死为 NULL。
- ``POST /api/auth/change-password`` —— 校验旧密码 + 新密码强度后
  写入 password_hash。
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import create_access_token, get_current_user
from app.models.common import now_local
from app.models.customer import AdminUser
from app.models.enums import AdminRole, AdminStatus
from app.schemas.auth import (
    ChangePasswordIn,
    LoginIn,
    LoginOut,
    LoginUserOut,
    ProfilePatch,
    parse_notif_prefs,
)
from app.services.password import hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _serialize_user(user: AdminUser) -> dict:
    """把 AdminUser ORM 序列化成 ``/login`` / ``/me`` 通用 dict。

    集中处理 notification_prefs 的 JSON 解析,避免每个 endpoint 重复写。"""
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role.value,
        "status": user.status.value,
        "customer_id": user.customer_id,
        "last_login_at": user.last_login_at,
        "email": user.email,
        "phone": user.phone,
        "notification_prefs": parse_notif_prefs(user.notification_prefs),
    }


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

    return LoginOut(token=create_access_token(user.id), user=LoginUserOut(**_serialize_user(user)))


@router.get("/me")
def me(user: AdminUser = Depends(get_current_user)):
    if user.status is not AdminStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin disabled")
    return _serialize_user(user)


@router.patch("/me")
def patch_me(
    payload: ProfilePatch,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.status is not AdminStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin disabled")

    # super_admin 永远绑死为「无客户」:不允许通过 PATCH /me 改 customer_id
    # (本 schema 也没暴露这个字段),邮箱 / 手机也强制 readonly —— 风控要求
    # super_admin 身份必须由后台手动调整,不允许通过自助修改覆盖。
    patched = payload.model_dump(exclude_unset=True)
    if user.role is AdminRole.SUPER_ADMIN:
        forbidden = [k for k in ("email", "phone") if k in patched]
        if forbidden:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="超级管理员不可修改邮箱 / 手机号",
            )

    # email / phone / notification_prefs 都是声明的字段,逐项写回 ORM。
    if "email" in patched:
        user.email = patched["email"]
    if "phone" in patched:
        user.phone = patched["phone"]
    if "notification_prefs" in patched:
        np = patched["notification_prefs"]
        user.notification_prefs = (
            json.dumps(np, ensure_ascii=False) if np is not None else None
        )

    db.commit()
    db.refresh(user)
    return _serialize_user(user)


@router.post("/change-password")
def change_password(
    payload: ChangePasswordIn,
    user: AdminUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if user.status is not AdminStatus.ACTIVE:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin disabled")
    if not verify_password(payload.old_password, user.password_hash):
        # 旧密码错:401(不是 422,语义就是「认证失败」,前端可弹「当前密码不正确」)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="当前密码不正确",
        )
    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"ok": True}
