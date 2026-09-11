"""Public configuration surface for the frontend.

Houses values that the UI needs but aren't worth modelling as full
entities: today that's the per-call LLM price used by the edit-project
modal's 「预计费用」 footer. Auth-free on purpose — there's nothing
sensitive here, and gating it would force the modal to wait for the
``/auth/me`` round-trip before it could draw the cost number.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(prefix="/api/config", tags=["config"])


@router.get("/llm-pricing")
def get_llm_pricing() -> dict[str, float | str]:
    settings = get_settings()
    return {
        "cost_per_call": settings.api_cost_per_call,
        "currency": "CNY",
        "unit": "元",
    }
