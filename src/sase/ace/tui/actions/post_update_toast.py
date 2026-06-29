"""Post-restart update confirmation toast for the ace TUI."""

from __future__ import annotations

import logging

from textual.markup import escape

from sase.ace.update_receipt import (
    UpdateToastReceipt,
    UpdateVersionTransition,
    read_and_clear_pending_update_toast,
)

from ..modals.config_center_modal import center_tab_accent
from . import update_toast

log = logging.getLogger(__name__)

_SUCCESS_GLYPH = "✓"
_TOAST_TIMEOUT_SECONDS = 10.0


class PostUpdateToastMixin:
    """Mixin that renders a one-shot update confirmation after ACE restarts."""

    _update_toast_shown: bool

    def _maybe_show_post_update_toast(self) -> None:
        """Consume and render the pending post-update toast receipt, if present."""
        try:
            receipt = read_and_clear_pending_update_toast()
        except Exception:
            log.debug("Failed to consume pending update toast", exc_info=True)
            return
        if receipt is None:
            return

        try:
            config = update_toast._load_update_toast_config()
        except Exception:
            log.debug("Failed to load post-update toast config", exc_info=True)
            config = update_toast._UpdateToastConfig()
        if not config.post_update_toast:
            return

        self._update_toast_shown = True
        try:
            self.notify(  # type: ignore[attr-defined]
                _format_post_update_toast_message(receipt),
                title=_format_post_update_toast_title(receipt),
                severity="information",
                timeout=_TOAST_TIMEOUT_SECONDS,
                markup=True,
            )
        except Exception:
            log.debug("Failed to show post-update toast", exc_info=True)


def _format_post_update_toast_title(receipt: UpdateToastReceipt) -> str:
    primary = receipt.primary
    if primary is not None and primary.new:
        return f"{_SUCCESS_GLYPH} Updated to sase {primary.new}"
    return f"{_SUCCESS_GLYPH} SASE updated"


def _format_post_update_toast_message(receipt: UpdateToastReceipt) -> str:
    accent = center_tab_accent("updates") or "#AF87FF"
    lines: list[str] = []
    if receipt.primary is not None:
        lines.append(_primary_line(receipt.primary, accent))
    for plugin in receipt.plugins:
        lines.append(_plugin_line(plugin))
    if receipt.plugin_overflow > 0:
        lines.append(f"…and {receipt.plugin_overflow} more")
    tail = _tail_line(receipt)
    if tail:
        lines.append(tail)
    return "\n".join(lines)


def _primary_line(transition: UpdateVersionTransition, accent: str) -> str:
    old = escape(transition.old or "unknown")
    new = escape(transition.new or "unknown")
    name = escape(transition.name)
    return f"[bold {accent}]{name}[/]  [dim]{old}[/] [dim]→[/] [bold green]{new}[/]"


def _plugin_line(transition: UpdateVersionTransition) -> str:
    old = escape(transition.old or "unknown")
    new = escape(transition.new or "unknown")
    name = escape(transition.name)
    return f"• {name}  [dim]{old} →[/] [green]{new}[/]"


def _tail_line(receipt: UpdateToastReceipt) -> str:
    parts: list[str] = []
    if receipt.dependency_count > 0:
        noun = "dependency" if receipt.dependency_count == 1 else "dependencies"
        parts.append(f"+{receipt.dependency_count} {noun}")
    parts.append("Reloaded into the new version.")
    return f"[dim]{' · '.join(parts)}[/]"


__all__ = ["PostUpdateToastMixin"]
