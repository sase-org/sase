"""Tests for the Agents-tab mark/bulk workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.actions.agents._wait_resume import AgentWaitResumeMixin
from sase.ace.tui.actions.marking import MarkingMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for marking tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
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
        self.refresh_calls: int = 0
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
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
