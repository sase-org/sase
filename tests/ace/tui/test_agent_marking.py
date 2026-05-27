"""Tests for the Agents-tab mark/bulk workflow."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.actions.agents._wait_resume import AgentWaitResumeMixin
from sase.ace.tui.actions.marking import MarkingMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import AgentGroupFoldRegistry


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for marking tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "RUNNING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "pid": 4242,
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakeMarkApp(AgentMarkingMixin, MarkingMixin):
    """Minimal app implementing just what the marking flow touches."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self._current_group_key: tuple[str, ...] | None = None
        self._group_fold_registry = AgentGroupFoldRegistry()
        self.refresh_calls: int = 0
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self._scheduled: list[tuple[Any, tuple[Any, ...]]] = []
        self.async_refreshes = 0
        self.notification_refreshes_async = 0
        self.changespecs: list = []  # type: ignore[assignment]
        self.marked_indices: set[int] = set()

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        self.refresh_calls += 1

    def _try_patch_agent_row(self, agent: Agent) -> bool:
        # Fall back to the full refresh path so this fake exercises the
        # same code path it always did. Real-app tests cover patching.
        del agent
        return False

    def _try_patch_changespec_row(self, idx: int) -> bool:
        del idx
        return False

    def _update_info_panel(self) -> None:
        return

    def _refresh_panel_highlights(self) -> None:
        pass

    def _refresh_display(self) -> None:
        pass

    def _notify_after_refresh(
        self, message: str, *, severity: str = "information"
    ) -> None:
        self.notify(message, severity=severity)

    def call_later(self, callback: Any, *args: Any) -> None:
        self._scheduled.append((callback, args))

    async def _refresh_notification_count_async(self) -> None:
        self.notification_refreshes_async += 1

    def _schedule_agents_async_refresh(self) -> None:
        self.async_refreshes += 1

    def _apply_dismissal_in_memory(self, agents: list[Agent]) -> None:
        removed = {agent.identity for agent in agents}
        self._agents = [a for a in self._agents if a.identity not in removed]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in removed
        ]
        self._dismissed_agent_objects.extend(agents)

    def _agents_visible_order(self) -> list[int]:
        from sase.ace.tui.models.agent_groups import build_agent_tree

        tree = build_agent_tree(self._agents, fold_registry=self._group_fold_registry)
        return [
            entry.agent_idx
            for entry in tree
            if entry.kind == "agent" and entry.agent_idx is not None
        ]

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_kill_agent(self, agent: Agent) -> None:
        self._agents = [a for a in self._agents if a.identity != agent.identity]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity != agent.identity
        ]

    def _do_dismiss_all(self, agents: list[Agent]) -> None:
        ids = {a.identity for a in agents}
        self._agents = [a for a in self._agents if a.identity not in ids]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in ids
        ]

    def _do_bulk_kill_agents(
        self, killable: list[Agent], dismissable: list[Agent] | None = None
    ) -> None:
        ids = {a.identity for a in killable}
        ids.update(a.identity for a in dismissable or [])
        self._agents = [a for a in self._agents if a.identity not in ids]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in ids
        ]
        self._marked_agents = set()


def test_toggle_mark_adds_identity() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])

    app._toggle_mark_agent()

    assert a1.identity in app._marked_agents
    assert a2.identity not in app._marked_agents


def test_toggle_mark_auto_advances_cursor() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])

    app._toggle_mark_agent()

    assert app.current_idx == 1


def test_toggle_mark_wraps_around() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])
    app.current_idx = 1

    app._toggle_mark_agent()

    assert app.current_idx == 0


def test_toggle_mark_advances_in_rendered_agent_order() -> None:
    agents = [
        _make_agent(project_file="/tmp/projects/zeta/zeta.sase", cl_name="z1"),
        _make_agent(project_file="/tmp/projects/alpha/alpha.sase", cl_name="a1"),
        _make_agent(project_file="/tmp/projects/beta/beta.sase", cl_name="b1"),
    ]
    app = _FakeMarkApp(agents)
    app.current_idx = 1  # alpha, visually first

    app._toggle_mark_agent()

    assert app.current_idx == 2
    assert app._agents[app.current_idx].cl_name == "b1"


def test_toggle_mark_wraps_in_rendered_agent_order() -> None:
    agents = [
        _make_agent(project_file="/tmp/projects/zeta/zeta.sase", cl_name="z1"),
        _make_agent(project_file="/tmp/projects/alpha/alpha.sase", cl_name="a1"),
        _make_agent(project_file="/tmp/projects/beta/beta.sase", cl_name="b1"),
    ]
    app = _FakeMarkApp(agents)
    app.current_idx = 0  # zeta, visually last

    app._toggle_mark_agent()

    assert app.current_idx == 1
    assert app._agents[app.current_idx].cl_name == "a1"


def test_toggle_mark_skips_collapsed_banner_rows() -> None:
    agents = [
        _make_agent(project_file="/tmp/projects/alpha/alpha.sase", cl_name="a1"),
        _make_agent(project_file="/tmp/projects/beta/beta.sase", cl_name="b1"),
    ]
    app = _FakeMarkApp(agents)
    app._group_fold_registry.collapse(("alpha",))
    app.current_idx = 1

    app._toggle_mark_agent()

    assert app.current_idx == 1
    assert app._agents[app.current_idx].cl_name == "b1"


def test_toggle_mark_twice_removes_identity() -> None:
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    app._toggle_mark_agent()
    # With a single entry, cursor stays at 0 (no wraparound needed)
    assert app.current_idx == 0
    assert a1.identity in app._marked_agents
    app._toggle_mark_agent()

    assert a1.identity not in app._marked_agents


def test_toggle_mark_empty_panel_warns() -> None:
    app = _FakeMarkApp([])

    app._toggle_mark_agent()

    assert app._marked_agents == set()
    assert app.notifications == [("No agent selected", "warning")]


def test_clear_agent_marks_removes_all() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app = _FakeMarkApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}

    app._clear_agent_marks()

    assert app._marked_agents == set()
    assert any(msg.startswith("Cleared") for msg, _ in app.notifications)


def test_clear_agent_marks_when_empty_warns() -> None:
    app = _FakeMarkApp([_make_agent()])

    app._clear_agent_marks()

    assert app.notifications == [("No marks to clear", "warning")]


def test_prune_stale_marked_agents_drops_missing() -> None:
    a1 = _make_agent(raw_suffix="20240101120000")
    app = _FakeMarkApp([a1])
    ghost_identity: tuple[AgentType, str, str | None] = (
        AgentType.RUNNING,
        "missing",
        "20240101999999",
    )
    app._marked_agents = {a1.identity, ghost_identity}

    app._prune_stale_marked_agents()

    assert app._marked_agents == {a1.identity}


def test_bulk_kill_partitions_and_clears_marks() -> None:
    """Bulk kill with confirm delegates one batched call."""
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    done = _make_agent(
        cl_name="done_cl",
        raw_suffix="20240101130000",
        status="DONE",
        pid=None,
    )
    app = _FakeMarkApp([running, done])
    app._marked_agents = {running.identity, done.identity}

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app._bulk_kill_marked_agents()
        assert app.pushed_callbacks, "Modal callback not registered"
        # Simulate user confirming the modal
        app.pushed_callbacks[0](True)

    mock_bulk.assert_called_once_with([running], [done])


def test_bulk_kill_cancel_preserves_marks() -> None:
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}

    with patch.object(app, "_do_bulk_kill_agents") as mock_bulk:
        app._bulk_kill_marked_agents()
        # Simulate user cancelling the modal
        app.pushed_callbacks[0](False)

    mock_bulk.assert_not_called()
    assert app._marked_agents == {running.identity}


def test_bulk_change_status_dispatches_to_save_marked_agents_on_agents_tab() -> None:
    """The global S action routes to the Agents-tab save/dismiss flow."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    with patch.object(app, "_save_marked_agent_group") as mock_save:
        app.action_bulk_change_status()

    mock_save.assert_called_once_with()


def test_bulk_change_status_keeps_changespec_status_flow() -> None:
    """The CLs tab still opens the bulk status modal."""

    class _Spec:
        status = "WIP"

    app = _FakeMarkApp([])
    app.current_tab = "changespecs"
    app.changespecs = [_Spec()]  # type: ignore[list-item]
    app.marked_indices = {0}

    app.action_bulk_change_status()

    assert len(app.pushed_modals) == 1
    assert app.pushed_callbacks[0] is not None


def test_save_marked_agent_group_warns_when_no_agents_marked() -> None:
    app = _FakeMarkApp([_make_agent()])

    app.action_bulk_change_status()

    assert app.notifications == [("No agents marked", "warning")]
    assert app._scheduled == []


def test_save_marked_running_agents_hides_without_kill() -> None:
    """Agents-tab S must not call the bulk kill or SIGTERM path."""
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}

    with (
        patch.object(app, "_do_bulk_kill_agents") as mock_bulk_kill,
        patch.object(app, "_kill_process_group", create=True) as mock_killpg,
    ):
        app.action_bulk_change_status()

    mock_bulk_kill.assert_not_called()
    mock_killpg.assert_not_called()
    assert app._dismissed_agents == {running.identity}
    assert app._marked_agents == set()
    assert app._agents == []
    assert app._scheduled


def test_save_marked_group_persists_refs_in_display_order() -> None:
    """The saved group records marked agents and cascaded children in row order."""
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent_cl",
        raw_suffix="20240101120000",
        workflow="wf",
        pid=111,
    )
    child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="parent_cl",
        raw_suffix="20240101120001",
        parent_workflow="wf",
        parent_timestamp="20240101120000",
        step_index=1,
        pid=None,
    )
    other = _make_agent(cl_name="other_cl", raw_suffix="20240101130000", pid=222)
    app = _FakeMarkApp([parent, child, other])
    app._marked_agents = {other.identity, parent.identity}

    app.action_bulk_change_status()

    saved_groups: list[Any] = []
    saved_bundles: list[Agent] = []
    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle") as mock_bundle,
        patch("sase.ace.dismissed_agents.save_dismissed_agents", return_value=True),
        patch(
            "sase.ace.dismissed_agents.save_dismissed_agent_group",
            side_effect=lambda group: saved_groups.append(group) or group,
        ),
        patch(
            "sase.ace.tui.actions.agents._marking.sync_dismissed_agent_artifact_index"
        ),
    ):
        mock_bundle.side_effect = lambda agent: saved_bundles.append(agent) or True
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))

    assert [agent.identity for agent in saved_bundles] == [
        parent.identity,
        child.identity,
        other.identity,
    ]
    assert len(saved_groups) == 1
    group = saved_groups[0]
    assert [ref.raw_suffix for ref in group.agent_refs] == [
        "20240101120000",
        "20240101120001",
        "20240101130000",
    ]
    assert [ref.is_workflow_child for ref in group.agent_refs] == [
        False,
        True,
        False,
    ]
    assert group.agent_count == 3
    assert group.top_level_agent_count == 2


def test_toggle_mark_dispatches_to_agents_tab_from_action() -> None:
    """action_toggle_mark on agents tab routes to _toggle_mark_agent."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])

    app.action_toggle_mark()

    assert a1.identity in app._marked_agents
    # ChangeSpec mark set is independent
    assert app.marked_indices == set()


def test_toggle_mark_on_changespecs_does_not_touch_agent_marks() -> None:
    """action_toggle_mark on changespecs tab leaves _marked_agents alone."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])
    app.current_tab = "changespecs"
    app.changespecs = [object()]  # type: ignore[list-item]

    app.action_toggle_mark()

    assert app._marked_agents == set()


def test_clear_marks_dispatches_to_agents_tab_from_action() -> None:
    """action_clear_marks on agents tab routes to _clear_agent_marks."""
    a1 = _make_agent()
    app = _FakeMarkApp([a1])
    app._marked_agents = {a1.identity}

    app.action_clear_marks()

    assert app._marked_agents == set()


class _FakeWaitApp(AgentWaitResumeMixin, AgentMarkingMixin, MarkingMixin):
    """Minimal app implementing what action_wait_for_agent touches."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents: list[Agent] = list(agents)
        self._agents_with_children: list[Agent] = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self.notifications: list[tuple[str, str]] = []
        self.prompt_bar_calls: list[dict[str, Any]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _show_prompt_input_bar_for_home(
        self,
        *,
        initial_text: str = "",
        display_name: str | None = None,
        history_sort_key: str | None = None,
    ) -> None:
        self.prompt_bar_calls.append(
            {
                "initial_text": initial_text,
                "display_name": display_name,
                "history_sort_key": history_sort_key,
            }
        )


def test_wait_for_agent_no_marks_uses_single_agent_path() -> None:
    a1 = _make_agent(raw_suffix="20240101120000", agent_name="alice")
    app = _FakeWaitApp([a1])

    app.action_wait_for_agent()

    assert len(app.prompt_bar_calls) == 1
    call = app.prompt_bar_calls[0]
    assert call["initial_text"] == "%w:alice "
    assert call["display_name"] == "wait(alice)"


def test_wait_for_agent_family_root_uses_root_name() -> None:
    a1 = _make_agent(
        raw_suffix="20240101120000",
        agent_name="alice-plan",
        agent_family="alice",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = _FakeWaitApp([a1])

    app.action_wait_for_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "%w:alice "
    assert app.prompt_bar_calls[0]["display_name"] == "wait(alice)"


def test_fork_agent_family_root_uses_root_name() -> None:
    a1 = _make_agent(
        raw_suffix="20240101120000",
        status="DONE",
        agent_name="alice-plan",
        agent_family="alice",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = _FakeWaitApp([a1])

    app.action_fork_agent()

    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:alice "
    assert app.prompt_bar_calls[0]["display_name"] == "fork(alice)"


def test_wait_for_agent_one_mark_falls_through_to_single_agent() -> None:
    """A single mark behaves identically to single-agent path (cursor irrelevant)."""
    a1 = _make_agent(cl_name="cl_a", raw_suffix="20240101120000", agent_name="alice")
    a2 = _make_agent(cl_name="cl_b", raw_suffix="20240101130000", agent_name="bob")
    app = _FakeWaitApp([a1, a2])
    # Cursor is on a1 but only a2 is marked; we should wait on a2 not a1.
    app.current_idx = 0
    app._marked_agents = {a2.identity}

    app.action_wait_for_agent()

    assert len(app.prompt_bar_calls) == 1
    call = app.prompt_bar_calls[0]
    assert call["initial_text"] == "%w:bob "
    assert call["display_name"] == "wait(bob)"


def test_wait_for_agent_bulk_marks_joins_with_commas() -> None:
    a1 = _make_agent(cl_name="cl_a", raw_suffix="20240101120000", agent_name="alice")
    a2 = _make_agent(cl_name="cl_b", raw_suffix="20240101130000", agent_name="bob")
    app = _FakeWaitApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}

    app.action_wait_for_agent()

    assert len(app.prompt_bar_calls) == 1
    call = app.prompt_bar_calls[0]
    # Order follows _agents_with_children iteration: a1, then a2.
    assert call["initial_text"] == "%w:alice,bob "
    assert call["display_name"] == "wait(2 agents)"


def test_wait_for_agent_bulk_skips_unnamed_and_warns() -> None:
    a1 = _make_agent(cl_name="cl_a", raw_suffix="20240101120000", agent_name="alice")
    a2 = _make_agent(cl_name="cl_b", raw_suffix="20240101130000", agent_name="bob")
    a3 = _make_agent(cl_name="cl_c", raw_suffix="20240101140000", agent_name=None)
    app = _FakeWaitApp([a1, a2, a3])
    app._marked_agents = {a1.identity, a2.identity, a3.identity}

    app.action_wait_for_agent()

    assert len(app.prompt_bar_calls) == 1
    assert app.prompt_bar_calls[0]["initial_text"] == "%w:alice,bob "
    assert ("Skipped 1 marked agent(s) with no name", "warning") in app.notifications


def test_wait_for_agent_bulk_all_unnamed_warns_and_skips_prompt() -> None:
    a1 = _make_agent(cl_name="cl_a", raw_suffix="20240101120000", agent_name=None)
    a2 = _make_agent(cl_name="cl_b", raw_suffix="20240101130000", agent_name=None)
    app = _FakeWaitApp([a1, a2])
    app._marked_agents = {a1.identity, a2.identity}

    app.action_wait_for_agent()

    assert app.prompt_bar_calls == []
    assert ("No marked agents have a name", "warning") in app.notifications
