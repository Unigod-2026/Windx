"""Server-side mirror of the frontend's platform label dictionary.

The frontend keeps its display labels in ``wizardConfig.ts`` / the
``platforms.ts`` helpers so it can match the model card colors.
On the server we only need the human-readable Chinese name to fill in
``platform_label`` for the report snapshot — we don't have to deal with
``delivery_mode`` / ``thinking_mode`` here because the report groups
by raw ``Subtask.platform`` only.

Single source of truth lives in this module.  The frontend reads its
own copy (``WIZARD_MODELS``); if a new model is added, **both** files
need an entry until we have time to consolidate.
"""

from __future__ import annotations

# Display labels for raw ``Subtask.platform`` values.
# Compound rows like ``doubao_mobile`` carry the ``_mobile`` suffix —
# the helper below strips it before lookup so both ``doubao`` and
# ``doubao_mobile`` render as 「豆包」.
_LABELS: dict[str, str] = {
    "doubao": "豆包",
    "doubao_mobile": "豆包",
    "yuanbao": "元宝",
    "yuanbao_mobile": "元宝",
    "qianwen": "千问",
    "qianwen_mobile": "千问",
    "kimi": "Kimi",
    "kimi_mobile": "Kimi",
    "deepseek": "DeepSeek",
    "deepseek_mobile": "DeepSeek",
    "baiduai": "文心",
    "baidu": "文心",  # legacy alias
    "baidu_mobile": "文心",
    "antafu": "蚂蚁阿福",
    "chatgpt": "ChatGPT",
}

# 列头配色 —— 与前端 ``wizardConfig.ts`` 的 ``WIZARD_MODELS[].color`` 保持
# 同步(加新模型时两处都要改,口径同 ``_LABELS``)。导出 xlsx 的「提及率」
# sheet 用它给平台列表头上色,和 UI 里模型卡片的颜色对得上。
_COLORS: dict[str, str] = {
    "doubao": "#3f6bc4",
    "yuanbao": "#c9803a",
    "qianwen": "#3d9070",
    "kimi": "#8250bd",
    "deepseek": "#2b8b9b",
    "baiduai": "#b4487e",
    "antafu": "#8c3a2c",
    "chatgpt": "#4a8e84",
}

#: 未知平台的中性底色。
DEFAULT_COLOR = "#2F3A4F"


def platform_label_for_code(raw: str | None) -> str:
    """Return the Chinese display name for a ``Subtask.platform`` value.

    Falls back to the raw string when the code is unknown — same
    behaviour as the frontend ``platformLabel`` helper so a newly
    supported model still renders *something* rather than going blank.
    """
    if not raw:
        return "未知"
    if raw in _LABELS:
        return _LABELS[raw]
    stripped = raw.removesuffix("_mobile")
    if stripped in _LABELS:
        return _LABELS[stripped]
    return raw


def platform_color_for_code(raw: str | None) -> str:
    """Return the hex colour for a platform code.

    Falls back to :data:`DEFAULT_COLOR` for unknown codes so a newly
    supported model still renders a legible header instead of crashing
    the export.
    """
    if not raw:
        return DEFAULT_COLOR
    if raw in _COLORS:
        return _COLORS[raw]
    stripped = raw.removesuffix("_mobile")
    return _COLORS.get(stripped, DEFAULT_COLOR)
