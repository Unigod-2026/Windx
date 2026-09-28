"""Admin endpoints for report-templates management.

Currently a single endpoint:

- ``POST /api/admin/report-templates/reload`` — force a re-read of
  ``backend/configs/report_settings.json`` so an operator can edit
  template display metadata and have it visible without restarting
  the API process.

Why a dedicated router (not folded into the existing ``reports``
router): the reload endpoint sits in the ``/api/admin/`` URL space
that the rest of the app reserves for operator actions, not user
actions. Keeping it separate makes the contract self-evident and
avoids mixing auth scope with the public/templates path on
``reports``.

Auth: gated by the same ``get_current_user`` dependency as the rest
of the app. We deliberately do NOT limit to ``super_admin`` here —
the templates metadata is non-sensitive display config, and we may
want a customer_admin to trigger a reload after editing the file
on their behalf. If that becomes a real concern, swap to
``RequireSuperAdmin`` (already in scope).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_current_user
from app.models.customer import AdminUser
from app.services import report_settings

router = APIRouter(tags=["admin-report-templates"])


@router.post("/api/admin/report-templates/reload")
def reload_report_templates(
    user: AdminUser = Depends(get_current_user),
):
    """Drop the cached ``report_settings.json`` contents and re-read
    from disk. Returns a small summary so the operator can see what
    got picked up.
    """
    cache = report_settings.reload_cache()
    return {
        "reloaded": True,
        "baseline_count": len(cache.baselines),
        "template_count": len(cache.templates),
    }
