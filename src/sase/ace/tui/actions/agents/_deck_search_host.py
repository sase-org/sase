"""Deck-mode search host helpers for Agents metadata search."""

from __future__ import annotations

from typing import Any


def deck_search_panel(app: Any) -> Any | None:
    """Return the focused deck panel search should target, or None."""
    try:
        from ...widgets import AgentDetail

        detail = app.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined]
    except Exception:
        return None
    if not bool(getattr(detail, "decks_enabled", False)):
        return None
    try:
        area = detail.deck_area
        return area.focused_panel()
    except Exception:
        return None


def deck_structural_exit_keys(app: Any) -> tuple[str, ...]:
    """Build committed-search passthrough keys from the live keymap."""
    try:
        from ...keymaps import split_key_alternatives

        registry = getattr(app, "_keymap_registry", None)
        app_keys = getattr(registry, "app", None)
        if app_keys is None:
            return ()
        ids = (
            "next_deck",
            "prev_deck",
            "next_deck_card",
            "prev_deck_card",
            "toggle_deck_split_below",
            "toggle_deck_split_right",
            "toggle_deck_focus",
            "grow_deck_panel",
            "shrink_deck_panel",
            "edit_panel",
        )
        keys: list[str] = []
        for key_id in ids:
            try:
                configured = getattr(app_keys, key_id)
            except Exception:
                continue
            try:
                keys.extend(split_key_alternatives(configured))
            except Exception:
                continue
        return tuple(keys)
    except Exception:
        return ()


__all__ = ["deck_search_panel", "deck_structural_exit_keys"]
