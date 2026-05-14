"""Regression tests for the `]` AUTO-toggle stale-diff bug.

After cycling AUTO -> TOOLS -> INFO -> j/k -> AUTO, the file panel
must re-render for the currently selected agent rather than display the
stale content left over from when AUTO was last visible.
"""

from __future__ import annotations

import types
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_detail_panels import (
    AgentDetailPanelMixin,
    DetailPanelMode,
)


def _make_agent(cl_name: str, raw_suffix: str) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2024, 1, 1, 12, 0, 0),
        raw_suffix=raw_suffix,
    )


class _StubScroll:
    def __init__(self) -> None:
        self._classes: set[str] = set()

    def add_class(self, name: str) -> None:
        self._classes.add(name)

    def remove_class(self, name: str) -> None:
        self._classes.discard(name)

    def has_class(self, name: str) -> bool:
        return name in self._classes


def _build_detail(file_panel: Any) -> Any:
    """Construct a minimally-wired panel-mode mixin instance for testing."""
    detail = MagicMock(spec=AgentDetailPanelMixin)
    detail._panel_mode = DetailPanelMode.INFO
    detail._has_file_content = True
    detail._has_tools_content = False
    detail._current_agent = None
    detail._layout_swapped = False
    detail._file_count = 0
    detail._file_index = 0

    file_scroll = _StubScroll()
    file_scroll.add_class("hidden")
    tools_scroll = _StubScroll()
    tools_scroll.add_class("hidden")
    prompt_scroll = _StubScroll()
    prompt_scroll.add_class("expanded")
    tools_panel = MagicMock()

    by_id = {
        "#agent-file-scroll": file_scroll,
        "#agent-tools-scroll": tools_scroll,
        "#agent-tools-panel": tools_panel,
        "#agent-prompt-scroll": prompt_scroll,
        "#agent-file-panel": file_panel,
    }

    def _query_one(sel: str, *_args: Any, **_kwargs: Any) -> Any:
        return by_id[sel]

    detail.query_one = MagicMock(side_effect=_query_one)
    detail.call_after_refresh = MagicMock()
    detail._update_panel_indicators = MagicMock()
    detail._expand_prompt_only = MagicMock()
    detail._update_file_scroll_subtitle = MagicMock()

    detail._apply_panel_mode = types.MethodType(
        AgentDetailPanelMixin._apply_panel_mode, detail
    )
    return detail


def test_auto_branch_invalidates_file_panel_state_before_refresh() -> None:
    """Toggling back to AUTO must clear file_panel state so the next
    dispatch follows the full-reset path and re-renders for the new agent.
    """
    agent_a = _make_agent("a", "20240101120000")
    agent_b = _make_agent("b", "20240101130000")

    file_panel = MagicMock()
    file_panel._current_agent = agent_a
    file_panel._file_list = ["/tmp/a.diff"]

    captured: dict[str, Any] = {}

    def _record_update_display(agent: Agent, *_args: Any, **_kwargs: Any) -> None:
        captured["agent"] = agent
        captured["file_panel_current_agent"] = file_panel._current_agent
        captured["file_panel_file_list"] = list(file_panel._file_list)

    detail = _build_detail(file_panel)
    detail.update_display = MagicMock(side_effect=_record_update_display)

    detail._apply_panel_mode(DetailPanelMode.AUTO, agent_b)

    assert detail._panel_mode == DetailPanelMode.AUTO
    assert captured["agent"] is agent_b
    # The fix: file_panel state was invalidated *before* update_display ran,
    # so the file_panel's same-agent / same-file-list fast paths cannot
    # short-circuit and skip the re-render.
    assert captured["file_panel_current_agent"] is None
    assert captured["file_panel_file_list"] == []
