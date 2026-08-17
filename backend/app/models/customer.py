"""Customer & admin user ORM models.

Covers ``geo_customers`` and ``geo_admin_users``. Customers own projects and are
the multi-tenant boundary; admin users either belong to a single customer
(``customer_admin``) or are unscoped super admins.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm import foreign

from app.db import Base
from app.models.common import created_at_column, updated_at_column
from app.models.enums import AdminRole, AdminStatus, CustomerStatus

if TYPE_CHECKING:
    from app.models.project import Project


class Customer(Base):
    __tablename__ = "geo_customers"
    __table_args__ = (UniqueConstraint("code", name="uq_customers_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    logo_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[CustomerStatus] = mapped_column(
        Enum(
            CustomerStatus,
            name="customer_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=CustomerStatus.ACTIVE,
    )
    created_at: Mapped["DateTime"] = created_at_column()
    updated_at: Mapped["DateTime"] = updated_at_column()

    projects: Mapped[list["Project"]] = relationship(
        "Project",
        primaryjoin="foreign(Project.customer_id) == Customer.id",
        viewonly=True,
    )
    admin_users: Mapped[list["AdminUser"]] = relationship(
        "AdminUser",
        primaryjoin="foreign(AdminUser.customer_id) == Customer.id",
        viewonly=True,
    )

    def __repr__(self) -> str:
        return f"<Customer id={self.id} code={self.code!r} status={self.status!r}>"


class AdminUser(Base):
    __tablename__ = "geo_admin_users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_admin_users_username"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[AdminRole] = mapped_column(
        Enum(
            AdminRole,
            name="admin_role",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=AdminRole.SUPER_ADMIN,
    )
    status: Mapped[AdminStatus] = mapped_column(
        Enum(
            AdminStatus,
            name="admin_status",
            values_callable=lambda enum_cls: [m.value for m in enum_cls],
        ),
        nullable=False,
        default=AdminStatus.ACTIVE,
    )
    # Plain column (no FK) — see CLAUDE.md "外键约定". Deleting a Customer
    # row leaves AdminUser rows intact; the API layer enforces tenancy.
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_login_at: Mapped["DateTime | None"] = mapped_column(DateTime, nullable=True)
    created_at: Mapped["DateTime"] = created_at_column()
    updated_at: Mapped["DateTime"] = updated_at_column()

    customer: Mapped["Customer | None"] = relationship(
        "Customer",
        primaryjoin="foreign(AdminUser.customer_id) == Customer.id",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<AdminUser id={self.id} username={self.username!r} role={self.role!r}>"
