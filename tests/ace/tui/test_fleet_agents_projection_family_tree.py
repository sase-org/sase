from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.fleet_fixture import fleet_host_response, fleet_summary


def _remote_family_summaries() -> tuple[dict[str, object], ...]:
    root = fleet_summary(
        agent_id="remote-family",
        run_id="20260910120000",
        agent_name="remote-family",
        family_id="remote-family",
        family_role="root",
    )
    code = fleet_summary(
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
    gate = fleet_summary(
        agent_id="remote-family--gate",
        run_id="20260910120300",
        agent_name="remote-family--gate",
        family_id="remote-family",
        family_role="gate",
        row_kind="gate",
        parent_timestamp="20260910120000",
        occupied_runner_slot=False,
    )
    proc = fleet_summary(
        agent_id="remote-family--proc",
        run_id="20260910120400",
        agent_name="remote-family--proc",
        family_id="remote-family",
        family_role="proc",
        row_kind="proc",
        parent_timestamp="20260910120000",
        occupied_runner_slot=False,
    )
    return root, code, monitor, gate, proc


def _tree_shape(agents: list[Agent]) -> list[tuple[object, ...]]:
    return [
        (
            agent.identity,
            agent.parent_timestamp,
            agent.is_family_container_row,
            agent.is_clan_container,
            agent.is_remote_family_container,
            tuple(child.identity for child in agent.followup_agents),
            agent.fleet_origin_alias,
        )
        for agent in agents
    ]


def test_project_fleet_agents_builds_a_remote_family_container_with_shells() -> None:
    response = fleet_host_response(
        alias="apollo",
        summaries=_remote_family_summaries(),
    )

    projection = project_fleet_agents(catalog_response=response)
    rows = list(projection.fleet_rows)
    by_name = {row.agent_name: row for row in rows}
    root = by_name["remote-family"]
    code = by_name["remote-family--code"]
    monitor = by_name["remote-family--mon"]
    gate = by_name["remote-family--gate"]
    proc = by_name["remote-family--proc"]

    assert root.is_family_container_row is True
    assert root.fleet_origin_alias == "apollo"
    assert {child.agent_name for child in root.followup_agents} == {
        "remote-family--code",
        "remote-family--mon",
        "remote-family--gate",
        "remote-family--proc",
    }
    assert code.is_family_member_child is True
    assert monitor.is_monitor is True
    assert gate.is_gate is True
    assert proc.is_proc_shell is True
    assert all(
        child.parent_timestamp == root.raw_suffix for child in root.followup_agents
    )
    left, _, _ = format_agent_option(root, 0, is_selected=False)
    assert "[agent]" not in left.plain
    from sase.ace.tui.widgets._agent_list_helpers import compute_fold_annotation

    annotation = compute_fold_annotation(
        root,
        {root.raw_suffix: (len(root.followup_agents), 0)},
        set(),
    )
    assert annotation.startswith(" ×")


def test_project_fleet_agents_drops_container_plus_concrete_duplicates() -> None:
    concrete = fleet_summary(
        agent_id="sase-zr.1",
        run_id="run-current",
        agent_name="sase-zr.1",
        family_id="sase-zr",
        family_role="root",
        current_instance=True,
        revision=4,
    )
    container = fleet_summary(
        agent_id="sase-zr.1",
        run_id="run-container",
        agent_name="sase-zr.1",
        family_id="sase-zr",
        family_role="root",
        row_kind="container_header",
        current_instance=False,
        container_projected_concrete_agent=True,
        revision=3,
    )
    member = fleet_summary(
        agent_id="sase-zr.1--code",
        run_id="run-code",
        agent_name="sase-zr.1--code",
        family_id="sase-zr",
        family_role="member",
        parent_timestamp="run-current",
    )
    response = fleet_host_response(
        alias="apollo",
        summaries=(container, concrete, member),
    )

    projection = project_fleet_agents(catalog_response=response)
    names = [row.agent_name for row in projection.fleet_rows]
    assert names.count("sase-zr.1") == 1
    root = next(row for row in projection.fleet_rows if row.agent_name == "sase-zr.1")
    assert root.fleet_current_instance is True
    assert root.fleet_row_kind == "agent_shell"
    assert root.is_family_container_row is True


def test_project_fleet_agents_drops_superseded_non_current_top_level_instances() -> (
    None
):
    current = fleet_summary(
        agent_id="solo",
        run_id="run-new",
        agent_name="solo",
        family_id=None,
        current_instance=True,
        revision=5,
    )
    stale = fleet_summary(
        agent_id="solo",
        run_id="run-old",
        agent_name="solo",
        family_id=None,
        current_instance=False,
        status="done",
        revision=2,
    )
    historical = fleet_summary(
        agent_id="solo",
        run_id="run-history",
        agent_name="solo--old",
        family_id="solo",
        family_role="historical_shell",
        row_kind="historical_shell",
        current_instance=False,
        parent_timestamp="run-new",
        status="done",
        revision=1,
    )
    response = fleet_host_response(
        alias="apollo",
        summaries=(stale, current, historical),
    )

    projection = project_fleet_agents(catalog_response=response)
    by_name = {row.agent_name: row for row in projection.fleet_rows}
    assert "solo" in by_name
    assert by_name["solo"].fleet_current_instance is True
    assert "solo--old" in by_name
    assert by_name["solo--old"].parent_timestamp == by_name["solo"].raw_suffix
    assert [row.agent_name for row in projection.fleet_rows].count("solo") == 1


def test_project_fleet_agents_nests_under_real_root_instead_of_synthesizing() -> None:
    """Owner family identity is enough to attach members when run ids differ."""
    root = fleet_summary(
        agent_id="crew",
        run_id="20260910120000",
        agent_name="crew",
        family_id="crew",
        family_role="root",
        status="TALE DONE",
        current_instance=False,
    )
    historical = fleet_summary(
        agent_id="crew--plan",
        run_id="20260910113000",
        agent_name="crew--plan",
        family_id="crew",
        family_role="historical_shell",
        row_kind="historical_shell",
        parent_timestamp="crew",
        status="TALE DONE",
        current_instance=False,
    )
    response = fleet_host_response(alias="apollo", summaries=(root, historical))

    projection = project_fleet_agents(catalog_response=response)
    rows = list(projection.fleet_rows)
    by_name = {row.agent_name: row for row in rows}
    assert "crew" in by_name
    assert by_name["crew"].is_remote_family_container is False
    assert by_name["crew--plan"].parent_timestamp == by_name["crew"].raw_suffix
    assert not any(row.is_remote_family_container for row in rows)


def test_project_fleet_agents_synthesizes_a_stable_root_when_page_omits_it() -> None:
    code = fleet_summary(
        agent_id="crew--code",
        run_id="20260910120100",
        agent_name="crew--code",
        family_id="crew",
        family_role="member",
        parent_timestamp="20260910120000",
    )
    monitor = fleet_summary(
        agent_id="crew--mon",
        run_id="20260910120200",
        agent_name="crew--mon",
        family_id="crew",
        family_role="monitor",
        row_kind="monitor",
        parent_timestamp="20260910120000",
        occupied_runner_slot=False,
    )
    response = fleet_host_response(alias="apollo", summaries=(code, monitor))

    first = project_fleet_agents(catalog_response=response)
    second = project_fleet_agents(catalog_response=response)
    roots = [row for row in first.fleet_rows if not row.is_family_member_child]
    assert len(roots) == 1
    container = roots[0]
    assert container.is_remote_family_container is True
    assert container.is_family_container_row is True
    assert container.agent_family == "crew"
    assert container.raw_suffix == "fleet:apollo:family:crew"
    assert container.identity == second.fleet_rows[0].identity or any(
        row.identity == container.identity for row in second.fleet_rows
    )
    assert _tree_shape(list(first.fleet_rows)) == _tree_shape(list(second.fleet_rows))


def test_project_fleet_agents_preserves_selection_identity_across_refresh() -> None:
    response = fleet_host_response(
        alias="apollo",
        summaries=_remote_family_summaries(),
    )
    first = project_fleet_agents(catalog_response=response)
    selected = next(row for row in first.fleet_rows if row.is_family_container_row)
    second = project_fleet_agents(catalog_response=response)
    assert any(row.identity == selected.identity for row in second.fleet_rows)
    assert _tree_shape(list(first.fleet_rows)) == _tree_shape(list(second.fleet_rows))


def test_project_mixed_agent_tree_matches_reproject_and_refilter_shapes() -> None:
    from sase.ace.tui.actions.agents._fleet_projection import AgentFleetProjectionMixin
    from sase.ace.tui.models._agent_tree import project_mixed_agent_tree

    local = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research.one",
        project_file="/tmp/sase.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 17, 10, 0, 0),
        raw_suffix="local-one",
        agent_name="research.one",
        agent_clan="research",
        agent_clan_generation="g1",
    )
    local_peer = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="research.two",
        project_file="/tmp/sase.sase",
        status="DONE",
        start_time=datetime(2026, 7, 17, 10, 1, 0),
        raw_suffix="local-two",
        agent_name="research.two",
        agent_clan="research",
        agent_clan_generation="g1",
    )
    remote = list(
        project_fleet_agents(
            catalog_response=fleet_host_response(
                alias="apollo",
                summaries=_remote_family_summaries(),
            )
        ).fleet_rows
    )
    expected = project_mixed_agent_tree([local, local_peer], remote)
    assert any(row.is_clan_container for row in expected)
    assert any(
        row.is_family_container_row and row.fleet_origin_alias == "apollo"
        for row in expected
    )

    class _Harness(AgentFleetProjectionMixin):
        def __init__(self) -> None:
            self.current_agents_subtab = "focus"
            self.current_tab = "agents"
            self.current_idx = 0
            self._agents = [local]
            self._agents_with_children = [local, local_peer]
            self._agents_local_with_children = [local, local_peer]
            self._agents_fleet_rows = remote
            self._agents_refresh_active_source = "unknown"

        def _fleet_rows_with_dispatch_provisionals(
            self, rows: list[Agent]
        ) -> list[Agent]:
            return rows

        def _finalize_agent_list(self, *_args: object, **_kwargs: object) -> None:
            self._agents = list(self._agents_with_children)

        def _update_agents_header(self) -> None:
            return None

    harness = _Harness()
    harness._reproject_agents_from_current_mode(source="fleet_refresh")
    assert _tree_shape(harness._agents_with_children) == _tree_shape(expected)
    refiltered = harness._agents_source_for_current_mode(
        list(harness._agents_local_with_children)
    )
    assert _tree_shape(refiltered) == _tree_shape(expected)
