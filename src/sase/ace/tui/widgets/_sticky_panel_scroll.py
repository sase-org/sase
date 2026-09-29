"""Shared half-page scroll helpers for Agents sticky panels."""

from __future__ import annotations

from typing import Any


def sticky_panel_can_scroll(panel: Any) -> bool:
    """Return whether a sticky panel has overflow to scroll."""
    try:
        if not bool(getattr(panel, "is_mounted", False)):
            return False
    except Exception:
        return False
    try:
        if panel.has_class("hidden"):
            return False
    except Exception:
        return False
    try:
        if not bool(panel.display):
            return False
    except Exception:
        pass
    try:
        if int(panel.max_scroll_y) <= 0:
            return False
    except Exception:
        return False
    return True


def scroll_sticky_panel_half_page(panel: Any, direction: int) -> bool:
    """Scroll half the visible panel height and claim the key."""
    try:
        height = int(panel.scrollable_content_region.height)
    except Exception:
        height = 0
    step = max(1, height // 2)
    try:
        delta = step if direction >= 0 else -step
        panel.scroll_relative(y=delta, animate=False)
    except Exception:
        return False
    return True


__all__ = ["scroll_sticky_panel_half_page", "sticky_panel_can_scroll"]
