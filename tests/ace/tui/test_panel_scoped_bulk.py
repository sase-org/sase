"""Panel-scoped bulk actions only touch the focused panel.

Both ``_dismiss_all_done_agents`` and ``_kill_and_dismiss_all_agents`` must
narrow their candidate sets to the agents in ``self._panel_group.focused_key``
so that bulk actions on the Agents tab don't affect work in unrelated tribe
panels.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents import DISMISSABLE_STATUSES, AgentsMixin
from sase.ace.tui.actions.agents._clan_cleanup import expand_clan_containers_for_cleanup
from sase.ace.tui.modals import AgentCleanupTribeModal
from sase.ace.tui.models._agent_tree import agent_is_tree_child, project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup


def _agent(
    *,
    name: str,
    suffix: str,
    agent_type: AgentType | None = None,
    tribe: str | None = None,
    status: str = "DONE",
    pid: int | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    workflow: str | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
    agent_family_role: str | None = None,
    role_suffix: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type
        if agent_type is not None
        else AgentType.WORKFLOW
        if parent_workflow
        else AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status=status,
        start_time=None,
        agent_name=name,
        tribe=tribe,
        raw_suffix=suffix,
        pid=pid,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        workflow=workflow,
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
        agent_family_role=agent_family_role,
        role_suffix=role_suffix,
    )


class _FakeApp(AgentsMixin):
    def __init__(
        self,
        agents: list[Agent],
        focused_key: str | None = None,
        with_panel_group: bool = True,
        agents_with_children: list[Agent] | None = None,
    ) -> None:
        self._agents = agents
        self._agents_with_children = list(
            agents if agents_with_children is None else agents_with_children
        )
        self.current_idx = 0
        self.current_tab = "agents"
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self._current_group_key = None
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
    """Extract lane names from the most recent confirmation description."""
    assert app._pushed, "no modal was pushed"
    screen, _ = app._pushed[-1]
    desc = screen.agent_description
    names: list[str] = []
    for line in desc.splitlines():
        if not line.startswith("  "):
            continue
        names.append(line.strip().split(maxsplit=1)[0])
    return names


def test_dismiss_all_is_scoped_to_focused_panel() -> None:
    no_tribe = _agent(name="u1", suffix="t1")
    fix = _agent(name="f1", suffix="t2", tribe="fix")
    review = _agent(name="r1", suffix="t3", tribe="review")
    app = _FakeApp([no_tribe, fix, review], focused_key="fix")

    app._dismiss_all_done_agents()

    assert len(app._pushed) == 1
    assert app._pushed[-1][0].agent_description.startswith("Dismiss: 1 sase agent\n")
    assert _names_in_modal(app) == ["f1"]


def test_kill_and_dismiss_all_is_scoped_to_focused_panel() -> None:
    no_tribe_done = _agent(name="u_done", suffix="t1")
    no_tribe_run = _agent(name="u_run", suffix="t2", status="RUNNING", pid=10)
    fix_done = _agent(name="f_done", suffix="t3", tribe="fix")
    fix_run = _agent(name="f_run", suffix="t4", status="RUNNING", pid=20, tribe="fix")
    review_done = _agent(name="r_done", suffix="t5", tribe="review")
    app = _FakeApp(
        [no_tribe_done, no_tribe_run, fix_done, fix_run, review_done],
        focused_key="fix",
    )

    app._kill_and_dismiss_all_agents()

    assert len(app._pushed) == 1
    description = app._pushed[-1][0].agent_description
    assert "Kill: 1 sase agent" in description
    assert "Dismiss: 1 sase agent" in description
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
        tribe="fix",
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
    assert (
        "Dismiss: 1 sase agent · 2 agents"
        in app_focus_fix._pushed[-1][0].agent_description
    )
    assert _names_in_modal(app_focus_fix) == ["parent"]

    app_default_focus = _FakeApp([parent, child], focused_key=None)
    assert app_default_focus._panel_group.focused_key == "fix"
    app_default_focus._dismiss_all_done_agents()
    assert _names_in_modal(app_default_focus) == ["parent"]


def test_missing_focused_key_falls_back_to_first_tribe_for_dismiss() -> None:
    fix = _agent(name="f1", suffix="t1", tribe="fix")
    app = _FakeApp([fix], focused_key=None)

    app._dismiss_all_done_agents()

    assert app._panel_group.focused_key == "fix"
    assert _names_in_modal(app) == ["f1"]
    assert app._notifications == []


def test_missing_focused_key_falls_back_to_first_tribe_for_kill_and_dismiss() -> None:
    fix_run = _agent(name="f_run", suffix="t1", status="RUNNING", pid=42, tribe="fix")
    app = _FakeApp([fix_run], focused_key=None)

    app._kill_and_dismiss_all_agents()

    assert app._panel_group.focused_key == "fix"
    assert _names_in_modal(app) == ["f_run"]
    assert app._notifications == []


def test_panel_group_none_falls_back_to_all_agents() -> None:
    no_tribe = _agent(name="u1", suffix="t1")
    fix = _agent(name="f1", suffix="t2", tribe="fix")
    review = _agent(name="r1", suffix="t3", tribe="review")
    app = _FakeApp([no_tribe, fix, review], with_panel_group=False)

    app._dismiss_all_done_agents()

    assert len(app._pushed) == 1
    assert set(_names_in_modal(app)) == {"u1", "f1", "r1"}


def test_tribe_cleanup_uses_tribe_scope_plan() -> None:
    fix_done = _agent(name="f_done", suffix="t1", tribe="fix")
    fix_run = _agent(name="f_run", suffix="t2", status="RUNNING", pid=20, tribe="fix")
    review_done = _agent(name="r_done", suffix="t3", tribe="review")
    app = _FakeApp([fix_done, fix_run, review_done], focused_key=None)

    app._present_tribe_cleanup("fix")

    assert len(app._pushed) == 1
    names = set(_names_in_modal(app))
    assert names == {"f_done", "f_run"}


def test_tribe_cleanup_known_tribes_are_current_agents_tab_tribes(
    monkeypatch: Any,
) -> None:
    fix = _agent(name="f1", suffix="t1", tribe="fix")
    stale_review = _agent(name="r1", suffix="t2", tribe="review")
    app = _FakeApp([fix], agents_with_children=[fix, stale_review])
    monkeypatch.setattr(
        "sase.ace.agent_tribes.load_agent_tribes",
        lambda: {(AgentType.RUNNING, "cl", "t3"): "persisted"},
    )

    assert app._known_agent_cleanup_tribes() == ("fix",)


def test_tribe_cleanup_modal_preview_ignores_out_of_scope_same_tribe_agent() -> None:
    visible = _agent(name="visible", suffix="t1", tribe="fix", status="RUNNING", pid=10)
    stale = _agent(name="stale", suffix="t2", tribe="fix", status="RUNNING", pid=20)
    app = _FakeApp([visible], agents_with_children=[visible, stale])

    app._open_tribe_cleanup_selector()

    screen, _callback = app._pushed[-1]
    assert isinstance(screen, AgentCleanupTribeModal)
    rows = {row.tribe: row for row in screen._rows}
    assert rows["fix"].plan.counts.kill == 1


def test_tribe_cleanup_confirmation_ignores_out_of_scope_same_tribe_agent() -> None:
    visible = _agent(name="visible", suffix="t1", tribe="fix", status="RUNNING", pid=10)
    stale = _agent(name="stale", suffix="t2", tribe="fix", status="RUNNING", pid=20)
    app = _FakeApp([visible], agents_with_children=[visible, stale])

    app._present_tribe_cleanup("fix")

    assert len(app._pushed) == 1
    assert _names_in_modal(app) == ["visible"]


def test_multi_tribe_cleanup_confirmation_includes_selected_tribes() -> None:
    fix = _agent(name="fix", suffix="t1", tribe="fix", status="RUNNING", pid=10)
    review = _agent(name="review", suffix="t2", tribe="review")
    other = _agent(name="other", suffix="t3", tribe="other")
    app = _FakeApp([fix, review, other])

    app._present_tribe_cleanup_for_tribes(("fix", "review"))

    assert len(app._pushed) == 1
    screen, _callback = app._pushed[-1]
    assert "Tribes: @fix, @review" in screen.agent_description
    assert set(_names_in_modal(app)) == {"fix", "review"}


def test_multi_tribe_cleanup_dedupes_workflow_cascade_identities() -> None:
    parent = _agent(
        name="parent",
        suffix="parent-ts",
        agent_type=AgentType.WORKFLOW,
        tribe="fix",
        status="RUNNING",
        pid=10,
        workflow="wf",
    )
    child = _agent(
        name="child",
        suffix="child-ts",
        status="RUNNING",
        pid=11,
        parent_workflow="wf",
        parent_timestamp="parent-ts",
        workflow="step",
        tribe="review",
    )
    review = _agent(name="review", suffix="review-ts", tribe="review")
    app = _FakeApp([parent, review], agents_with_children=[parent, child, review])

    app._present_tribe_cleanup_for_tribes(("fix", "review"))

    assert len(app._pushed) == 1
    assert _names_in_modal(app).count("parent") == 1
    assert set(_names_in_modal(app)) == {"parent", "review"}


def test_multi_tribe_cleanup_confirmation_ignores_out_of_scope_same_tribe_agent() -> (
    None
):
    visible_fix = _agent(
        name="visible-fix", suffix="t1", tribe="fix", status="RUNNING", pid=10
    )
    visible_review = _agent(name="visible-review", suffix="t2", tribe="review")
    stale_fix = _agent(
        name="stale-fix", suffix="t3", tribe="fix", status="RUNNING", pid=20
    )
    app = _FakeApp(
        [visible_fix, visible_review],
        agents_with_children=[visible_fix, visible_review, stale_fix],
    )

    app._present_tribe_cleanup_for_tribes(("fix", "review"))

    assert len(app._pushed) == 1
    assert set(_names_in_modal(app)) == {"visible-fix", "visible-review"}


def test_tribe_cleanup_current_workflow_parent_keeps_hidden_child_cascade() -> None:
    parent = _agent(
        name="parent",
        suffix="parent-ts",
        agent_type=AgentType.WORKFLOW,
        tribe="fix",
        status="RUNNING",
        pid=10,
        workflow="wf",
    )
    hidden_child = _agent(
        name="hidden-child",
        suffix="child-ts",
        status="RUNNING",
        pid=11,
        parent_workflow="wf",
        parent_timestamp="parent-ts",
        workflow="step",
    )
    app = _FakeApp([parent], agents_with_children=[parent, hidden_child])

    app._open_tribe_cleanup_selector()

    screen, _callback = app._pushed[-1]
    assert isinstance(screen, AgentCleanupTribeModal)
    rows = {row.tribe: row for row in screen._rows}
    assert rows["fix"].plan.counts.kill == 1
    assert rows["fix"].plan.counts.cascaded_workflow_children == 1


def _projected_clans(*members: Agent) -> list[Agent]:
    return project_clan_tree(list(members))


def _clan_member_panel_app() -> tuple[_FakeApp, Agent, Agent, Agent, Agent, Agent]:
    direct = _agent(
        name="alpha.direct",
        suffix="alpha-direct",
        tribe="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
    )
    family_shell = _agent(
        name="alpha.direct--1",
        suffix="alpha-family",
        tribe="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
        parent_timestamp="alpha-direct",
        agent_family_role="root",
        role_suffix="--1",
    )
    running = _agent(
        name="alpha.run",
        suffix="alpha-run",
        status="RUNNING",
        pid=10,
        tribe="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
    )
    standalone = _agent(name="epic.solo", suffix="epic-solo", tribe="epic")
    review = _agent(
        name="review.done",
        suffix="review-done",
        tribe="review",
        agent_clan="review",
        agent_clan_generation="g2",
    )
    rows = _projected_clans(direct, family_shell, running, standalone, review)
    visible = [agent for agent in rows if not agent_is_tree_child(agent)]
    app = _FakeApp(visible, focused_key="epic", agents_with_children=rows)
    return app, direct, family_shell, running, standalone, review


def _dismiss_candidates(agents: list[Agent]) -> list[Agent]:
    return [
        agent
        for agent in agents
        if agent.status in DISMISSABLE_STATUSES and agent.raw_suffix is not None
    ]


def _kill_candidates(agents: list[Agent]) -> list[Agent]:
    return [
        agent
        for agent in agents
        if agent.pid is not None and agent.status not in DISMISSABLE_STATUSES
    ]


def test_panel_dismiss_selects_clan_members_not_container() -> None:
    app, direct, family_shell, running, standalone, review = _clan_member_panel_app()

    panel = app._agents_in_focused_panel()
    assert any(agent.is_clan_container for agent in panel)
    candidates = expand_clan_containers_for_cleanup(panel, app._agents_with_children)
    dismissable = _dismiss_candidates(candidates)
    assert {agent.identity for agent in dismissable} == {
        direct.identity,
        family_shell.identity,
        standalone.identity,
    }
    assert all(not agent.is_clan_container for agent in candidates)
    assert running.identity not in {agent.identity for agent in dismissable}
    assert review.identity not in {agent.identity for agent in dismissable}

    app._dismiss_all_done_agents()
    names = _names_in_modal(app)
    assert "alpha.direct" in names
    assert "epic.solo" in names
    assert "alpha.run" not in names
    assert "review.done" not in names


def test_panel_kill_and_dismiss_selects_clan_members_not_container() -> None:
    app, direct, family_shell, running, standalone, review = _clan_member_panel_app()

    panel = app._agents_in_focused_panel()
    candidates = expand_clan_containers_for_cleanup(panel, app._agents_with_children)
    killable = _kill_candidates(candidates)
    dismissable = _dismiss_candidates(candidates)
    selected = [*killable, *dismissable]
    assert {agent.identity for agent in killable} == {running.identity}
    assert {agent.identity for agent in dismissable} == {
        direct.identity,
        family_shell.identity,
        standalone.identity,
    }
    assert all(not agent.is_clan_container for agent in candidates)
    assert review.identity not in {agent.identity for agent in selected}

    app._kill_and_dismiss_all_agents()
    names = _names_in_modal(app)
    assert "alpha.direct" in names
    assert "alpha.run" in names
    assert "epic.solo" in names
    assert "review.done" not in names
