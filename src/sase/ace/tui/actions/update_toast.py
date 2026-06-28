"""Startup update-available toast for the ace TUI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from textual.markup import escape

from sase.config.core import load_merged_config
from sase.updates import UpdateStatus, get_cached_update_status

from ..modals.config_center_modal import (
    center_tab_accent,
    center_tab_shortcut,
)

if TYPE_CHECKING:
    from sase.updates import OutdatedComponent

log = logging.getLogger(__name__)

_UPDATE_GLYPH = "↑"
_TOAST_TITLE = f"{_UPDATE_GLYPH} Updates available"
_TOAST_TIMEOUT_SECONDS = 12.0
_DEFAULT_CHECK_TTL_HOURS = 24.0
_MAX_COMPONENT_LINES = 3


@dataclass(frozen=True)
class _UpdateToastConfig:
    """Config values controlling the startup update toast."""

    startup_toast: bool = True
    check_ttl_hours: float = _DEFAULT_CHECK_TTL_HOURS


class UpdateToastMixin:
    """Mixin that schedules and renders the startup update-available toast."""

    _update_toast_shown: bool

    def _schedule_startup_update_toast_check(self) -> None:
        """Schedule the update-status check after first paint."""
        try:
            self.run_worker(  # type: ignore[attr-defined]
                cast(Any, self._run_startup_update_toast_check),
                thread=True,
                exclusive=False,
                group="startup-loads",
            )
        except Exception:
            log.debug("Failed to schedule startup update-status check", exc_info=True)

    def _run_startup_update_toast_check(self) -> None:
        """Run the cached update-status check in a worker thread."""
        try:
            config = _load_update_toast_config()
            if not config.startup_toast:
                return
            status = get_cached_update_status(
                ttl_seconds=max(0.0, config.check_ttl_hours) * 60 * 60
            )
            if status is None or not status.has_updates:
                return
            self.call_from_thread(  # type: ignore[attr-defined]
                self._show_startup_update_toast,
                status,
            )
        except Exception:
            log.debug("Startup update-status check failed", exc_info=True)

    def _show_startup_update_toast(self, status: UpdateStatus) -> None:
        """Show the startup update toast once per TUI session."""
        if getattr(self, "_update_toast_shown", False):
            return
        if not status.has_updates:
            return
        self._update_toast_shown = True
        self.notify(  # type: ignore[attr-defined]
            _format_update_toast_message(status),
            title=_TOAST_TITLE,
            severity="information",
            timeout=_TOAST_TIMEOUT_SECONDS,
            markup=True,
        )


def _load_update_toast_config() -> _UpdateToastConfig:
    """Load the startup update-toast config from merged SASE config."""
    data = load_merged_config()
    ace = data.get("ace")
    if not isinstance(ace, dict):
        return _UpdateToastConfig()
    updates = ace.get("updates")
    if not isinstance(updates, dict):
        return _UpdateToastConfig()
    return _UpdateToastConfig(
        startup_toast=_coerce_bool(updates.get("startup_toast"), default=True),
        check_ttl_hours=_coerce_positive_float(
            updates.get("check_ttl_hours"),
            default=_DEFAULT_CHECK_TTL_HOURS,
        ),
    )


def _format_update_toast_message(status: UpdateStatus) -> str:
    """Build the Rich/Textual markup body for the update toast."""
    accent = center_tab_accent("updates") or "#AF87FF"
    count = status.count
    noun = "update" if count == 1 else "updates"
    lines = [f"[bold {accent}]{count} {noun}[/] available"]
    for component in status.components[:_MAX_COMPONENT_LINES]:
        lines.append(_component_line(component))
    overflow = count - _MAX_COMPONENT_LINES
    if overflow > 0:
        lines.append(f"…and {overflow} more")
    lines.append(_shortcut_line(accent))
    return "\n".join(lines)


def _component_line(component: OutdatedComponent) -> str:
    installed = component.installed_version or "unknown"
    latest = component.latest_version or "unknown"
    return f"• {escape(component.display_name)}  {escape(installed)} → {escape(latest)}"


def _shortcut_line(accent: str) -> str:
    shortcut = center_tab_shortcut("updates")
    if shortcut is None:
        return (
            f"Open the [bold {accent}]Updates[/] tab in the SASE Admin Center (press #)"
        )
    return (
        f"Press [bold {accent}]#[/] then [bold {accent}]{shortcut}[/] "
        "to open the Updates tab"
    )


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off", "none", "disabled"}:
            return False
    return default


def _coerce_positive_float(value: object, *, default: float) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value) if value >= 0 else default
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return default
        return parsed if parsed >= 0 else default
    return default


__all__ = ["UpdateToastMixin"]
