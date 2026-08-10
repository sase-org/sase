"""Notification tab configuration checks for ``sase doctor``."""

from __future__ import annotations

from rich.cells import cell_len

from sase.config import load_merged_config
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.checks_config_common import MAX_DETAIL_ROWS
from sase.notification_gates.model_validation import GateError, validate_icon


_MAX_TAB_ICON_CELLS = 2


def check_config_notification_tabs() -> DiagnosticCheck:
    """Warn when configured notification tabs explicitly share an icon."""
    config = load_merged_config()
    ace = config.get("ace", {})
    tabs = ace.get("notification_tabs", {}) if isinstance(ace, dict) else {}
    if not isinstance(tabs, dict):
        tabs = {}

    icons: dict[str, list[str]] = {}
    configured_icon_count = 0
    for key, entry in sorted(tabs.items(), key=lambda item: str(item[0])):
        if not isinstance(key, str) or not isinstance(entry, dict):
            continue
        icon = _sanitize_configured_icon(entry.get("icon", ""))
        if not icon:
            continue
        configured_icon_count += 1
        icons.setdefault(icon, []).append(key)

    problems = [
        f"icon {icon!r} is configured by notification tabs: {', '.join(keys)}"
        for icon, keys in sorted(icons.items(), key=lambda item: item[0])
        if len(keys) > 1
    ]
    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        f"{len(problems)} duplicate notification tab icon(s) configured"
        if problems
        else f"{configured_icon_count} configured notification tab icon(s) are unique"
    )
    next_steps = (
        (
            "Give each configured `ace.notification_tabs.<key>.icon` a distinct glyph "
            "or accept that those compact tabs will share an explicit icon.",
        )
        if problems
        else ()
    )

    return DiagnosticCheck(
        id="config.notification_tabs",
        group="config",
        status=status,
        title="Notification tab icons",
        summary=summary,
        details=tuple(problems)[:MAX_DETAIL_ROWS],
        next_steps=next_steps,
        data={
            "configured_icon_count": configured_icon_count,
            "duplicate_count": len(problems),
            "duplicates": problems,
        },
    )


def _sanitize_configured_icon(raw: object) -> str:
    try:
        icon = validate_icon(raw, "icon")
    except GateError:
        return ""
    if icon is None or cell_len(icon) > _MAX_TAB_ICON_CELLS:
        return ""
    return icon
