"""Agents-tab projection and fold behavior for rootless clans."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models._agent_tree import (
    agent_fold_key,
    agent_parent_fold_key,
    filter_tree_rows,
    presentation_anchor,
    presentation_anchor_lookup,
    project_clan_tree,
    _tree_parent,
    tree_parent_lookup,
)
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import build_agent_tree
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models._agent_loader_normalization import (
    apply_snapshot_clan_context,
)
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.agent_list import _compute_fold_annotation
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentClanContextWire,
    AgentMetaWire,
)

_GENERATION = "20260717100000"


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def _agent(
    name: str,
    suffix: str,
    *,
    agent_type: AgentType = AgentType.RUNNING,
    status: str = "RUNNING",
    parent_timestamp: str | None = None,
    parent_workflow: str | None = None,
    step_type: str | None = None,
    hidden: bool = False,
    clan: str | None = "research",
    generation: str | None = _GENERATION,
    tribe: str | None = None,
    clan_tribe: str | None = None,
    clan_summary: str | None = None,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=name,
        project_file="/tmp/sase.sase",
        status=status,
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        run_start_time=datetime(2026, 7, 17, 10, 0, 0),
        raw_suffix=suffix,
        agent_name=name,
        parent_timestamp=parent_timestamp,
        parent_workflow=parent_workflow,
        step_type=step_type,
        is_hidden_step=hidden,
        agent_clan=clan,
        agent_clan_generation=generation,
        tribe=tribe,
        clan_tribe=clan_tribe,
        clan_summary=clan_summary,
    )


def test_project_clan_tree_inserts_container_and_three_depths() -> None:
    family = _agent("research.family", "family", tribe="epic")
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
        tribe="review",
    )
    solo = _agent("research.solo", "solo", status="DONE", tribe="review")

    projected = project_clan_tree([family, family_member, solo])

    container = projected[0]
    assert container.is_clan_container is True
    assert container.display_name == "research"
    assert container.agent_clan_generation == _GENERATION
    assert container.clan_tribes == ("epic", "review")
    assert container.runtime_children == [family, solo]
    assert projected == [container, family, family_member, solo]
    assert [row.tree_depth for row in projected] == [0, 1, 2, 1]
    clan_key = agent_fold_key(container)
    assert family.tree_parent_key == clan_key
    assert solo.tree_parent_key == clan_key
    assert family_member.tree_parent_key == family.raw_suffix
    assert agent_fold_key(family) == family.raw_suffix
    assert agent_parent_fold_key(family) == clan_key
    assert agent_parent_fold_key(family_member) == family.raw_suffix

    lookup = tree_parent_lookup(projected)
    assert _tree_parent(family_member, lookup) is family
    assert _tree_parent(family, lookup) is container
    anchors = presentation_anchor_lookup(projected, lookup)
    assert [anchors[id(row)] for row in projected] == [container] * 4


def test_project_clan_tree_sorts_direct_member_units_by_status_priority() -> None:
    done = _agent("research.done", "done", status="DONE")
    waiting = _agent("research.waiting", "waiting", status="WAITING")
    running = _agent("research.running", "running", status="RUNNING")
    stopped = _agent("research.stopped", "stopped", status="QUESTION")
    failed = _agent("research.failed", "failed", status="FAILED")

    container, *members = project_clan_tree([done, waiting, running, stopped, failed])

    assert members == [failed, stopped, running, waiting, done]
    # Container facts and the detail-panel inventory retain the established
    # launch order rather than inheriting the presentation-only member sort.
    assert container.runtime_children == [done, waiting, running, stopped, failed]

    reprojected_container = project_clan_tree([container, *members])[0]
    assert reprojected_container.runtime_children == [
        done,
        waiting,
        running,
        stopped,
        failed,
    ]


def test_project_clan_tree_keeps_same_bucket_launch_order_stable() -> None:
    newer = _agent("research.newer", "newer", status="RUNNING")
    older = _agent("research.older", "older", status="RUNNING")
    newer.start_time = datetime(2026, 7, 17, 10, 1, 0)
    older.start_time = datetime(2026, 7, 17, 10, 0, 0)

    _, *members = project_clan_tree([newer, older])

    assert members == [newer, older]


def test_project_clan_tree_sorts_family_unit_by_displayed_anchor_status() -> None:
    family = _agent("research.family", "family", status="WAITING")
    failed_followup = _agent(
        "research.family--failed",
        "family-failed",
        status="FAILED",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    done_followup = _agent(
        "research.family--done",
        "family-done",
        status="DONE",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    done_peer = _agent("research.done", "done", status="DONE")
    failed_peer = _agent("research.failed", "failed", status="FAILED")

    _, *members = project_clan_tree(
        [family, failed_followup, done_followup, done_peer, failed_peer]
    )

    assert members == [
        failed_peer,
        family,
        failed_followup,
        done_followup,
        done_peer,
    ]


def test_project_clan_tree_ranks_starting_with_running() -> None:
    done = _agent("research.done", "done", status="DONE")
    starting = _agent("research.starting", "starting", status="STARTING")
    running = _agent("research.running", "running", status="RUNNING")

    _, *members = project_clan_tree([done, starting, running])

    assert members == [starting, running, done]


def test_presentation_anchor_handles_orphans_and_cycles_deterministically() -> None:
    orphan = _agent("orphan", "orphan", clan=None, generation=None)
    orphan.tree_parent_key = "missing"
    orphan.tree_depth = 2
    shallow = _agent("cycle.shallow", "shallow", clan=None, generation=None)
    deep = _agent("cycle.deep", "deep", clan=None, generation=None)
    shallow.tree_parent_key = deep.raw_suffix
    shallow.tree_depth = 1
    deep.tree_parent_key = shallow.raw_suffix
    deep.tree_depth = 2
    rows = [deep, orphan, shallow]

    parent_lookup = tree_parent_lookup(rows)
    anchors = presentation_anchor_lookup(rows, parent_lookup)

    assert anchors[id(orphan)] is orphan
    assert anchors[id(shallow)] is shallow
    assert anchors[id(deep)] is shallow
    assert presentation_anchor(orphan, parent_lookup) is orphan
    assert presentation_anchor(shallow, parent_lookup) is shallow
    assert presentation_anchor(deep, parent_lookup) is shallow


def test_project_clan_tree_keeps_generations_separate() -> None:
    old = _agent("research.old", "old", generation="old")
    new = _agent("research.new", "new", generation="new")

    projected = project_clan_tree([new, old])

    containers = [row for row in projected if row.is_clan_container]
    assert [row.agent_clan_generation for row in containers] == ["new", "old"]
    assert containers[0].runtime_children == [new]
    assert containers[1].runtime_children == [old]
    assert new.tree_parent_key == agent_fold_key(containers[0])
    assert old.tree_parent_key == agent_fold_key(containers[1])


def test_project_clan_tree_uses_latest_explicit_clan_tribe() -> None:
    first = _agent(
        "research.first",
        "20260717100001",
        tribe="legacy",
        clan_tribe="alpha",
    )
    latest = _agent(
        "research.latest",
        "20260717100002",
        tribe="other-legacy",
        clan_tribe="beta",
    )
    later_without_declaration = _agent(
        "research.later",
        "20260717100003",
        tribe="ignored-legacy",
    )

    container = project_clan_tree([later_without_declaration, first, latest])[0]

    assert container.tribe == "beta"
    assert container.clan_tribe == "beta"
    assert container.clan_tribes == ("beta",)


def test_project_clan_tree_uses_context_when_declarer_is_omitted() -> None:
    context = AgentClanContextWire(
        agent_clan="toobig-0",
        agent_clan_generation="g1",
        clan_tribe="chop",
        clan_summary="Chop generation",
        clan_tribe_source_launch_timestamp="20260701000000",
        clan_tribe_source_identity="/tmp/declarer",
    )
    first = _agent(
        "toobig-0.first",
        "20260701000001",
        clan="toobig-0",
        generation="g1",
    )
    second = _agent(
        "toobig-0.second",
        "20260701000002",
        clan="toobig-0",
        generation="g1",
    )
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        clan_context=[context],
    )
    apply_snapshot_clan_context([first, second], snapshot)

    container, *members = project_clan_tree([first, second])

    assert members == [first, second]
    assert container.runtime_children == [first, second]
    assert container.clan_tribe == "chop"
    assert container.clan_summary == "Chop generation"
    assert container.clan_tribes == ("chop",)
    assert container.tribe == "chop"


def test_wire_enrichment_loads_clan_summary() -> None:
    agent = _agent("research.first", "one")

    enrich_agent_from_meta_wire(
        agent,
        AgentMetaWire(clan_summary="[bold]Research[/bold]"),
        None,
    )

    assert agent.clan_summary == "[bold]Research[/bold]"


def test_project_clan_tree_uses_latest_explicit_clan_summary() -> None:
    first = _agent(
        "research.first",
        "20260717100001",
        clan_summary="First summary",
    )
    latest = _agent(
        "research.latest",
        "20260717100002",
        clan_summary="[bold]Latest summary[/bold]",
    )
    later_without_declaration = _agent(
        "research.later",
        "20260717100003",
    )

    container = project_clan_tree([later_without_declaration, first, latest])[0]

    assert container.clan_summary == "[bold]Latest summary[/bold]"


def test_project_clan_tree_omits_summary_without_declaration() -> None:
    container = project_clan_tree(
        [
            _agent("research.first", "one"),
            _agent("research.second", "two"),
        ]
    )[0]

    assert container.clan_summary is None


def test_project_clan_tree_retains_direct_tribe_fallback() -> None:
    first = _agent("research.first", "one", tribe="alpha")
    second = _agent("research.second", "two", tribe="beta")

    container = project_clan_tree([first, second])[0]

    assert container.tribe is None
    assert container.clan_tribe is None
    assert container.clan_tribes == ("alpha", "beta")


def test_clan_tree_does_not_invent_a_patch_banner_from_one_member() -> None:
    one = _agent("first-patch", "one")
    two = _agent("second-patch", "two")
    projected = project_clan_tree([one, two])

    group_keys = [
        entry.group.group_key
        for entry in build_agent_tree(projected)
        if entry.group is not None
    ]

    assert group_keys == [("tmp",)]


def test_clan_and_members_fold_independently_through_recursive_ancestors() -> None:
    family = _agent("research.family", "family")
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    workflow = _agent(
        "research.workflow",
        "workflow",
        agent_type=AgentType.WORKFLOW,
    )
    workflow_step = _agent(
        "prompt",
        "workflow-step",
        agent_type=AgentType.WORKFLOW,
        parent_timestamp=workflow.raw_suffix,
        parent_workflow="visual-workflow",
        step_type="agent",
        clan=None,
        generation=None,
    )
    hidden_step = _agent(
        "setup",
        "workflow-hidden",
        agent_type=AgentType.WORKFLOW,
        parent_timestamp=workflow.raw_suffix,
        parent_workflow="visual-workflow",
        step_type="bash",
        hidden=True,
        clan=None,
        generation=None,
    )
    projected = project_clan_tree(
        [family, family_member, workflow, workflow_step, hidden_step]
    )
    container = projected[0]
    fold_key = agent_fold_key(container)
    assert fold_key is not None
    family_key = agent_fold_key(family)
    workflow_key = agent_fold_key(workflow)
    assert family_key is not None
    assert workflow_key is not None
    manager = FoldStateManager()

    collapsed, counts = filter_agents_by_fold_state(projected, manager)
    assert collapsed == [container]
    assert counts == {
        fold_key: (2, 0),
        family_key: (1, 0),
        workflow_key: (1, 1),
    }
    assert _compute_fold_annotation(container, counts, set()) == " ×2"
    assert _compute_fold_annotation(family, counts, set()) == " ×1"
    assert _compute_fold_annotation(workflow, counts, set()) == " ×2"

    manager.expand(fold_key)
    expanded, counts = filter_agents_by_fold_state(projected, manager)
    assert expanded == [container, family, workflow]
    assert _compute_fold_annotation(container, counts, {fold_key}) == ""

    manager.expand(workflow_key)
    member_expanded, counts = filter_agents_by_fold_state(projected, manager)
    assert member_expanded == [container, family, workflow, workflow_step]
    assert family_member not in member_expanded
    assert _compute_fold_annotation(workflow, counts, {workflow_key}) == " ×2 −1"

    manager.expand(workflow_key)
    member_fully_expanded, counts = filter_agents_by_fold_state(projected, manager)
    assert member_fully_expanded == [
        container,
        family,
        workflow,
        workflow_step,
        hidden_step,
    ]
    assert family_member not in member_fully_expanded
    assert (
        _compute_fold_annotation(
            workflow,
            counts,
            {workflow_key},
            {workflow_key},
        )
        == " ×2 +1"
    )

    manager.collapse(fold_key)
    masked, _ = filter_agents_by_fold_state(projected, manager)
    assert masked == [container]
    assert manager.get(workflow_key).name == "FULLY_EXPANDED"

    manager.expand(fold_key)
    reopened, _ = filter_agents_by_fold_state(projected, manager)
    assert reopened == member_fully_expanded


def test_clan_tree_query_retains_complete_immediate_parent_chain() -> None:
    family = _agent("research.family", "family")
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    peer = _agent("research.peer", "peer")
    projected = project_clan_tree([family, family_member, peer])

    filtered = filter_tree_rows(
        projected,
        lambda row: row.raw_suffix == family_member.raw_suffix,
    )

    assert filtered == projected


def test_clan_and_member_rows_render_identity_colors_tribes_and_depth_guides() -> None:
    family = _agent("research.family", "family", tribe="epic")
    family.agent_family = "research.family"
    family.agent_family_role = "root"
    family_member = _agent(
        "research.family--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    family.followup_agents = [family_member]
    container, family, family_member = project_clan_tree([family, family_member])

    container_text, _, _ = format_agent_option(
        container,
        0,
        is_selected=False,
        fold_annotation=" ×2",
        now=datetime(2026, 7, 17, 10, 5, 0),
    )
    family_text, _, _ = format_agent_option(
        family,
        1,
        is_selected=False,
        now=datetime(2026, 7, 17, 10, 5, 0),
    )
    member_text, _, _ = format_agent_option(
        family_member,
        2,
        is_selected=False,
        now=datetime(2026, 7, 17, 10, 5, 0),
    )

    assert container_text.plain == "(RUNNING) ×2 [R1] research @epic"
    assert "[agent]" not in container_text.plain
    assert _style_at(container_text, container_text.plain.rindex("research")) == (
        "#D75FFF"
    )
    assert family_text.plain.startswith("  └─ research.family")
    assert family_text.plain.endswith("research.family")
    assert (
        _style_at(
            family_text,
            family_text.plain.rindex("research.family"),
        )
        == "#00AFFF"
    )
    assert family_member.tree_depth == 2
    assert member_text.plain.startswith("  │  └─ research.family--code")


def test_family_identity_color_requires_a_real_member() -> None:
    family = _agent("cx", "family", clan=None, generation=None)
    family.agent_family = "cx"
    family.agent_family_role = "root"
    family.appears_as_agent = True
    member = _agent(
        "cx--code",
        "family-code",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    family.followup_agents = [member]

    lone_planner = _agent("solo", "planner", clan=None, generation=None)
    lone_planner.agent_family = "solo"
    lone_planner.agent_family_role = "root"
    lone_planner.appears_as_agent = True
    synthetic = _agent(
        "solo--plan",
        "synthetic-plan",
        parent_timestamp=lone_planner.raw_suffix,
        clan=None,
        generation=None,
    )
    synthetic.is_synthetic_planner = True
    lone_planner.followup_agents = [synthetic]

    plain = _agent("plain", "plain", clan=None, generation=None)
    plain.appears_as_agent = True
    anonymous_workflow = _agent(
        "anonymous-workflow",
        "anonymous-workflow",
        agent_type=AgentType.WORKFLOW,
        clan=None,
        generation=None,
    )
    anonymous_workflow.appears_as_agent = True

    family_text, _, _ = format_agent_option(family, 0, is_selected=False)
    planner_text, _, _ = format_agent_option(lone_planner, 1, is_selected=False)
    plain_text, _, _ = format_agent_option(plain, 2, is_selected=False)
    workflow_text, _, _ = format_agent_option(
        anonymous_workflow,
        3,
        is_selected=False,
    )

    assert family.is_family_container_row is True
    assert family_text.plain.startswith("cx")
    assert family_text.plain.endswith("cx")
    assert _style_at(family_text, family_text.plain.rindex("cx")) == "#00AFFF"
    assert lone_planner.is_family_container_row is False
    assert planner_text.plain.startswith("solo")
    assert _style_at(planner_text, planner_text.plain.rindex("solo")) == "#FFD700"
    assert plain_text.plain.startswith("plain")
    assert _style_at(plain_text, plain_text.plain.rindex("plain")) == "#FFD700"
    assert workflow_text.plain.startswith("anonymous-workflow")
    assert (
        _style_at(
            workflow_text,
            workflow_text.plain.rindex("anonymous-workflow"),
        )
        == "#FFD700"
    )

    family.agent_name = None
    family.presented_agent_name = None
    nameless_family_text, _, _ = format_agent_option(family, 4, is_selected=False)
    assert not nameless_family_text.plain.endswith(" ")


def test_clan_row_renders_unread_count_in_both_fold_states() -> None:
    done = _agent("research.done", "done", status="DONE")
    failed = _agent("research.failed", "failed", status="FAILED")
    container, failed, done = project_clan_tree([done, failed])
    container.llm_provider = "codex"
    unread_ids = {done.identity, failed.identity}

    collapsed, _, _ = format_agent_option(
        container,
        0,
        is_selected=False,
        fold_annotation=" ×2",
        unread_agent_ids=unread_ids,
    )
    expanded, _, _ = format_agent_option(
        container,
        0,
        is_selected=False,
        is_expanded=True,
        unread_agent_ids=unread_ids,
    )

    assert "[F1 U2]" in collapsed.plain
    assert "[F1 U2]" in expanded.plain
    assert "D" not in collapsed.plain.split("[", 1)[1]
    for clan_text in (collapsed, expanded):
        assert not clan_text.plain.startswith(" ")
        assert "  " not in clan_text.plain


def test_project_clan_tree_nests_disk_shaped_monitor_under_starter() -> None:
    family = _agent("sase-ns.6.6.6.1", "20260817055518")
    family.agent_family = "sase-ns.6.6.6.1"
    family.agent_family_role = "root"
    starter = _agent(
        "sase-ns.6.6.6.1--2",
        "20260817070811",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    starter.agent_family = family.agent_family
    starter.agent_family_role = "code"
    monitor = _agent(
        "sase-ns.6.6.6.1--mon-1",
        "20260817071511",
        parent_timestamp=starter.raw_suffix,
        clan=None,
        generation=None,
    )
    monitor.agent_family = family.agent_family
    monitor.agent_family_role = "monitor"
    peer = _agent("sase-ns.6.6.6.2", "20260817060000", status="DONE")

    projected = project_clan_tree([family, starter, monitor, peer])

    container = projected[0]
    assert container.is_clan_container is True
    assert monitor.agent_clan is None
    assert monitor.agent_clan_generation is None
    assert monitor.tree_parent_key == starter.raw_suffix
    assert monitor.tree_depth == starter.tree_depth + 1 == 3
    assert starter.tree_parent_key == family.raw_suffix
    assert starter.tree_depth == 2
    assert family.tree_depth == 1
    assert projected.index(monitor) == projected.index(starter) + 1
    assert projected == [container, family, starter, monitor, peer]


def test_project_clan_tree_keeps_tagged_and_disk_shaped_monitors_identical() -> None:
    family = _agent("research.family", "family")
    family.agent_family = "research.family"
    family.agent_family_role = "root"
    starter = _agent(
        "research.family--2",
        "starter",
        parent_timestamp=family.raw_suffix,
        clan=None,
        generation=None,
    )
    starter.agent_family = family.agent_family
    disk_monitor = _agent(
        "research.family--mon-1",
        "disk-mon",
        parent_timestamp=starter.raw_suffix,
        clan=None,
        generation=None,
    )
    disk_monitor.agent_family = family.agent_family
    disk_monitor.agent_family_role = "monitor"
    tagged_monitor = _agent(
        "research.family--mon-1",
        "tagged-mon",
        parent_timestamp=starter.raw_suffix,
        clan=family.agent_clan,
        generation=family.agent_clan_generation,
    )
    tagged_monitor.agent_family = family.agent_family
    tagged_monitor.agent_family_role = "monitor"

    disk_tree = project_clan_tree([family, starter, disk_monitor])
    tagged_tree = project_clan_tree([family, starter, tagged_monitor])

    assert [row.tree_depth for row in disk_tree] == [
        row.tree_depth for row in tagged_tree
    ]
    assert (
        disk_monitor.tree_parent_key
        == tagged_monitor.tree_parent_key
        == starter.raw_suffix
    )
    assert disk_monitor.tree_depth == tagged_monitor.tree_depth == 3
