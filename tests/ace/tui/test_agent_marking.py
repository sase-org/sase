"""Tests for the Agents-tab mark/bulk workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
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
        self._pinned_agents: set[tuple[AgentType, str, str | None]] = set()
        self._main_panel_indices: list[int] = list(range(len(agents)))
        self._pinned_panel_indices: list[int] = []
        self._main_panel_idx_map: dict[int, int] = {i: i for i in range(len(agents))}
        self._pinned_panel_idx_map: dict[int, int] = {}
        self._pinned_panel_focused: str = "main"
        self.refresh_calls: int = 0
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.changespecs: list = []  # type: ignore[assignment]
        self.marked_indices: set[int] = set()

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(self, *, list_changed: bool = False) -> None:
        self.refresh_calls += 1

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
        # Simulate removal by the real kill path
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
    """Bulk kill with confirm: killables go through _do_kill_agent, dismissables through _do_dismiss_all."""
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    done = _make_agent(
        cl_name="done_cl",
        raw_suffix="20240101130000",
        status="DONE",
        pid=None,
    )
    app = _FakeMarkApp([running, done])
    app._marked_agents = {running.identity, done.identity}

    captured_kills: list[Agent] = []
    captured_dismissals: list[list[Agent]] = []

    def fake_kill(agent: Agent) -> None:
        captured_kills.append(agent)
        app._agents = [a for a in app._agents if a.identity != agent.identity]
        app._agents_with_children = [
            a for a in app._agents_with_children if a.identity != agent.identity
        ]

    def fake_dismiss(agents: list[Agent]) -> None:
        captured_dismissals.append(agents)
        ids = {a.identity for a in agents}
        app._agents = [a for a in app._agents if a.identity not in ids]
        app._agents_with_children = [
            a for a in app._agents_with_children if a.identity not in ids
        ]

    with (
        patch.object(app, "_do_kill_agent", side_effect=fake_kill),
        patch.object(app, "_do_dismiss_all", side_effect=fake_dismiss),
    ):
        app._bulk_kill_marked_agents()
        assert app.pushed_callbacks, "Modal callback not registered"
        # Simulate user confirming the modal
        app.pushed_callbacks[0](True)

    assert captured_kills == [running]
    assert captured_dismissals == [[done]]
    assert app._marked_agents == set()


def test_bulk_kill_cancel_preserves_marks() -> None:
    running = _make_agent(raw_suffix="20240101120000", status="RUNNING", pid=111)
    app = _FakeMarkApp([running])
    app._marked_agents = {running.identity}

    with patch.object(app, "_do_kill_agent") as mock_kill:
        app._bulk_kill_marked_agents()
        # Simulate user cancelling the modal
        app.pushed_callbacks[0](False)

    mock_kill.assert_not_called()
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
    # Ensure a changespec exists so _toggle_mark_changespec doesn't early-return
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
