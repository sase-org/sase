"""Shared helper to pin deck tests to paged rendering."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.agent_decks_settings import AgentDecksSettings


def pin_paged(app: Any) -> None:
    """Pin ``app`` to always-paged deck rendering for paged-behavior tests."""
    app._agent_decks_settings = AgentDecksSettings(spread_max_screens=0)


__all__ = ["pin_paged"]
