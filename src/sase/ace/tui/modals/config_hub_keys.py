"""Forward Config sub-tab cycling from focused filter inputs."""

from __future__ import annotations

from typing import Any

from textual.events import Key


def handle_config_hub_bracket_key(widget: Any, event: Key) -> bool:
    """Cycle Config sub-tabs when ``[`` / ``]`` arrive in an embedded filter.

    Returns True when the event was consumed. Standalone panes leave
    brackets as ordinary input.
    """
    if event.key not in ("left_square_bracket", "right_square_bracket"):
        return False
    hub = _nearest_config_hub(widget)
    if hub is None:
        return False
    event.stop()
    event.prevent_default()
    if event.key == "left_square_bracket":
        hub.action_cycle_subtab_reverse()
    else:
        hub.action_cycle_subtab()
    return True


def _nearest_config_hub(widget: Any) -> Any | None:
    """Return the enclosing Config hub, if this widget is mounted in one."""
    from .config_hub_pane import ConfigHubPane

    node: object | None = getattr(widget, "parent", None)
    while node is not None:
        if isinstance(node, ConfigHubPane):
            return node
        node = getattr(node, "parent", None)
    return None


__all__ = ["handle_config_hub_bracket_key"]
