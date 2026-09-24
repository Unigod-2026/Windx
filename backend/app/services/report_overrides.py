"""Manual-override merge helper — shared by auth and public report endpoints.

The editable report feature lets an operator overwrite the template's
narrative-prose fields (declarations in ``report_templates.TEMPLATE_FIELDS``)
plus the four nested blocks under ``snapshot.weekly_summary``. The
override dict is persisted on ``geo_reports.manual_overrides``; both the
auth-gated preview endpoint and the public preview endpoint must apply
the same merge logic so what the operator sees is what the recipient
sees.

Living here (not in either router file) so adding a third caller
(e.g. a render-on-publish path) doesn't drift the merge rules.
"""

from __future__ import annotations

from app.services.report_templates import TEMPLATE_FIELDS


def merge_overrides(snapshot: dict, manual_overrides: dict) -> dict:
    """Overlay operator-edited narrative content onto a template snapshot.

    For each editable field declared in ``TEMPLATE_FIELDS``, prefer the
    operator's value in ``manual_overrides`` over the template's output
    (which is currently always None for these fields — the template no
    longer computes narrative prose).

    Dead keys in ``manual_overrides`` (template removed the field but
    the operator saved before) are ignored — we only read keys declared
    in the template's editable-field list.
    """
    if not manual_overrides:
        return snapshot
    editable_keys = {
        f["key"]
        for fields in TEMPLATE_FIELDS.values()
        for f in fields
    }
    for k, v in manual_overrides.items():
        if k not in editable_keys:
            continue
        snapshot[k] = v
    # Also overlay the 4-block weekly_summary nested object.
    nested_overrides = {
        "core_finding": manual_overrides.get("weekly_core_finding"),
        "platform_dynamic": manual_overrides.get("weekly_platform_dynamic"),
        "content_result": manual_overrides.get("weekly_content_result"),
        "scene_coverage": manual_overrides.get("weekly_scene_coverage"),
    }
    if "weekly_summary" in snapshot and isinstance(snapshot["weekly_summary"], dict):
        for k, v in nested_overrides.items():
            if v is not None:
                snapshot["weekly_summary"][k] = v
    return snapshot
