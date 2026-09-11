"""Molizhishu upstream proxy endpoints.

Currently a single read-only endpoint:

- ``GET /api/molizhishu/cities`` — wraps the upstream
  ``GET /eip-edge/ports/city-info`` call so the wizard's 「指定区域」
  dropdown can populate without exposing the upstream token to the
  browser. The response is cached in-process for 5 minutes because the
  supported-region list rarely changes and the wizard re-renders the
  dropdown on every step transition.

Why a router instead of just calling Molizhishu from the frontend?
The upstream ``Authorization: Bearer <token>`` header carries the
project's Molizhishu token (per
``https://github.com/molizhishu/molizhishu-api-pub/blob/main/docs/api/overview.md``),
which must
never reach the browser (see ``CLAUDE.md`` §Token 安全). Funnelling
the lookup through here keeps the token on the server side.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.deps import get_current_user
from app.models.customer import AdminUser
from app.services.molizhishu_client import MolizhishuClient

router = APIRouter(prefix="/api/molizhishu", tags=["molizhishu"])

# 5 minutes — the upstream's supported-region list is essentially static;
# caching cuts out ~12 upstream round-trips per wizard session without
# delaying the operator when the list does change.
_CACHE_TTL_SECONDS = 5 * 60

# Module-level cache shared across requests. ``threading.Lock`` keeps the
# TTL refresh race-free under the FastAPI threadpool; the cached payload
# itself is tiny (≈2 KB) so there's no memory pressure worth worrying about.
_cache_lock = threading.Lock()
_cache_payload: list[dict[str, Any]] | None = None
_cache_fetched_at: float = 0.0


def _is_cache_fresh() -> bool:
    return (
        _cache_payload is not None
        and (time.monotonic() - _cache_fetched_at) < _CACHE_TTL_SECONDS
    )


def _fetch_and_cache(client: MolizhishuClient) -> list[dict[str, Any]]:
    cities = client.list_cities_sync()
    with _cache_lock:
        globals()["_cache_payload"] = cities
        globals()["_cache_fetched_at"] = time.monotonic()
    return cities


@router.get("/cities")
def list_cities(_: AdminUser = Depends(get_current_user)):
    """Return Molizhishu's supported provinces.

    Shape (matches the wizard's single-select dropdown — only ``code`` /
    ``name`` are needed; city level is intentionally out of scope because
    the upstream's submit endpoint accepts only one ``regionCode`` per
    task and province is the most useful granularity for 「指定区域」
    comparison):

        [{"code": "410000", "name": "河南省"}, ...]

    On upstream failure (no token configured / 401 / 5xx) we return
    ``200 {"items": [], "warning": "..."}`` instead of a 5xx so the wizard
    renders an empty dropdown + inline retry message instead of a hard
    error. ``items=[]`` keeps the contract stable for the frontend.
    """
    settings = get_settings()
    if not settings.molizhishu_city_url:
        return {"items": [], "warning": "MOLIZHISHU_CITY_URL 未配置"}

    # Fast path: warm cache. No lock needed because we only read.
    if _is_cache_fresh():
        return {"items": _cache_payload, "warning": None}

    # Cold / stale path: build a client per request so token rotation in
    # the env takes effect on the next call without restarting.
    client = MolizhishuClient(
        base_url=settings.molizhishu_base_url,
        token=settings.molizhishu_token,
        timeout=settings.molizhishu_timeout_seconds,
    )
    try:
        cities = _fetch_and_cache(client)
    except Exception as exc:
        # Stale-while-error: if we have a stale payload from a previous
        # successful fetch, serve it with a warning so the operator can
        # still pick a region instead of being locked out by a transient
        # upstream blip.
        if _cache_payload is not None:
            return {
                "items": _cache_payload,
                "warning": f"upstream stale: {exc}",
            }
        # No prior payload — bubble the failure shape with an empty list.
        return {"items": [], "warning": f"upstream error: {exc}"}

    return {"items": cities, "warning": None}