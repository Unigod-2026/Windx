"""Pydantic schemas for the Customer / AdminUser API surface.

These mirror ``app.models.customer`` but strip server-managed fields
(``id``, ``created_at``, ``updated_at``) from the request side and add a
``logo_url`` derived field to the response.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AdminRole, AdminStatus, CustomerStatus


class CustomerCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    code: str = Field(..., min_length=1, max_length=64)
    contact: str | None = Field(default=None, max_length=128)


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    contact: str | None = Field(default=None, max_length=128)
    status: CustomerStatus | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    code: str
    contact: str | None
    status: CustomerStatus
    logo_path: str | None
    logo_url: str | None = None
    created_at: datetime
    updated_at: datetime


class CustomerListOut(BaseModel):
    items: list[CustomerOut]
    total: int
    page: int
    size: int


class AdminUserCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password_hash: str = Field(..., min_length=1, max_length=255)
    display_name: str | None = Field(default=None, max_length=128)
    role: AdminRole = AdminRole.SUPER_ADMIN
    status: AdminStatus = AdminStatus.ACTIVE
    customer_id: int | None = None


class AdminUserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    display_name: str | None
    role: AdminRole
    status: AdminStatus
    customer_id: int | None
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime
