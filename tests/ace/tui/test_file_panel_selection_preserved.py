"""Tests that ensure auto-refresh preserves the file-panel selection.

Covers the bug where pressing <ctrl+n> to move off file index 0 would be
silently reset on the next auto-refresh tick on the Agents tab.
"""

from __future__ import annotations

import types
from datetime import datetime
from unittest.mock import MagicMock

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.file_panel import _LIVE_DIFF_SENTINEL, AgentFilePanel
from sase.ace.tui.widgets.file_panel._messages import (
    FileCacheEntry,
    file_cache,
    get_cache_key,
)


def _make_agent(
    cl_name: str = "test_cl",
    raw_suffix: str | None = "20240101120000",
    extra_files: list[str] | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.gp",
        status="RUNNING",
        start_time=datetime(2024, 1, 1, 12, 0, 0),
        raw_suffix=raw_suffix,
        extra_files=list(extra_files) if extra_files else [],
    )


def _make_panel() -> MagicMock:
    """Create a MagicMock panel and bind the methods under test."""
    panel = MagicMock(spec=AgentFilePanel)
    panel._current_agent = None
    panel._current_worker = None
    panel._has_displayed_content = False
    panel._last_file_content = None
    panel._is_background_refreshing = False
    panel._file_list = []
    panel._current_file_index = 0
    panel._total_line_count = 0
    panel._visible_line_count = 0
    panel._base_trim_size = 0
    panel._is_trimmed = False
    panel._full_content = None
    panel._full_content_lexer = "text"
    panel._content_mode = "none"
    panel._static_header_path = None

    # Bind the real methods we want to test
    panel.update_display = types.MethodType(AgentFilePanel.update_display, panel)
    panel._update_display_body = types.MethodType(
        AgentFilePanel._update_display_body, panel
    )
    panel.set_file_list = types.MethodType(AgentFilePanel.set_file_list, panel)
    panel.next_file = types.MethodType(AgentFilePanel.next_file, panel)
    panel.prev_file = types.MethodType(AgentFilePanel.prev_file, panel)
    panel._pick_up_extra_files = types.MethodType(
        AgentFilePanel._pick_up_extra_files, panel
    )

    # Stub out side-effecting internals that would touch the filesystem,
    # spawn workers, or render UI.
    panel._reset_trim_state = MagicMock()
    panel._start_background_fetch = MagicMock()
    panel._display_file_at_current_index = MagicMock()
    panel._display_file_with_timestamp = MagicMock()
    panel._show_loading = MagicMock()
    panel.run_worker = MagicMock(return_value=None)
    panel.post_message = MagicMock()
    return panel


def _clear_cache_for(agent: Agent) -> None:
    file_cache.pop(get_cache_key(agent), None)


def test_ctrl_n_index_survives_no_cache_refresh() -> None:
    """On same-agent refresh with no cache, the user's file index is preserved."""
    panel = _make_panel()
    agent = _make_agent(extra_files=["/tmp/plan.md", "/tmp/notes.md"])
    _clear_cache_for(agent)

    # First update_display: full-reset branch (new agent, no cache),
    # populates the file list without the sentinel since no cached diff.
    panel.update_display(agent)
    assert panel._file_list == ["/tmp/plan.md", "/tmp/notes.md"]
    assert panel._current_file_index == 0

    # User presses <ctrl+n> to move to the second file.
    panel.next_file()
    assert panel._current_file_index == 1
    assert panel._file_list[panel._current_file_index] == "/tmp/notes.md"

    # Simulate a refresh tick that reaches branch 4 again (e.g. after a
    # previous fetch errored so the cache was never populated).
    _clear_cache_for(agent)
    panel.update_display(agent)

    assert panel._current_file_index == 1
    assert panel._file_list[panel._current_file_index] == "/tmp/notes.md"


def test_ctrl_n_index_survives_set_file_list_refresh() -> None:
    """set_file_list with an unchanged list must not reset a user selection."""
    panel = _make_panel()
    panel.set_file_list(["/tmp/a.diff", "/tmp/b.diff"], start_index=0)
    assert panel._current_file_index == 0

    panel.next_file()
    assert panel._current_file_index == 1

    # Auto-refresh always passes start_index=0 — must be ignored when files match.
    panel.set_file_list(["/tmp/a.diff", "/tmp/b.diff"], start_index=0)
    assert panel._current_file_index == 1


def test_set_file_list_preserves_selection_when_list_grows() -> None:
    """When the file list grows but the current file still exists, keep it."""
    panel = _make_panel()
    panel.set_file_list(["/tmp/a", "/tmp/b"], start_index=0)
    panel.next_file()
    assert panel._current_file_index == 1
    assert panel._file_list[panel._current_file_index] == "/tmp/b"

    panel.set_file_list(["/tmp/a", "/tmp/b", "/tmp/c"], start_index=0)

    assert panel._current_file_index == 1
    assert panel._file_list[panel._current_file_index] == "/tmp/b"


def test_set_file_list_falls_back_to_start_index_when_old_file_missing() -> None:
    """When the currently selected file is gone, fall back to start_index."""
    panel = _make_panel()
    panel.set_file_list(["/tmp/a", "/tmp/b"], start_index=0)
    panel.next_file()
    assert panel._current_file_index == 1
    assert panel._file_list[panel._current_file_index] == "/tmp/b"

    # b is gone from the new list — must fall back to start_index.
    panel.set_file_list(["/tmp/a", "/tmp/c"], start_index=0)

    assert panel._current_file_index == 0
    assert panel._file_list == ["/tmp/a", "/tmp/c"]


def test_update_display_cross_agent_switch_still_resets() -> None:
    """Switching to a different agent must reset the file index to 0."""
    panel = _make_panel()
    agent_x = _make_agent(
        cl_name="x",
        raw_suffix="20240101120000",
        extra_files=["/tmp/x1.md", "/tmp/x2.md"],
    )
    agent_y = _make_agent(
        cl_name="y",
        raw_suffix="20240101130000",
        extra_files=["/tmp/y1.md", "/tmp/y2.md"],
    )
    _clear_cache_for(agent_x)
    _clear_cache_for(agent_y)

    panel.update_display(agent_x)
    panel.next_file()
    assert panel._current_file_index == 1

    panel.update_display(agent_y)

    assert panel._current_file_index == 0
    assert panel._file_list == ["/tmp/y1.md", "/tmp/y2.md"]


def test_update_display_same_agent_preserves_plan_when_sentinel_disappears() -> None:
    """If the sentinel drops out of the rebuilt list, preserve the plan file.

    Pre-state: user was viewing the plan file (index 1) while a live diff
    sentinel was at index 0. A later refresh rebuilds the list with no
    cached diff, so the sentinel is gone. The user should stay on the plan,
    which is now at index 0.
    """
    panel = _make_panel()
    agent = _make_agent(extra_files=["/tmp/plan.md"])
    # Seed pre-state: file_list had the sentinel + plan, user on the plan.
    panel._current_agent = agent
    panel._file_list = [_LIVE_DIFF_SENTINEL, "/tmp/plan.md"]
    panel._current_file_index = 1

    # No cache — forces branch 4 full-reset path.
    _clear_cache_for(agent)
    panel.update_display(agent)

    assert panel._file_list == ["/tmp/plan.md"]
    assert panel._current_file_index == 0


def test_update_display_fresh_cache_preserves_user_index() -> None:
    """Fresh-cache early-return branch must not touch _current_file_index."""
    panel = _make_panel()
    agent = _make_agent(extra_files=["/tmp/plan.md", "/tmp/notes.md"])

    # Seed pre-state: user has navigated to index 1 under a populated cache.
    panel._current_agent = agent
    panel._file_list = ["/tmp/plan.md", "/tmp/notes.md"]
    panel._current_file_index = 1
    file_cache[get_cache_key(agent)] = FileCacheEntry(
        diff_output="", fetch_time=datetime.now()
    )

    try:
        panel.update_display(agent, stale_threshold_seconds=10)
    finally:
        _clear_cache_for(agent)

    assert panel._current_file_index == 1
