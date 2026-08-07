"""Customer logo file storage.

Writes validated image bytes to ``{storage_dir}/{customer_id}.{ext}`` and
returns the path that should be stored in ``geo_customers.logo_path``.
The DB only stores the *relative* path (``logos/{filename}``) — the
absolute root comes from ``settings.logo_storage_dir`` at read time, so
the deployment can relocate the logo directory without rewriting rows.

Validation lives here (not in the API layer) so any future caller — a
seed script, a CLI importer, a test fixture — gets the same guarantees.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException

# content_type -> file extension (with leading dot, lowercased).
ALLOWED_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


def save_logo(
    storage_dir: str,
    customer_id: int,
    content_type: str,
    content: bytes,
    max_bytes: int,
) -> str:
    """Persist ``content`` as the customer's logo.

    Returns the relative path that should be stored in the DB
    (``logos/{filename}``). Raises ``HTTPException`` on invalid type or
    oversize upload.
    """
    ext = ALLOWED_TYPES.get(content_type)
    if ext is None:
        raise HTTPException(400, f"unsupported content type: {content_type}")
    if len(content) > max_bytes:
        raise HTTPException(413, "logo too large")

    root = Path(storage_dir)
    root.mkdir(parents=True, exist_ok=True)
    filename = f"{customer_id}{ext}"
    (root / filename).write_bytes(content)
    return f"logos/{filename}"
