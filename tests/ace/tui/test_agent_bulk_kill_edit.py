"""Tests for the Agents-tab bulk kill-and-edit flow (leader ``,X``).

``,X`` kills/dismisses the explicitly marked rows and then opens a prompt stack
seeded with one editable pane per killed agent, in mark order. It reuses the
existing bulk confirmation modal and the forced-name-reuse rule used by the
single-agent ``,x`` path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.models.agent import AgentType

AgentIdentity = tuple[AgentType, str, str | None]


@dataclass
class _FakeAgent:
    cl_name: str
    raw_suffix: str
    raw_prompt: str | None
    agent_name: str | None = None
    status: str = "RUNNING"
    pid: int | None = 100
    project_file: str = "/tmp/projects/proj/proj.sase"
    is_project_agent: bool = False
    agent_type: AgentType = AgentType.RUNNING

    @property
    def identity(self) -> AgentIdentity:
        return (self.agent_type, self.cl_name, self.raw_suffix)

    @property
    def display_name(self) -> str:
        return self.cl_name

    def get_raw_xprompt_content(self) -> str | None:
        return self.raw_prompt


class _FakeBulkEditApp(AgentMarkingMixin):
    """Minimal app exercising the bulk kill-and-edit entry point."""

    def __init__(self, agents: list[_FakeAgent]) -> None:
        self.current_tab = "agents"  # type: ignore[assignment]
        self.current_idx = 0
        self._agents = list(agents)  # type: ignore[assignment]
        self._agents_with_children = list(agents)  # type: ignore[assignment]
        self._marked_agents = set()
        self._marked_agent_order = []
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.bulk_kill_calls: list[tuple[list[Any], list[Any]]] = []
        self.edit_calls: list[dict[str, Any]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_bulk_kill_agents(
        self, killable: list[Any], dismissable: list[Any] | None = None
    ) -> None:
        dismissable = dismissable or []
        self.bulk_kill_calls.append((list(killable), list(dismissable)))
        ids = {a.identity for a in killable} | {a.identity for a in dismissable}
        self._agents = [a for a in self._agents if a.identity not in ids]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in ids
        ]
        self._reset_marked_agents()

    def _edit_and_relaunch_agents_bulk(
        self,
        prompts: list[str],
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.edit_calls.append(
            {
                "prompts": list(prompts),
                "project_file": project_file,
                "cl_name": cl_name,
                "is_project_agent": is_project_agent,
            }
        )


def _mark_in_order(app: _FakeBulkEditApp, *agents: _FakeAgent) -> None:
    for agent in agents:
        app._record_marked_agent(agent.identity)


def _confirm(app: _FakeBulkEditApp) -> None:
    assert app.pushed_callbacks, "Modal callback not registered"
    app.pushed_callbacks[-1](True)


# --- happy path ------------------------------------------------------------


def test_bulk_kill_and_edit_mounts_panes_in_mark_order() -> None:
    running = _FakeAgent(
        cl_name="run",
        raw_suffix="20240101120000",
        raw_prompt="%n:run\nWork run",
        agent_name="run",
        status="RUNNING",
        pid=111,
    )
    done = _FakeAgent(
        cl_name="done",
        raw_suffix="20240101130000",
        raw_prompt="%name:done\nWork done",
        agent_name="done",
        status="DONE",
        pid=None,
    )
    # Mark done first, then running: panes must follow this order, not row
    # order or set order.
    app = _FakeBulkEditApp([running, done])
    _mark_in_order(app, done, running)

    app._bulk_kill_marked_agents_and_edit()
    _confirm(app)

    # Kill split: running is killable, done is dismissable.
    assert len(app.bulk_kill_calls) == 1
    killable, dismissable = app.bulk_kill_calls[0]
    assert [a.cl_name for a in killable] == ["run"]
    assert [a.cl_name for a in dismissable] == ["done"]

    # One pane per killed agent, in mark order, with forced name reuse applied.
    assert len(app.edit_calls) == 1
    assert app.edit_calls[0]["prompts"] == [
        "%name:!done\nWork done",
        "%n:!run\nWork run",
    ]


def test_bulk_kill_and_edit_one_mark_uses_marked_flow() -> None:
    only = _FakeAgent(
        cl_name="solo",
        raw_suffix="20240101120000",
        raw_prompt="Just do it",
        status="RUNNING",
        pid=222,
    )
    app = _FakeBulkEditApp([only])
    _mark_in_order(app, only)

    app._bulk_kill_marked_agents_and_edit()
    _confirm(app)

    assert app.edit_calls[0]["prompts"] == ["Just do it"]


def test_bulk_kill_and_edit_does_not_split_embedded_separator() -> None:
    agent = _FakeAgent(
        cl_name="multi",
        raw_suffix="20240101120000",
        raw_prompt="part one\n---\npart two",
        status="RUNNING",
        pid=333,
    )
    app = _FakeBulkEditApp([agent])
    _mark_in_order(app, agent)

    app._bulk_kill_marked_agents_and_edit()
    _confirm(app)

    # The embedded ``---`` stays inside the single pane for this one agent.
    assert app.edit_calls[0]["prompts"] == ["part one\n---\npart two"]


# --- cancel / no-op paths --------------------------------------------------


def test_bulk_kill_and_edit_cancel_preserves_marks_and_mounts_nothing() -> None:
    agent = _FakeAgent(
        cl_name="run",
        raw_suffix="20240101120000",
        raw_prompt="Work",
        status="RUNNING",
        pid=111,
    )
    app = _FakeBulkEditApp([agent])
    _mark_in_order(app, agent)

    app._bulk_kill_marked_agents_and_edit()
    assert app.pushed_callbacks, "Modal callback not registered"
    app.pushed_callbacks[-1](False)  # cancel

    assert app.bulk_kill_calls == []
    assert app.edit_calls == []
    assert app._marked_agents == {agent.identity}
    assert app._marked_agent_order == [agent.identity]


def test_bulk_kill_and_edit_no_marks_warns() -> None:
    agent = _FakeAgent(
        cl_name="run",
        raw_suffix="20240101120000",
        raw_prompt="Work",
    )
    app = _FakeBulkEditApp([agent])

    app._bulk_kill_marked_agents_and_edit()

    assert app.pushed_modals == []
    assert app.notifications == [("No agents marked", "warning")]


def test_bulk_kill_and_edit_all_stale_warns() -> None:
    stale: AgentIdentity = (AgentType.RUNNING, "ghost", "20240101990000")
    app = _FakeBulkEditApp([])
    app._marked_agents = {stale}
    app._marked_agent_order = [stale]

    app._bulk_kill_marked_agents_and_edit()

    assert app.pushed_modals == []
    assert app.notifications == [("No marked agents remain", "warning")]
    assert app._marked_agents == set()
    assert app._marked_agent_order == []


def test_bulk_kill_and_edit_prunes_stale_marks() -> None:
    live = _FakeAgent(
        cl_name="live",
        raw_suffix="20240101120000",
        raw_prompt="Work live",
        status="RUNNING",
        pid=111,
    )
    stale: AgentIdentity = (AgentType.RUNNING, "ghost", "20240101990000")
    app = _FakeBulkEditApp([live])
    _mark_in_order(app, live)
    app._marked_agents.add(stale)
    app._marked_agent_order.append(stale)

    app._bulk_kill_marked_agents_and_edit()
    _confirm(app)

    # Only the live marked agent becomes a pane.
    assert app.edit_calls[0]["prompts"] == ["Work live"]


def test_bulk_kill_and_edit_missing_prompt_aborts_before_kill() -> None:
    has_prompt = _FakeAgent(
        cl_name="ok",
        raw_suffix="20240101120000",
        raw_prompt="Work ok",
        status="RUNNING",
        pid=111,
    )
    no_prompt = _FakeAgent(
        cl_name="bad",
        raw_suffix="20240101130000",
        raw_prompt=None,
        status="RUNNING",
        pid=222,
    )
    app = _FakeBulkEditApp([has_prompt, no_prompt])
    _mark_in_order(app, has_prompt, no_prompt)

    app._bulk_kill_marked_agents_and_edit()

    # Aborted before confirmation: no modal, no kill, no panes, marks intact.
    assert app.pushed_modals == []
    assert app.bulk_kill_calls == []
    assert app.edit_calls == []
    assert app._marked_agents == {has_prompt.identity, no_prompt.identity}
    assert app.notifications == [
        ("1 marked agent missing a prompt; nothing killed", "warning")
    ]
