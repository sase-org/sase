"""Shared helpers for the agent display mixins."""

from __future__ import annotations

from typing import Literal

# Type alias for tab names
TabName = Literal["changespecs", "agents", "axe"]

#: id of the untagged "main" panel — kept stable across panel set changes
#: so existing callers (loading shim, prompt-bar mount, tests) continue to
#: work without knowing about the dynamic side panels.
_MAIN_PANEL_ID = "agent-list-panel"


def panel_widget_id(panel_idx: int) -> str:
    """Return the AgentList widget id for the panel at *panel_idx*.

    Index 0 is the untagged main pane; tag panels follow.
    """
    if panel_idx == 0:
        return _MAIN_PANEL_ID
    return f"{_MAIN_PANEL_ID}-{panel_idx}"
