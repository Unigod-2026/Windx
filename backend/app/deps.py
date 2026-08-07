"""Authentication / authorisation dependencies.

Task 4 only needs ``require_super_admin`` so customer CRUD can stay gated
behind a single role check. JWT verification is wired so a real token
issued by Task 6 can be used immediately; for now tests inject a token
whose ``sub`` claim is the ``AdminUser.id`` (the row must already exist
in the DB, which the test fixture creates).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models.customer import AdminUser
from app.models.enums import AdminRole, AdminStatus

_settings = get_settings()
_bearer = HTTPBearer(auto_error=True)


def get_current_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
    db: Session = Depends(get_db),
) -> AdminUser:
    try:
        payload = jwt.decode(
            creds.credentials,
            _settings.jwt_secret,
            algorithms=[_settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"invalid token: {exc}",
        ) from exc

    sub = payload.get("sub")
    if sub is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="missing sub"
        )

    user = db.get(AdminUser, int(sub))
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found"
        )
    return user


def require_super_admin(
    current: AdminUser = Depends(get_current_user),
) -> AdminUser:
    if current.role is not AdminRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="super admin required"
        )
    if current.status is not AdminStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="admin disabled"
        )
    return current
