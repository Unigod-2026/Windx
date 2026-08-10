"""Pydantic schemas for the ``/api/auth`` endpoints.

Lives separately from ``app.schemas.customer`` because login is its own
narrow surface (``username + password`` in, ``token + user`` out) and
nothing else needs to share these models.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AdminRole, AdminStatus

_BCRYPT_MAX_BYTES = 72


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


LoginOut.model_rebuild()