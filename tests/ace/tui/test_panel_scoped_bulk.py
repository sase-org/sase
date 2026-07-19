"""Panel-scoped bulk actions only touch the focused panel.

Both ``_dismiss_all_done_agents`` and ``_kill_and_dismiss_all_agents`` must
narrow their candidate sets to the agents in ``self._panel_group.focused_key``
so that bulk actions on the Agents tab don't blow away unrelated tagged work in
other panels.
"""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.modals import (
    AgentCleanupClanModal,
    AgentCleanupClanResult,
    AgentCleanupTagModal,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.core.agent_cleanup_wire import (
    CLEANUP_SCOPE_CLAN,
    CLEANUP_SCOPE_CUSTOM_SELECTION,
)


def _agent(
    *,
    name: str,
    suffix: str,
    agent_type: AgentType | None = None,
    tag: str | None = None,
    status: str = "DONE",
    pid: int | None = None,
    parent_workflow: str | None = None,
    parent_timestamp: str | None = None,
    workflow: str | None = None,
    agent_clan: str | None = None,
    agent_clan_generation: str | None = None,
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
        tribe=tag,
        raw_suffix=suffix,
        pid=pid,
        parent_workflow=parent_workflow,
        parent_timestamp=parent_timestamp,
        workflow=workflow,
        agent_clan=agent_clan,
        agent_clan_generation=agent_clan_generation,
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

    app_default_focus = _FakeApp([parent, child], focused_key=None)
    assert app_default_focus._panel_group.focused_key == "fix"
    app_default_focus._dismiss_all_done_agents()
    assert set(_names_in_modal(app_default_focus)) == {"parent", "child"}


def test_missing_focused_key_falls_back_to_first_tag_for_dismiss() -> None:
    fix = _agent(name="f1", suffix="t1", tag="fix")
    app = _FakeApp([fix], focused_key=None)

    app._dismiss_all_done_agents()

    assert app._panel_group.focused_key == "fix"
    assert _names_in_modal(app) == ["f1"]
    assert app._notifications == []


def test_missing_focused_key_falls_back_to_first_tag_for_kill_and_dismiss() -> None:
    fix_run = _agent(name="f_run", suffix="t1", status="RUNNING", pid=42, tag="fix")
    app = _FakeApp([fix_run], focused_key=None)

    app._kill_and_dismiss_all_agents()

    assert app._panel_group.focused_key == "fix"
    assert _names_in_modal(app) == ["f_run"]
    assert app._notifications == []


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


def test_tag_cleanup_known_tags_are_current_agents_tab_tags(
    monkeypatch: Any,
) -> None:
    fix = _agent(name="f1", suffix="t1", tag="fix")
    stale_review = _agent(name="r1", suffix="t2", tag="review")
    app = _FakeApp([fix], agents_with_children=[fix, stale_review])
    monkeypatch.setattr(
        "sase.ace.agent_tribes.load_agent_tribes",
        lambda: {(AgentType.RUNNING, "cl", "t3"): "persisted"},
    )

    assert app._known_agent_cleanup_tags() == ("fix",)


def test_tag_cleanup_modal_preview_ignores_out_of_scope_same_tag_agent() -> None:
    visible = _agent(name="visible", suffix="t1", tag="fix", status="RUNNING", pid=10)
    stale = _agent(name="stale", suffix="t2", tag="fix", status="RUNNING", pid=20)
    app = _FakeApp([visible], agents_with_children=[visible, stale])

    app._open_tag_cleanup_selector()

    screen, _callback = app._pushed[-1]
    assert isinstance(screen, AgentCleanupTagModal)
    rows = {row.tag: row for row in screen._rows}
    assert rows["fix"].plan.counts.kill == 1


def test_tag_cleanup_confirmation_ignores_out_of_scope_same_tag_agent() -> None:
    visible = _agent(name="visible", suffix="t1", tag="fix", status="RUNNING", pid=10)
    stale = _agent(name="stale", suffix="t2", tag="fix", status="RUNNING", pid=20)
    app = _FakeApp([visible], agents_with_children=[visible, stale])

    app._present_tag_cleanup("fix")

    assert len(app._pushed) == 1
    assert _names_in_modal(app) == ["visible"]


def test_multi_tag_cleanup_confirmation_includes_selected_tags() -> None:
    fix = _agent(name="fix", suffix="t1", tag="fix", status="RUNNING", pid=10)
    review = _agent(name="review", suffix="t2", tag="review")
    other = _agent(name="other", suffix="t3", tag="other")
    app = _FakeApp([fix, review, other])

    app._present_tag_cleanup_for_tags(("fix", "review"))

    assert len(app._pushed) == 1
    screen, _callback = app._pushed[-1]
    assert "Tags: @fix, @review" in screen.agent_description
    assert set(_names_in_modal(app)) == {"fix", "review"}


def test_multi_tag_cleanup_dedupes_workflow_cascade_identities() -> None:
    parent = _agent(
        name="parent",
        suffix="parent-ts",
        agent_type=AgentType.WORKFLOW,
        tag="fix",
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
        tag="review",
    )
    review = _agent(name="review", suffix="review-ts", tag="review")
    app = _FakeApp([parent, review], agents_with_children=[parent, child, review])

    app._present_tag_cleanup_for_tags(("fix", "review"))

    assert len(app._pushed) == 1
    assert _names_in_modal(app).count("parent") == 1
    assert set(_names_in_modal(app)) == {"parent", "review"}


def test_multi_tag_cleanup_confirmation_ignores_out_of_scope_same_tag_agent() -> None:
    visible_fix = _agent(
        name="visible-fix", suffix="t1", tag="fix", status="RUNNING", pid=10
    )
    visible_review = _agent(name="visible-review", suffix="t2", tag="review")
    stale_fix = _agent(
        name="stale-fix", suffix="t3", tag="fix", status="RUNNING", pid=20
    )
    app = _FakeApp(
        [visible_fix, visible_review],
        agents_with_children=[visible_fix, visible_review, stale_fix],
    )

    app._present_tag_cleanup_for_tags(("fix", "review"))

    assert len(app._pushed) == 1
    assert set(_names_in_modal(app)) == {"visible-fix", "visible-review"}


def test_tag_cleanup_current_workflow_parent_keeps_hidden_child_cascade() -> None:
    parent = _agent(
        name="parent",
        suffix="parent-ts",
        agent_type=AgentType.WORKFLOW,
        tag="fix",
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

    app._open_tag_cleanup_selector()

    screen, _callback = app._pushed[-1]
    assert isinstance(screen, AgentCleanupTagModal)
    rows = {row.tag: row for row in screen._rows}
    assert rows["fix"].plan.counts.kill == 1
    assert rows["fix"].plan.counts.cascaded_workflow_children == 1


def _projected_clans(*members: Agent) -> list[Agent]:
    return project_clan_tree(list(members))


def test_clan_cleanup_panel_state_counts_cleanable_clans_and_focus(
    monkeypatch: Any,
) -> None:
    alpha = _agent(
        name="alpha.1",
        suffix="alpha-1",
        status="RUNNING",
        pid=10,
        tag="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
    )
    beta = _agent(
        name="beta.1",
        suffix="beta-1",
        tag="epic",
        agent_clan="beta",
        agent_clan_generation="g2",
    )
    rows = _projected_clans(alpha, beta)
    app = _FakeApp(rows, focused_key="epic", agents_with_children=rows)
    monkeypatch.setattr(app, "_get_focused_group", lambda: None)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: alpha)

    state = app._build_agent_cleanup_panel_state()

    assert state.clan_count == 2
    assert state.focused_clan_label == "alpha"


def test_open_clan_cleanup_selector_is_tribe_scoped_and_pre_highlighted(
    monkeypatch: Any,
) -> None:
    alpha = _agent(
        name="alpha.1",
        suffix="alpha-1",
        status="RUNNING",
        pid=10,
        tag="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
    )
    review = _agent(
        name="review.1",
        suffix="review-1",
        tag="review",
        agent_clan="review",
        agent_clan_generation="g2",
    )
    rows = _projected_clans(alpha, review)
    app = _FakeApp(rows, focused_key="epic", agents_with_children=rows)
    monkeypatch.setattr(app, "_get_selected_agent", lambda: alpha)

    app._open_clan_cleanup_selector()

    screen, _callback = app._pushed[-1]
    assert isinstance(screen, AgentCleanupClanModal)
    assert [row.label for row in screen._rows] == ["alpha"]
    assert screen._initial_clan == ("alpha", "g1")
    assert all(not target.is_clan_container for target in screen._targets)


def test_single_clan_cleanup_uses_clan_scope_and_strips_containers(
    monkeypatch: Any,
) -> None:
    running = _agent(
        name="alpha.1",
        suffix="alpha-1",
        status="RUNNING",
        pid=10,
        tag="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
    )
    done = _agent(
        name="alpha.2",
        suffix="alpha-2",
        tag="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
    )
    rows = _projected_clans(running, done)
    app = _FakeApp(rows, focused_key="epic", agents_with_children=rows)
    captured: dict[str, Any] = {}

    def capture(request: Any, *, header: str, targets: list[Agent]) -> None:
        captured.update(request=request, header=header, targets=targets)

    monkeypatch.setattr(app, "_present_planned_cleanup", capture)

    app._present_clan_cleanup(
        AgentCleanupClanResult(clans=(("alpha", "g1"),), identities=())
    )

    request = captured["request"]
    assert request.scope == CLEANUP_SCOPE_CLAN
    assert request.clan_name == "alpha"
    assert request.clan_generation == "g1"
    assert captured["header"] == "Clan: alpha"
    assert {target.raw_suffix for target in captured["targets"]} == {
        "alpha-1",
        "alpha-2",
    }
    assert all(not target.is_clan_container for target in captured["targets"])


def test_mixed_clan_cleanup_unions_whole_clan_and_member_selection(
    monkeypatch: Any,
) -> None:
    alpha_one = _agent(
        name="alpha.1",
        suffix="alpha-1",
        status="RUNNING",
        pid=10,
        tag="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
    )
    alpha_two = _agent(
        name="alpha.2",
        suffix="alpha-2",
        tag="epic",
        agent_clan="alpha",
        agent_clan_generation="g1",
    )
    beta = _agent(
        name="beta.1",
        suffix="beta-1",
        status="RUNNING",
        pid=20,
        tag="epic",
        agent_clan="beta",
        agent_clan_generation="g2",
    )
    rows = _projected_clans(alpha_one, alpha_two, beta)
    app = _FakeApp(rows, focused_key="epic", agents_with_children=rows)
    captured: dict[str, Any] = {}

    def capture(request: Any, *, header: str, targets: list[Agent]) -> None:
        captured.update(request=request, header=header, targets=targets)

    monkeypatch.setattr(app, "_present_planned_cleanup", capture)

    app._present_clan_cleanup(
        AgentCleanupClanResult(clans=(("alpha", "g1"),), identities=(beta.identity,))
    )

    request = captured["request"]
    assert request.scope == CLEANUP_SCOPE_CUSTOM_SELECTION
    assert {identity.raw_suffix for identity in request.identities} == {
        "alpha-1",
        "alpha-2",
        "beta-1",
    }
    assert captured["header"] == "Clans: 2 selected"


def test_clan_cleanup_preserves_generation_and_untagged_panel_scope(
    monkeypatch: Any,
) -> None:
    old = _agent(
        name="alpha.old",
        suffix="alpha-old",
        agent_clan="alpha",
        agent_clan_generation="old",
    )
    current = _agent(
        name="alpha.current",
        suffix="alpha-current",
        status="RUNNING",
        pid=10,
        agent_clan="alpha",
        agent_clan_generation="current",
    )
    tagged = _agent(
        name="other.1",
        suffix="other-1",
        tag="review",
        agent_clan="other",
        agent_clan_generation="g2",
    )
    rows = _projected_clans(old, current, tagged)
    app = _FakeApp(rows, focused_key=None, agents_with_children=rows)
    captured: dict[str, Any] = {}

    def capture(request: Any, *, header: str, targets: list[Agent]) -> None:
        captured.update(request=request, header=header, targets=targets)

    monkeypatch.setattr(app, "_present_planned_cleanup", capture)

    app._present_clan_cleanup(
        AgentCleanupClanResult(clans=(("alpha", "current"),), identities=())
    )

    request = captured["request"]
    assert request.scope == CLEANUP_SCOPE_CLAN
    assert request.clan_generation == "current"
    assert {target.raw_suffix for target in captured["targets"]} == {
        "alpha-old",
        "alpha-current",
    }
