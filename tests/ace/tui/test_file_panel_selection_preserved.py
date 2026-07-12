"""Tests that ensure auto-refresh preserves the file-panel selection.

Covers the bug where pressing <ctrl+n> to move off file index 0 would be
silently reset on the next auto-refresh tick on the Agents tab.
"""

from __future__ import annotations

import types
from datetime import datetime
from unittest.mock import MagicMock

from sase.ace.changespec.models import DeltaEntry
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent import LinkedRepoMetadata
from sase.ace.tui.widgets.file_panel import _LIVE_DIFF_SENTINEL, AgentFilePanel
from sase.ace.tui.widgets.file_panel import _linked_deltas as linked_deltas_mod
from sase.ace.tui.widgets.file_panel._linked_deltas import LinkedDeltaGroup
from sase.ace.tui.widgets.file_panel._display import StaticReadResult
from sase.ace.tui.widgets.file_panel._messages import (
    FileCacheEntry,
    commit_slot_id,
    file_cache,
    get_cache_key,
    linked_slot_id,
)


def _make_agent(
    cl_name: str = "test_cl",
    raw_suffix: str | None = "20240101120000",
    extra_files: list[str] | None = None,
    status: str = "RUNNING",
    linked_repos: tuple[LinkedRepoMetadata, ...] = (),
    workspace_dir: str | None = None,
    diff_path: str | None = None,
    step_output: dict[str, object] | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2024, 1, 1, 12, 0, 0),
        raw_suffix=raw_suffix,
        extra_files=list(extra_files) if extra_files else [],
        linked_repos=linked_repos,
        workspace_dir=workspace_dir,
        diff_path=diff_path,
        step_output=step_output,
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
    panel._is_content_capped = False
    panel._full_content = None
    panel._full_content_lexer = "text"
    panel._content_mode = "none"
    panel._static_header_path = None
    panel._linked_repo_name = None
    panel._linked_workspace_dir = None
    panel._linked_fetched_at = None

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
    panel._desired_file_list = types.MethodType(
        AgentFilePanel._desired_file_list, panel
    )
    panel._select_file_index = types.MethodType(
        AgentFilePanel._select_file_index, panel
    )
    panel._current_file_value = types.MethodType(
        AgentFilePanel._current_file_value, panel
    )
    panel._linked_group_for_repo = types.MethodType(
        AgentFilePanel._linked_group_for_repo, panel
    )
    panel._commit_diff_info_for_slot = types.MethodType(
        AgentFilePanel._commit_diff_info_for_slot, panel
    )
    panel._commit_diff_path_for_slot = types.MethodType(
        AgentFilePanel._commit_diff_path_for_slot, panel
    )
    panel._current_linked_diff_changed = types.MethodType(
        AgentFilePanel._current_linked_diff_changed, panel
    )
    panel._reconcile_file_list = types.MethodType(
        AgentFilePanel._reconcile_file_list, panel
    )
    panel.get_current_file_path = types.MethodType(
        AgentFilePanel.get_current_file_path, panel
    )
    panel.current_source_label = types.MethodType(
        AgentFilePanel.current_source_label, panel
    )
    panel.source_label_for_slot = types.MethodType(
        AgentFilePanel.source_label_for_slot, panel
    )
    panel.file_source_labels = types.MethodType(
        AgentFilePanel.file_source_labels, panel
    )

    # Stub out side-effecting internals that would touch the filesystem,
    # spawn workers, or render UI.
    panel._reset_content_state = MagicMock()
    panel._start_background_fetch = MagicMock()
    panel._display_file_at_current_index = MagicMock()
    panel._display_file_with_timestamp = MagicMock()
    panel._show_loading = MagicMock()
    panel.run_worker = MagicMock(return_value=None)
    panel.post_message = MagicMock()
    return panel


def _clear_cache_for(agent: Agent) -> None:
    file_cache.pop(get_cache_key(agent), None)
    linked_deltas_mod._selected_agent_linked_delta_cache.pop(agent.identity, None)
    linked_deltas_mod._selected_agent_cache_monotonic.pop(agent.identity, None)


def _seed_linked_group(
    agent: Agent,
    *,
    repo_name: str = "sase-core",
    workspace_dir: str = "/tmp/sase-core",
    diff_text: str = "diff --git a/lib.py b/lib.py\n+++ b/lib.py\n+new\n",
) -> None:
    linked_deltas_mod._selected_agent_linked_delta_cache[agent.identity] = (
        LinkedDeltaGroup(
            repo_name=repo_name,
            workspace_dir=workspace_dir,
            entries=(DeltaEntry(path="lib.py", change_type="M"),),
            diff_text=diff_text,
            fetched_at=datetime(2024, 1, 1, 12, 30, 0),
        ),
    )


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


def test_desired_file_list_orders_primary_linked_then_extra_files() -> None:
    """Linked diff pages sit after the primary diff and before artifacts."""
    panel = _make_panel()
    agent = _make_agent(
        extra_files=["/tmp/plan.md"],
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/tmp/sase-core",
            ),
        ),
    )
    file_cache[get_cache_key(agent)] = FileCacheEntry(
        diff_output="diff --git a/a b/a\n+primary\n",
        fetch_time=datetime.now(),
    )
    _seed_linked_group(agent)

    try:
        pages, default_value = panel._desired_file_list(agent)
    finally:
        _clear_cache_for(agent)

    assert pages == [
        _LIVE_DIFF_SENTINEL,
        linked_slot_id("sase-core"),
        "/tmp/plan.md",
    ]
    assert default_value == _LIVE_DIFF_SENTINEL


def test_desired_file_list_plan_default_is_value_based_with_linked_pages() -> None:
    """Plan-chain agents default to the plan path even after linked diff slots."""
    panel = _make_panel()
    agent = _make_agent(
        extra_files=["/tmp/plan.md"],
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/tmp/sase-core",
            ),
        ),
    )
    agent.role_suffix = ".plan"
    file_cache[get_cache_key(agent)] = FileCacheEntry(
        diff_output="diff --git a/a b/a\n+primary\n",
        fetch_time=datetime.now(),
    )
    _seed_linked_group(agent)

    try:
        pages, default_value = panel._desired_file_list(agent)
    finally:
        _clear_cache_for(agent)

    assert pages == [
        _LIVE_DIFF_SENTINEL,
        linked_slot_id("sase-core"),
        "/tmp/plan.md",
    ]
    assert default_value == "/tmp/plan.md"


def test_reconcile_adds_linked_page_and_preserves_current_file() -> None:
    """Adding a linked page before a static file preserves selection by value."""
    panel = _make_panel()
    agent = _make_agent(
        extra_files=["/tmp/plan.md"],
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/tmp/sase-core",
            ),
        ),
    )
    panel._current_agent = agent
    panel._file_list = ["/tmp/plan.md"]
    panel._current_file_index = 0
    panel._has_displayed_content = True
    _seed_linked_group(agent)

    try:
        panel._reconcile_file_list(agent, allow_initial_display=True)
    finally:
        _clear_cache_for(agent)

    assert panel._file_list == [linked_slot_id("sase-core"), "/tmp/plan.md"]
    assert panel._current_file_index == 1
    assert panel._file_list[panel._current_file_index] == "/tmp/plan.md"
    panel._display_file_at_current_index.assert_not_called()


def test_reconcile_removes_linked_page_and_falls_back_to_plan() -> None:
    """When a linked page disappears, reconciliation selects the default page."""
    panel = _make_panel()
    agent = _make_agent(
        extra_files=["/tmp/plan.md"],
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/tmp/sase-core",
            ),
        ),
    )
    panel._current_agent = agent
    panel._file_list = [linked_slot_id("sase-core"), "/tmp/plan.md"]
    panel._current_file_index = 0
    panel._has_displayed_content = True
    _clear_cache_for(agent)

    panel._reconcile_file_list(agent, allow_initial_display=True)

    assert panel._file_list == ["/tmp/plan.md"]
    assert panel._current_file_index == 0
    panel._display_file_at_current_index.assert_called_once()


def test_completed_agents_do_not_get_linked_pages() -> None:
    """The file-panel page list follows the header eligibility for terminal agents."""
    panel = _make_panel()
    agent = _make_agent(
        status="DONE",
        linked_repos=(
            LinkedRepoMetadata(
                name="sase-core",
                workspace_dir="/tmp/sase-core",
            ),
        ),
    )
    _seed_linked_group(agent)

    try:
        pages, _ = panel._desired_file_list(agent)
    finally:
        _clear_cache_for(agent)

    assert pages == []


def test_terminal_commit_pages_precede_files_and_suppress_live_diff() -> None:
    panel = _make_panel()
    agent = _make_agent(
        status="DONE",
        workspace_dir="/tmp/sase_7",
        diff_path="/tmp/latest.diff",
        extra_files=["/tmp/plan.md"],
        step_output={
            "meta_commits": [
                {
                    "message": "feat: first",
                    "sha": "111111111111aaaa",
                    "cwd": "/tmp/sase_7",
                    "diff_path": "/tmp/001.diff",
                },
                {
                    "message": "fix: second",
                    "sha": "222222222222bbbb",
                    "cwd": "/tmp/sase_7/src",
                    "diff_path": "/tmp/002.diff",
                },
            ],
        },
    )
    file_cache[get_cache_key(agent)] = FileCacheEntry(
        diff_output="diff --git a/latest b/latest\n+latest\n",
        fetch_time=datetime.now(),
    )

    try:
        pages, default_value = panel._desired_file_list(agent)
    finally:
        _clear_cache_for(agent)

    assert pages == [commit_slot_id(0), commit_slot_id(1), "/tmp/plan.md"]
    assert default_value == commit_slot_id(0)


def test_commit_slot_label_path_and_display_resolution() -> None:
    panel = _make_panel()
    panel._display_file_at_current_index = types.MethodType(
        AgentFilePanel._display_file_at_current_index, panel
    )
    linked_repo = LinkedRepoMetadata(
        name="sase-core",
        workspace_dir="/tmp/sase-core_7",
    )
    agent = _make_agent(
        status="DONE",
        workspace_dir="/tmp/sase_7",
        linked_repos=(linked_repo,),
        step_output={
            "meta_commits": [
                {
                    "message": "feat: primary",
                    "sha": "111111111111aaaa",
                    "cwd": "/tmp/sase_7/src",
                    "diff_path": "/tmp/001.diff",
                },
                {
                    "message": "feat: linked",
                    "sha": "222222222222bbbb",
                    "cwd": "/tmp/sase-core_7",
                    "diff_path": "/tmp/002.diff",
                },
            ],
        },
    )
    panel._current_agent = agent
    panel._file_list = [commit_slot_id(0), commit_slot_id(1)]
    panel._current_file_index = 0
    panel.display_static_diff = MagicMock()

    assert panel.get_current_file_path() == "/tmp/001.diff"
    assert panel.current_source_label() == "test 111111111111"
    panel._display_file_at_current_index()
    panel.display_static_diff.assert_called_once_with("/tmp/001.diff")

    panel._current_file_index = 1
    assert panel.get_current_file_path() == "/tmp/002.diff"
    assert panel.current_source_label() == "▣ sase-core 222222222222"


def test_commit_slot_static_read_result_matches_resolved_diff_path() -> None:
    panel = _make_panel()
    panel._handle_static_read_result = types.MethodType(
        AgentFilePanel._handle_static_read_result, panel
    )
    agent = _make_agent(
        status="DONE",
        workspace_dir="/tmp/sase_7",
        step_output={
            "meta_commits": [
                {
                    "message": "feat: primary",
                    "sha": "111111111111aaaa",
                    "cwd": "/tmp/sase_7",
                    "diff_path": "/tmp/001.diff",
                },
            ],
        },
    )
    panel._current_agent = agent
    panel._file_list = [commit_slot_id(0)]
    panel._current_file_index = 0
    panel._static_request_id = 7
    panel._render_static_diff_result = MagicMock()

    matching = StaticReadResult(
        request_id=7,
        mode="diff",
        path="/tmp/001.diff",
        expanded_path="/tmp/001.diff",
        status="ok",
        content="diff --git a/a b/a\n+a\n",
        lexer="diff",
    )
    panel._handle_static_read_result(matching)
    panel._render_static_diff_result.assert_called_once_with(matching)

    panel._render_static_diff_result.reset_mock()
    stale = StaticReadResult(
        request_id=7,
        mode="diff",
        path="/tmp/other.diff",
        expanded_path="/tmp/other.diff",
        status="ok",
        content="diff --git a/b b/b\n+b\n",
        lexer="diff",
    )
    panel._handle_static_read_result(stale)
    panel._render_static_diff_result.assert_not_called()


def test_current_source_label_and_path_guard_for_linked_slot() -> None:
    panel = _make_panel()
    panel._file_list = [linked_slot_id("sase-core"), "/tmp/plan.md"]
    panel._current_file_index = 0

    assert panel.get_current_file_path() is None
    assert panel.current_source_label() == "▣ sase-core"

    panel._current_file_index = 1
    assert panel.current_source_label() == "plan.md"
