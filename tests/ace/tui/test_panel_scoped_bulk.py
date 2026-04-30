"""Panel-scoped bulk actions: ``X`` and ``,X`` only touch the focused panel.

Both ``_dismiss_all_done_agents`` (``X``) and
``_kill_and_dismiss_all_agents`` (``,X``) must narrow their candidate
sets to the agents in ``self._panel_group.focused_key`` so that bulk
actions on the Agents tab don't blow away unrelated tagged work in
other panels.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup


def _agent(
    *,
    name: str,
    suffix: str,
    tag: str | None = None,
    status: str = "DONE",
    pid: int | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    workflow: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW if parent_workflow else AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.gp",
        status=status,
        start_time=None,
        agent_name=name,
        tag=tag,
        raw_suffix=suffix,
        pid=pid,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        workflow=workflow,
    )


class _FakeApp(AgentsMixin):
    def __init__(
        self,
        agents: list[Agent],
        focused_key: str | None = None,
        with_panel_group: bool = True,
    ) -> None:
        self._agents = agents
        self._agents_with_children = list(agents)
        self.current_idx = 0
        self.current_tab = "agents"
        self._notifications: list[tuple[str, str]] = []
        self._pushed: list[tuple[Any, Any]] = []
        if with_panel_group:
            self._panel_group = AgentPanelGroup.from_agents(
                agents, focused_key=focused_key
            )

    def notify(self, msg: str, severity: str = "information") -> None:
        self._notifications.append((msg, severity))

    def push_screen(self, screen: Any, callback: Any = None) -> None:
        self._pushed.append((screen, callback))


def _names_in_modal(app: _FakeApp) -> list[str]:
    """Extract agent names from the description of the most recent pushed modal.

    Each agent line looks like ``"  <display_name> @<agent_name>"``.
    """
    assert app._pushed, "no modal was pushed"
    screen, _ = app._pushed[-1]
    desc = screen.agent_description
    names: list[str] = []
    for line in desc.splitlines():
        if not line.startswith("  ") or "@" not in line:
            continue
        names.append(line.rsplit("@", 1)[1].strip())
    return names


def test_dismiss_all_is_scoped_to_focused_panel() -> None:
    untagged = _agent(name="u1", suffix="t1")
    fix = _agent(name="f1", suffix="t2", tag="fix")
    review = _agent(name="r1", suffix="t3", tag="review")
    app = _FakeApp([untagged, fix, review], focused_key="fix")

    app._dismiss_all_done_agents()

    assert len(app._pushed) == 1
    assert _names_in_modal(app) == ["f1"]


def test_kill_and_dismiss_all_is_scoped_to_focused_panel() -> None:
    untagged_done = _agent(name="u_done", suffix="t1")
    untagged_run = _agent(name="u_run", suffix="t2", status="RUNNING", pid=10)
    fix_done = _agent(name="f_done", suffix="t3", tag="fix")
    fix_run = _agent(name="f_run", suffix="t4", status="RUNNING", pid=20, tag="fix")
    review_done = _agent(name="r_done", suffix="t5", tag="review")
    app = _FakeApp(
        [untagged_done, untagged_run, fix_done, fix_run, review_done],
        focused_key="fix",
    )

    app._kill_and_dismiss_all_agents()

    assert len(app._pushed) == 1
    names = _names_in_modal(app)
    assert "f_run" in names
    assert "f_done" in names
    assert "u_done" not in names
    assert "u_run" not in names
    assert "r_done" not in names


def test_workflow_child_inherits_parent_panel_for_bulk_dismiss() -> None:
    parent = _agent(
        name="parent",
        suffix="20240101120000",
        tag="fix",
        status="DONE",
        workflow="wf",
    )
    child = _agent(
        name="child",
        suffix="step-1",
        status="DONE",
        parent_workflow="wf",
        parent_timestamp="20240101120000",
        workflow="step",
    )

    app_focus_fix = _FakeApp([parent, child], focused_key="fix")
    app_focus_fix._dismiss_all_done_agents()
    assert set(_names_in_modal(app_focus_fix)) == {"parent", "child"}

    app_focus_untagged = _FakeApp([parent, child], focused_key=None)
    app_focus_untagged._dismiss_all_done_agents()
    assert app_focus_untagged._notifications == [
        ("No agents to dismiss", "warning"),
    ]
    assert app_focus_untagged._pushed == []


def test_empty_focused_panel_short_circuits_dismiss() -> None:
    fix = _agent(name="f1", suffix="t1", tag="fix")
    app = _FakeApp([fix], focused_key=None)

    app._dismiss_all_done_agents()

    assert app._pushed == []
    assert app._notifications == [("No agents to dismiss", "warning")]


def test_empty_focused_panel_short_circuits_kill_and_dismiss() -> None:
    fix_run = _agent(name="f_run", suffix="t1", status="RUNNING", pid=42, tag="fix")
    app = _FakeApp([fix_run], focused_key=None)

    app._kill_and_dismiss_all_agents()

    assert app._pushed == []
    assert app._notifications == [("No agents to kill or dismiss", "warning")]


def test_panel_group_none_falls_back_to_all_agents() -> None:
    untagged = _agent(name="u1", suffix="t1")
    fix = _agent(name="f1", suffix="t2", tag="fix")
    review = _agent(name="r1", suffix="t3", tag="review")
    app = _FakeApp([untagged, fix, review], with_panel_group=False)

    app._dismiss_all_done_agents()

    assert len(app._pushed) == 1
    assert set(_names_in_modal(app)) == {"u1", "f1", "r1"}


def test_tag_cleanup_uses_tag_scope_plan() -> None:
    fix_done = _agent(name="f_done", suffix="t1", tag="fix")
    fix_run = _agent(name="f_run", suffix="t2", status="RUNNING", pid=20, tag="fix")
    review_done = _agent(name="r_done", suffix="t3", tag="review")
    app = _FakeApp([fix_done, fix_run, review_done], focused_key=None)

    app._present_tag_cleanup("fix")

    assert len(app._pushed) == 1
    names = set(_names_in_modal(app))
    assert names == {"f_done", "f_run"}
