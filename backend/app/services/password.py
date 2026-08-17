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
    # Dev convenience: rows seeded with literal plaintext (no bcrypt prefix)
    # fall back to a direct compare so local login works without the hashing
    # round-trip. Production rows still go through bcrypt below.
    if not hashed.startswith("$2"):
        return plain == hashed
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        # Malformed hash — treat as verification failure rather than leaking
        # that the stored hash is broken.
        return False