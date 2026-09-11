"""Shared helpers for agent info panel tests."""

from __future__ import annotations

from unittest.mock import patch

from rich.text import Text

from sase.ace.tui.keymaps import key_display_name, load_keymap_registry
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel

DEFAULT_GROUPING_KEY = key_display_name(
    load_keymap_registry({}).app.cycle_grouping_mode
)
DEFAULT_NEIGHBOR_KEY = key_display_name(load_keymap_registry({}).app.start_sibling_mode)


def collect_text(panel: AgentInfoPanel) -> str:
    captured: list[str] = []
    with patch.object(
        panel,
        "update",
        lambda text, **_kwargs: captured.append(text.plain),
    ):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def collect_rich_text(panel: AgentInfoPanel) -> Text:
    captured: list[Text] = []
    with patch.object(
        panel,
        "update",
        lambda text, **_kwargs: captured.append(text),
    ):
        panel._update_display()
    assert captured, "panel._update_display did not invoke self.update()"
    return captured[-1]


def style_for_plain_segment(text: Text, segment: str) -> str:
    start = text.plain.index(segment)
    end = start + len(segment)
    matching = [
        str(span.style)
        for span in text.spans
        if span.start <= start and span.end >= end
    ]
    assert matching, f"no Rich style span found for {segment!r}"
    return matching[-1]


def style_at_plain_index(text: Text, index: int) -> str:
    matching = [
        str(span.style) for span in text.spans if span.start <= index < span.end
    ]
    assert matching, f"no Rich style span found at index {index}"
    return matching[-1]


def stable_state_kwargs(**overrides: object) -> dict[str, object]:
    """Default kwargs for ``AgentInfoPanel.update_state``."""
    base: dict[str, object] = {
        "position": 0,
        "total": 5,
        "unread": 0,
        "asking": 0,
        "running": 2,
        "waiting": 0,
        "failed": 0,
        "read": 0,
        "sase_agent_count": 5,
        "starting": 0,
        "neighbor_count": 0,
        "countdown": 5,
        "interval": 5,
        "view_mode": "",
        "grouping_mode": "by project",
        "search_query": "",
        "runner_limit": 10,
        "runner_occupied_capacity": 2.0,
        "runner_queue_count": 0,
    }
    base.update(overrides)
    return base
