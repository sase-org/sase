"""Row rendering for clan containers and their member rows."""

from __future__ import annotations

from datetime import datetime

from rich.text import Text

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option

from ._agent_tree_helpers import _agent


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


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
    assert member_text.plain.startswith("  │  └─ (RUNNING)")
    assert "research.family--code" in member_text.plain
    assert not member_text.plain.startswith("  │  └─ research.family--code")


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


def test_remote_family_container_renders_without_agent_bracket() -> None:
    from sase.ace.tui.models.fleet_agents import project_fleet_agents
    from sase.ace.tui.widgets._agent_list_helpers import compute_fold_annotation
    from tests.ace.tui.fleet_fixture import fleet_host_response, fleet_summary

    root = fleet_summary(
        agent_id="remote-family",
        run_id="20260910120000",
        agent_name="remote-family",
        family_id="remote-family",
        family_role="root",
    )
    member = fleet_summary(
        agent_id="remote-family--code",
        run_id="20260910120100",
        agent_name="remote-family--code",
        family_id="remote-family",
        family_role="member",
        parent_timestamp="20260910120000",
    )
    monitor = fleet_summary(
        agent_id="remote-family--mon",
        run_id="20260910120200",
        agent_name="remote-family--mon",
        family_id="remote-family",
        family_role="monitor",
        row_kind="monitor",
        parent_timestamp="20260910120000",
        occupied_runner_slot=False,
    )
    rows = list(
        project_fleet_agents(
            catalog_response=fleet_host_response(
                alias="apollo",
                summaries=(root, member, monitor),
            )
        ).fleet_rows
    )
    family = next(row for row in rows if row.is_family_container_row)
    nested = [row for row in rows if row.parent_timestamp == family.raw_suffix]
    annotation = compute_fold_annotation(
        family,
        {family.raw_suffix: (len(nested), 0)},
        set(),
    )
    family_text, _, _ = format_agent_option(
        family,
        0,
        is_selected=False,
        fold_annotation=annotation,
    )
    assert "[agent]" not in family_text.plain
    assert annotation.startswith(" ×")
    assert annotation in family_text.plain
    monitor_row = next(row for row in nested if row.is_monitor)
    monitor_text, _, _ = format_agent_option(monitor_row, 1, is_selected=False)
    assert monitor_row.is_family_member_child is True
    assert "⚙" in monitor_text.plain or monitor_row.is_monitor
