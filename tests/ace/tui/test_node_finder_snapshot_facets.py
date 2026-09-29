"""Fold-facet and panel-tree snapshot tests for the Node Finder row model."""

from __future__ import annotations

from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_groups import GroupingMode, build_agent_tree
from tests.ace.tui._member_jump_navigation_helpers import (
    make_agent,
    make_agent_session,
    make_clan,
)
from tests.ace.tui._node_finder_snapshot_shared import (
    NodeFinderHarness,
    snapshot_started,
)

__all__ = [
    "test_fold_filter_facets_match_direct_reads",
    "test_panel_tree_state_matches_rebuild",
]


def _facet_tables(complete: list) -> tuple:
    from sase.ace.tui.actions.agents._node_finder_facets import (
        snapshot_all_facets,
    )

    return snapshot_all_facets(complete)[:5]


def _fold_states() -> list[str]:
    return ["collapsed", "expanded", "full"]


def _apply_fold_state(app: NodeFinderHarness, agents: list, state: str) -> None:
    from sase.ace.tui.models._agent_tree import agent_fold_key

    for agent in agents:
        key = agent_fold_key(agent)
        if not key:
            continue
        if state == "expanded":
            app._fold_manager.expand(key)
        elif state == "full":
            app._fold_manager.expand(key)
            app._fold_manager.expand(key)


def _hidden_step_shape() -> list:
    started = snapshot_started()
    hidden_root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="h",
        project_file="/p/p.sase",
        status="RUNNING",
        start_time=started,
        raw_suffix="ts-hidden-root",
        agent_name="h",
        workflow="hidden-flow",
    )
    hidden_step = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="hs",
        project_file="/p/p.sase",
        status="DONE",
        start_time=started,
        raw_suffix="ts-hidden-step",
        parent_workflow="hidden-flow",
        parent_timestamp="ts-hidden-root",
        step_name="setup",
        step_type="python",
        step_index=0,
        total_steps=1,
        is_hidden_step=True,
        role_suffix="--setup",
    )
    return [hidden_root, hidden_step]


def test_fold_filter_facets_match_direct_reads() -> None:
    """Facet-hoisted fold filtering keeps rows and counts identical."""
    from sase.ace.tui.models import filter_agents_by_fold_state
    from sase.ace.tui.models.fold_state import FoldLevel

    members, _container = make_clan(4)
    session_rows, _root, _child = make_agent_session(in_clan=True)
    rosters = [
        project_clan_tree([*members, *session_rows]),
        [make_agent("solo"), *_hidden_step_shape()],
    ]
    for complete in rosters:
        parent_keys, fold_keys, _depths, _identities, hidden_steps = _facet_tables(
            complete
        )
        for state in _fold_states():
            app = NodeFinderHarness(list(complete), complete[0])
            _apply_fold_state(app, complete, state)
            levels: dict[str, object] = dict(app._fold_manager.snapshot())
            for fold_key in fold_keys.values():
                if fold_key is not None:
                    levels[fold_key] = FoldLevel.FULLY_EXPANDED
            from sase.ace.tui.actions.agents._prospective_clan import (
                FoldStateProjection,
            )

            projection = FoldStateProjection(levels)  # type: ignore[arg-type]
            plain, plain_counts = filter_agents_by_fold_state(complete, projection)
            faceted, faceted_counts = filter_agents_by_fold_state(
                complete,
                projection,
                fold_keys=fold_keys,
                parent_keys=parent_keys,
                hidden_steps=hidden_steps,
            )
            assert [id(agent) for agent in faceted] == [id(agent) for agent in plain], (
                complete[0].agent_name,
                state,
            )
            assert faceted_counts == plain_counts, (complete[0].agent_name, state)


def test_panel_tree_state_matches_rebuild() -> None:
    """Reusing one roster index keeps panel trees byte-identical per mode."""
    from sase.ace.tui.models._agent_tree import (
        presentation_anchor_lookup,
        tree_parent_lookup,
    )
    from sase.ace.tui.models.agent_panels import AgentPanelGroup, agents_for_panel
    from sase.ace.tui.models.group_fold import GroupFoldRegistry

    members, _container = make_clan(6, mixed_tribes=True)
    complete = members
    for mode in (
        GroupingMode.STANDARD,
        GroupingMode.BY_DATE,
        GroupingMode.BY_STATUS,
        GroupingMode.BY_MACHINE,
    ):
        lookup = tree_parent_lookup(complete)
        anchors = presentation_anchor_lookup(complete, lookup)
        tree_state = (lookup, anchors)
        panel_group = AgentPanelGroup.from_agents(
            complete, merge_tribe_panels=False, tree_state=tree_state
        )
        for panel_key in panel_group.panel_keys:
            panel_agents = agents_for_panel(
                complete, panel_key, merge_tribe_panels=False, tree_state=tree_state
            )
            plain = build_agent_tree(
                panel_agents, fold_registry=GroupFoldRegistry(), mode=mode
            )
            reused = build_agent_tree(
                panel_agents,
                fold_registry=GroupFoldRegistry(),
                mode=mode,
                tree_state=tree_state
                if len(panel_agents) == len(complete)
                and all(
                    new is old for new, old in zip(panel_agents, complete, strict=True)
                )
                else None,
            )
            assert [(entry.kind, entry.agent_idx) for entry in reused] == [
                (entry.kind, entry.agent_idx) for entry in plain
            ], (mode, panel_key)
            assert [
                entry.group.group_key if entry.group is not None else None
                for entry in reused
            ] == [
                entry.group.group_key if entry.group is not None else None
                for entry in plain
            ], (mode, panel_key)
