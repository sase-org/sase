"""Tests for the Phase 4 incremental row-removal fast path.

The fast path lets a single kill or dismiss avoid rebuilding every row
in the focused panel by removing the targeted Option in place. The
caller falls back to ``_refresh_agents_display(list_changed=True)`` when
any conservative gate fails.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.actions.agents._dismissing import AgentDismissingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.widgets.agent_list import AgentList


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _Container:
    """Minimal stand-in for the ``#agent-list-container`` Textual widget."""

    def __init__(self, panels: list[AgentList]) -> None:
        self.children = panels


def _wire_agent_list(monkeypatch: Any) -> AgentList:
    widget = AgentList()

    def _call_later(callback: Callable[[], None]) -> None:
        callback()

    monkeypatch.setattr(widget, "call_later", _call_later)
    monkeypatch.setattr(widget, "post_message", lambda _msg: None)
    return widget


def _agent(
    *,
    cl_name: str = "demo",
    raw_suffix: str = "20260425143000",
    status: str = "RUNNING",
    project_file: str = "/repo/proj.gp",
    pid: int | None = 1234,
    workflow: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=cl_name,
        project_file=project_file,
        status=status,
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        raw_suffix=raw_suffix,
        pid=pid,
        workflow=workflow,
    )


# ---------------------------------------------------------------------------
# Kill fast-path
# ---------------------------------------------------------------------------


def _build_kill_app(panel_widget: AgentList | None) -> Any:
    class MockApp(AgentsMixin):
        def __init__(self) -> None:
            self._notifications: list[tuple[str, str]] = []
            self.current_tab = "agents"
            self.current_idx = 0
            self._kill_persistence_inflight: set[Any] = set()
            self._agent_status_overrides: dict[Any, Any] = {}
            self._agent_pre_question_status: dict[Any, Any] = {}
            self._dismissed_agents: set[Any] = set()
            self._agents_with_children: list[Agent] = []
            self._agents: list[Agent] = []
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self.refresh_calls: list[tuple[bool, bool]] = []
            self._agent_search_query = ""
            self._grouping_mode = GroupingMode.STANDARD
            self._tab_bar_refreshes = 0
            self._panel_cache_invalidations = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _refresh_notification_count(self) -> None:
            return

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            self.refresh_calls.append((list_changed, defer_detail))

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _schedule_agents_async_refresh(self) -> None:
            return

        def _capture_focused_visible_pos(self) -> int | None:
            return None

        def _restore_focus_after_removal(self, prior_visible_pos: int | None) -> None:
            return

        def _invalidate_agent_panel_cache(self) -> None:
            self._panel_cache_invalidations += 1

        def _refresh_tab_bar_agent_counts(self) -> None:
            self._tab_bar_refreshes += 1

        def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
            if panel_widget is None:
                from textual.css.query import NoMatches

                raise NoMatches()
            return _Container([panel_widget])

    return MockApp()


def test_single_kill_uses_fast_path(monkeypatch: Any) -> None:
    """Kill of a leaf RUNNING agent removes the row in place and
    skips the ``list_changed=True`` rebuild."""
    panel = _wire_agent_list(monkeypatch)
    a, b, c = (
        _agent(raw_suffix="r1"),
        _agent(raw_suffix="r2"),
        _agent(raw_suffix="r3"),
    )
    panel.update_list([a, b, c], current_idx=1)
    update_calls: list[int] = []
    orig_update_list = panel.update_list

    def _spy_update_list(*args: Any, **kwargs: Any) -> None:
        update_calls.append(1)
        orig_update_list(*args, **kwargs)

    monkeypatch.setattr(panel, "update_list", _spy_update_list)

    app = _build_kill_app(panel)
    app._agents = [a, b, c]
    app._agents_with_children = [a, b, c]

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(b)

    assert app._agents == [a, c]
    # The fast path skipped the full rebuild but still fired the
    # lightweight refresh.
    assert app.refresh_calls == [(False, True)]
    assert update_calls == []  # update_list never invoked
    # The widget's option list is one row shorter.
    assert b.identity not in {a.identity for a in panel._agents}
    assert app._tab_bar_refreshes == 1
    assert app._panel_cache_invalidations == 1


def test_kill_falls_back_when_no_panel_widget() -> None:
    """When the panel widget tree is unavailable, the kill path falls
    back to a full ``list_changed=True`` refresh."""
    app = _build_kill_app(None)
    a = _agent(raw_suffix="r1")
    b = _agent(raw_suffix="r2")
    app._agents = [a, b]
    app._agents_with_children = [a, b]

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(a)

    assert app.refresh_calls == [(True, True)]


def test_kill_falls_back_under_search(monkeypatch: Any) -> None:
    """An active agent search query disables the fast path."""
    panel = _wire_agent_list(monkeypatch)
    a = _agent(raw_suffix="r1")
    b = _agent(raw_suffix="r2")
    panel.update_list([a, b], current_idx=0)
    app = _build_kill_app(panel)
    app._agents = [a, b]
    app._agents_with_children = [a, b]
    app._agent_search_query = "running"

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(a)

    assert app.refresh_calls == [(True, True)]


def test_kill_falls_back_under_non_standard_grouping(monkeypatch: Any) -> None:
    """A non-STANDARD grouping mode disables the fast path."""
    panel = _wire_agent_list(monkeypatch)
    a = _agent(raw_suffix="r1")
    b = _agent(raw_suffix="r2")
    panel.update_list([a, b], current_idx=0, grouping_mode=GroupingMode.BY_STATUS)
    app = _build_kill_app(panel)
    app._agents = [a, b]
    app._agents_with_children = [a, b]
    app._grouping_mode = GroupingMode.BY_STATUS

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(a)

    assert app.refresh_calls == [(True, True)]


# ---------------------------------------------------------------------------
# Dismiss fast-path
# ---------------------------------------------------------------------------


def _build_dismiss_app(panel_widget: AgentList | None) -> Any:
    class FakeDismissApp(AgentDismissingMixin):
        def __init__(self) -> None:
            self.current_tab = "agents"
            self.current_idx = 0
            self.changespecs: list[Any] = []
            self._agents: list[Agent] = []
            self._dismissed_agents: set[Any] = set()
            self._dismissed_agent_objects: list[Agent] = []
            self._agents_with_children: list[Agent] = []
            self._agent_status_overrides: dict[Any, Any] = {}
            self._agent_pre_question_status: dict[Any, Any] = {}
            self._dismiss_persistence_inflight: set[Any] = set()
            self._scheduled: list[tuple[object, tuple[object, ...]]] = []
            self._notifications: list[tuple[str, str]] = []
            self.refilter_count = 0
            self.refresh_calls: list[tuple[bool, bool]] = []
            self._agent_search_query = ""
            self._grouping_mode = GroupingMode.STANDARD
            self._tab_bar_refreshes = 0

        def notify(self, msg: str, severity: str = "information") -> None:
            self._notifications.append((msg, severity))

        def _load_agents(self) -> None:
            return

        def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
            self.refilter_count += 1

        def _refresh_notification_count(self) -> None:
            return

        async def _refresh_notification_count_async(self) -> None:
            return

        def _refresh_agents_display(
            self, *, list_changed: bool = False, defer_detail: bool = False
        ) -> None:
            self.refresh_calls.append((list_changed, defer_detail))

        def _schedule_agents_async_refresh(self) -> None:
            return

        def call_later(self, callback: object, *args: object) -> None:
            self._scheduled.append((callback, args))

        def _capture_focused_visible_pos(self) -> int | None:
            return None

        def _restore_focus_after_removal(self, prior_visible_pos: int | None) -> None:
            return

        def _invalidate_agent_panel_cache(self) -> None:
            return

        def _refresh_tab_bar_agent_counts(self) -> None:
            self._tab_bar_refreshes += 1

        def _try_remove_agent_rows(self, removed_identities: set[Any]) -> bool:
            # Lightweight wrapper that delegates straight to the widget
            # so the test harness doesn't need to wire ``query_one``.
            if panel_widget is None:
                return False
            if self._agent_search_query:
                return False
            if self._grouping_mode is not GroupingMode.STANDARD:
                return False
            return panel_widget.try_remove_rows(removed_identities)

    return FakeDismissApp()


def test_single_dismiss_uses_fast_path(monkeypatch: Any) -> None:
    """Dismiss of a single DONE leaf removes the row in place and
    avoids the full ``_refilter_agents`` rebuild."""
    panel = _wire_agent_list(monkeypatch)
    leaf = _agent(raw_suffix="d1", status="DONE", pid=None)
    sibling = _agent(raw_suffix="d2", status="DONE", pid=None)
    panel.update_list([leaf, sibling], current_idx=0)

    app = _build_dismiss_app(panel)
    app._agents = [leaf, sibling]
    app._agents_with_children = [leaf, sibling]

    update_calls: list[int] = []
    orig_update_list = panel.update_list

    def _spy_update_list(*args: Any, **kwargs: Any) -> None:
        update_calls.append(1)
        orig_update_list(*args, **kwargs)

    monkeypatch.setattr(panel, "update_list", _spy_update_list)

    app._apply_dismissal_in_memory([leaf])

    assert app.refilter_count == 0  # fast path bypassed _refilter_agents
    assert update_calls == []
    assert app.refresh_calls == [(False, True)]
    assert leaf.identity not in {a.identity for a in panel._agents}
    assert leaf.identity not in {a.identity for a in app._agents}
    # Same-session revive snapshot still records the dismissed agent.
    assert leaf.identity in {a.identity for a in app._dismissed_agent_objects}
    assert app._tab_bar_refreshes == 1


def test_dismiss_falls_back_when_widget_missing() -> None:
    """When no panel widget is available, the dismiss path falls back
    to the full ``_refilter_agents`` rebuild."""
    app = _build_dismiss_app(None)
    leaf = _agent(raw_suffix="d1", status="DONE", pid=None)
    app._agents = [leaf]
    app._agents_with_children = [leaf]

    app._apply_dismissal_in_memory([leaf])

    assert app.refilter_count == 1
    assert app.refresh_calls == []


def test_dismiss_falls_back_under_search(monkeypatch: Any) -> None:
    panel = _wire_agent_list(monkeypatch)
    leaf = _agent(raw_suffix="d1", status="DONE", pid=None)
    panel.update_list([leaf], current_idx=0)
    app = _build_dismiss_app(panel)
    app._agents = [leaf]
    app._agents_with_children = [leaf]
    app._agent_search_query = "done"

    app._apply_dismissal_in_memory([leaf])

    # Search active -> fast path returns False -> _refilter_agents is taken.
    assert app.refilter_count == 1
    assert app.refresh_calls == []


def test_dismiss_workflow_parent_with_children_falls_back(
    monkeypatch: Any,
) -> None:
    panel = _wire_agent_list(monkeypatch)
    parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="wf_parent",
        project_file="/repo/proj.gp",
        status="DONE",
        start_time=datetime(2026, 4, 25, 12, 0, 0),
        workflow="wf",
        raw_suffix="wfp1",
    )
    child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="step_one",
        project_file=parent.project_file,
        status="DONE",
        start_time=datetime(2026, 4, 25, 12, 1, 0),
        raw_suffix="wfc1",
        parent_timestamp=parent.raw_suffix,
        parent_workflow=parent.workflow,
    )
    panel.update_list([parent, child], current_idx=0)

    app = _build_dismiss_app(panel)
    app._agents = [parent, child]
    app._agents_with_children = [parent, child]

    app._apply_dismissal_in_memory([parent])

    # Workflow parent gate trips -> fast path bails -> refilter runs.
    assert app.refilter_count == 1
    assert app.refresh_calls == []
