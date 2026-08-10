"""Password hashing helpers.

Uses ``bcrypt`` directly instead of ``passlib``. ``passlib``'s bcrypt
handler is incompatible with ``bcrypt>=4`` (it reads ``bcrypt.__about__``
which 4.x removed), so wrapping ``bcrypt`` ourselves keeps both deps
declared in ``pyproject.toml`` but lets us sidestep that bug without
pinning an old bcrypt.

Bcrypt has a 72-byte input cap — reject longer passwords at the schema
layer (``LoginIn`` / ``AdminUserCreate``) so we never have to silently
truncate.
"""

from __future__ import annotations

import bcrypt

_BCRYPT_MAX_BYTES = 72


def hash_password(plain: str) -> str:
    raw = plain.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        raise ValueError(f"password exceeds {_BCRYPT_MAX_BYTES} bytes")
    return bcrypt.hashpw(raw, bcrypt.gensalt(rounds=10)).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash (e.g. not bcrypt at all) — treat as verification failure
        # rather than leaking that the stored hash is broken.
        return False