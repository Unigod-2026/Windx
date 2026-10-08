"""Pydantic schemas for the ``/api/auth`` endpoints.

Lives separately from ``app.schemas.customer`` because login is its own
narrow surface (``username + password`` in, ``token + user`` out) and
nothing else needs to share these models.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import AdminRole, AdminStatus

_BCRYPT_MAX_BYTES = 72
# 通知偏好 4 个开关;后端只校验 key 集合,具体值类型(bool)在 application 层把控。
NOTIF_KEYS = {"mention", "drop", "report", "system"}
# email 简单正则 —— 不做 RFC 5322 完整校验,避免用户在「设置」页改个邮箱
# 就要面对一长串「邮箱格式不正确」报错;只要「@ 之前非空 + @ + 之后有点」就行。
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LoginIn(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=_BCRYPT_MAX_BYTES)


class LoginOut(BaseModel):
    token: str
    user: "LoginUserOut"


class LoginUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None
    role: AdminRole
    status: AdminStatus
    customer_id: int | None
    last_login_at: datetime | None
    # 2026-10-08 新增:「个人中心」三件套 —— SettingsPane 真实落库用。
    email: str | None = None
    phone: str | None = None
    notification_prefs: dict[str, bool] | None = None


class ProfilePatch(BaseModel):
    """PATCH /api/auth/me body —— 局部更新,只校验出现的字段。"""
    email: str | None = Field(default=None, max_length=128)
    phone: str | None = Field(default=None, max_length=32)
    notification_prefs: dict[str, bool] | None = None

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if not EMAIL_RE.match(v):
            raise ValueError("邮箱格式不正确")
        return v

    @field_validator("notification_prefs")
    @classmethod
    def _check_notif(cls, v: dict[str, bool] | None) -> dict[str, bool] | None:
        if v is None:
            return None
        if set(v.keys()) != NOTIF_KEYS:
            raise ValueError(
                f"notification_prefs 必须恰好包含 {sorted(NOTIF_KEYS)} 四个键"
            )
        if not all(isinstance(x, bool) for x in v.values()):
            raise ValueError("notification_prefs 的每个值必须是 bool")
        return v


class ChangePasswordIn(BaseModel):
    old_password: str = Field(..., min_length=1, max_length=_BCRYPT_MAX_BYTES)
    new_password: str = Field(..., min_length=8, max_length=_BCRYPT_MAX_BYTES)

    @field_validator("new_password")
    @classmethod
    def _check_pwd_strength(cls, v: str) -> str:
        if not re.search(r"[A-Za-z]", v):
            raise ValueError("新密码必须包含字母")
        if not re.search(r"\d", v):
            raise ValueError("新密码必须包含数字")
        return v


# Helper for /me / login response:把 model 上的 notification_prefs 字符串
# 解析成 dict 返回;解析失败(None / 非法 JSON)统一返 None,不让一个坏值
# 把整个 /me 请求 500 掉。
def parse_notif_prefs(raw: str | None) -> dict[str, bool] | None:
    if not raw:
        return None
    try:
        obj: Any = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    if set(obj.keys()) != NOTIF_KEYS:
        return None
    if not all(isinstance(x, bool) for x in obj.values()):
        return None
    return {k: bool(obj[k]) for k in NOTIF_KEYS}


LoginOut.model_rebuild()
