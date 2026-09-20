"""Finalize-plan tests for an app that also projects fleet rows.

The worker computes the finalize plan off-thread; the UI thread publishes the
roster after projecting ``_agents_fleet_rows`` into it. These tests pin that the
plan is computed over the same rows that get published, and that a plan over any
other row set is discarded with a recorded reason instead of silently replacing
the roster (which dropped every fleet row and the tribe panels only they
occupied).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents._fleet_dispatch_launches import (
    AgentFleetDispatchLaunchMixin,
)
from sase.ace.tui.actions.agents._fleet_projection import AgentFleetProjectionMixin
from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyBoundary,
    PreparedApplyData,
    PreparedApplySnapshot,
    attach_finalize_plan_to_boundary,
    prepare_loaded_agents_apply_boundary,
    project_and_fold_rosters,
    rebase_prepared_apply_boundary_on_proc_projection,
)
from sase.ace.tui.actions.agents._loading_compute_finalize import (
    _compute_finalize_plan,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_group_fold import (
    AgentGroupFoldRegistry,
    AgentPanelFoldScope,
)
from sase.ace.tui.models.agent_groups import GroupingMode
from sase.ace.tui.models.agent_panels import panel_keys_for
from sase.ace.tui.util import trace
from sase.feature_flags import override_flags

from tests._agents_tab_graph_isolation_helpers import clan_graph
from tests._agents_tab_query_helpers import FakeAgentApp, _make_agent


@pytest.fixture(autouse=True)
def _pin_legacy_agent_query_dialect() -> Iterator[None]:
    """Default to the legacy dialect; tests that need the unified engine opt in."""
    with override_flags(agents_unified_query=False):
        yield


class _FleetFakeAgentApp(
    AgentFleetProjectionMixin,
    AgentFleetDispatchLaunchMixin,
    FakeAgentApp,
):
    """``FakeAgentApp`` that also projects ``_agents_fleet_rows`` after a load."""

    def __init__(self, query: str = "") -> None:
        super().__init__(query)
        self._agents_fleet_rows: list[Agent] = []
        self._agents_dispatch_provisional_rows: dict[str, Agent] = {}
        self._agents_local_with_children: list[Agent] = []
        self._agents_local_visible: list[Agent] = []


def _fleet_epic_row(name: str = "fleet-epic") -> Agent:
    return _make_agent(
        cl_name=name,
        agent_name=name,
        status="DONE",
        raw_suffix=f"apollo:{name}",
        tribe="epic",
        fleet_origin_alias="apollo",
    )


def _prepare_with_plan(
    app: _FleetFakeAgentApp,
    local_rows: list[Agent],
) -> tuple[PreparedApplyData, PreparedApplySnapshot, PreparedApplyBoundary]:
    """Run the worker's boundary + finalize-plan steps for *local_rows*."""
    prep = PreparedApplyData(
        filtered_agents=list(local_rows),
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )
    boundary = prepare_loaded_agents_apply_boundary(prep, snapshot)
    boundary = attach_finalize_plan_to_boundary(boundary, snapshot, content_index=None)
    assert boundary.finalize is not None
    return prep, snapshot, boundary


def _commit(
    app: _FleetFakeAgentApp,
    prep: PreparedApplyData,
    snapshot: PreparedApplySnapshot,
    boundary: PreparedApplyBoundary,
) -> None:
    """Commit a prepared boundary on the "UI thread"."""
    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
        persist_dismissed_changes=False,
        incomplete_merge_already_applied=True,
        precomputed_boundary=boundary,
        precomputed_fold_levels=snapshot.fold_levels,
    )


def _apply_with_plan(
    app: _FleetFakeAgentApp,
    local_rows: list[Agent],
) -> None:
    """Drive one disk apply through the worker's boundary and finalize plan."""
    _commit(app, *_prepare_with_plan(app, local_rows))


@pytest.mark.parametrize("unified_query", [False, True])
def test_plan_apply_keeps_fleet_rows_and_their_tribe_panel(
    unified_query: bool,
) -> None:
    """A non-drifting plan apply must publish the projected mixed roster."""
    local = [
        _make_agent(cl_name="alpha", status="RUNNING", raw_suffix="20260917090000"),
        _make_agent(cl_name="beta", status="DONE", raw_suffix="20260917090100"),
    ]
    fleet = _fleet_epic_row()
    with override_flags(agents_unified_query=unified_query):
        app = _FleetFakeAgentApp()
        app._agents_fleet_rows = [fleet]

        _apply_with_plan(app, local)

    assert fleet in app._agents
    assert fleet in app._agents_with_children
    assert "epic" in panel_keys_for(app._agents)


def test_plan_apply_keeps_fold_registry_entries_of_fleet_only_tribes() -> None:
    """Registry GC must enumerate the tribes of the roster actually published."""
    local = [
        _make_agent(cl_name="alpha", status="RUNNING", raw_suffix="20260917090000")
    ]
    fleet = _fleet_epic_row()
    app = _FleetFakeAgentApp()
    app._group_fold_registry = AgentGroupFoldRegistry()  # type: ignore[assignment]
    app._grouping_mode = GroupingMode.BY_STATUS
    app._agent_panels_grouped = False
    app._agents_fleet_rows = [fleet]
    epic_registry = app._group_fold_registry.for_panel("epic")
    epic_registry.collapse(("Done",))

    with override_flags(agents_unified_query=True):
        _apply_with_plan(app, local)

    assert fleet in app._agents
    assert AgentPanelFoldScope("epic") in app._group_fold_registry._registries
    assert epic_registry.is_collapsed(("Done",)) is True


@pytest.fixture
def trace_spans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Callable[[str], list[dict[str, Any]]]:
    """Enable span tracing and return a reader for spans by name."""
    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))

    def read(span: str) -> list[dict[str, Any]]:
        trace._flush_trace_writes()
        if not log.exists():
            return []
        rows = [json.loads(line) for line in log.read_text().splitlines() if line]
        return [row for row in rows if row.get("span") == span]

    return read


def test_plan_is_used_and_publishes_mixed_roster_when_fleet_rows_are_unchanged(
    trace_spans: Callable[[str], list[dict[str, Any]]],
) -> None:
    """Step 3 restored the off-thread path instead of just disabling it."""
    local = [
        _make_agent(cl_name="alpha", status="RUNNING", raw_suffix="20260917090000"),
        _make_agent(cl_name="beta", status="DONE", raw_suffix="20260917090100"),
    ]
    fleet = _fleet_epic_row()
    app = _FleetFakeAgentApp()
    app._agents_fleet_rows = [fleet]

    prep, snapshot, boundary = _prepare_with_plan(app, local)
    assert boundary.finalize is not None
    # The plan was computed over the mixed roster, not the local-only one.
    assert len(boundary.finalize.input_row_identities) == 3
    assert fleet.identity in boundary.finalize.input_row_identities
    assert boundary.finalize.panel_group_keys.keys() >= {AgentPanelFoldScope("epic")}

    _commit(app, prep, snapshot, boundary)

    (apply_span,) = trace_spans("agents.apply_loaded_agents_prepared")
    assert apply_span["finalize_plan"] == "applied"
    assert "finalize_plan_discard_reason" not in apply_span
    assert [agent.identity for agent in app._agents] == [
        agent.identity for agent in boundary.fold.visible_agents
    ]
    assert fleet.identity in [agent.identity for agent in app._agents]
    assert app._agents_local_visible == boundary.fold.local_visible_agents
    assert [a.identity for a in app._agents_local_with_children] == [
        a.identity for a in local
    ]
    (filter_span,) = trace_spans("agents.finalize_query_filter")
    assert filter_span["agents_in"] == 3
    assert filter_span["agents_out"] == 3
    assert "agents" not in filter_span


def test_plan_is_discarded_when_fleet_rows_move_during_the_worker(
    trace_spans: Callable[[str], list[dict[str, Any]]],
) -> None:
    """A fleet refresh between snapshot and commit must not be reverted."""
    local = [_make_agent(cl_name="alpha", status="RUNNING", raw_suffix="2026091709")]
    first = _fleet_epic_row("fleet-epic")
    app = _FleetFakeAgentApp()
    app._agents_fleet_rows = [first]
    prep, snapshot, boundary = _prepare_with_plan(app, local)

    # The stale token has no fleet field: only the row fingerprint can notice.
    second = _make_agent(
        cl_name="fleet-research",
        agent_name="fleet-research",
        status="DONE",
        raw_suffix="apollo:fleet-research",
        tribe="research",
        fleet_origin_alias="apollo",
    )
    app._agents_fleet_rows = [first, second]

    _commit(app, prep, snapshot, boundary)

    (apply_span,) = trace_spans("agents.apply_loaded_agents_prepared")
    assert apply_span["finalize_plan"] == "discarded"
    assert apply_span["finalize_plan_discard_reason"] == "roster_fingerprint"
    identities = [agent.identity for agent in app._agents]
    assert first.identity in identities
    assert second.identity in identities
    assert panel_keys_for(app._agents) == [None, "epic", "research"]


def test_plan_discard_reason_is_stale_token_when_query_drifts(
    trace_spans: Callable[[str], list[dict[str, Any]]],
) -> None:
    a = _make_agent(cl_name="alpha", status="RUNNING", raw_suffix="20260917090000")
    b = _make_agent(cl_name="beta", status="FAILED", raw_suffix="20260917090100")
    app = _FleetFakeAgentApp(query="status:running")
    prep, snapshot, boundary = _prepare_with_plan(app, [a, b])

    app._agent_search_query = "status:failed"
    _commit(app, prep, snapshot, boundary)

    (apply_span,) = trace_spans("agents.apply_loaded_agents_prepared")
    assert apply_span["finalize_plan"] == "discarded"
    assert apply_span["finalize_plan_discard_reason"] == "stale_token"
    assert app._agents == [b]


def test_apply_without_a_worker_plan_reports_absent(
    trace_spans: Callable[[str], list[dict[str, Any]]],
) -> None:
    fleet = _fleet_epic_row()
    app = _FleetFakeAgentApp()
    app._agents_fleet_rows = [fleet]
    prep = PreparedApplyData(
        filtered_agents=[_make_agent(cl_name="alpha", raw_suffix="20260917090000")],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )

    app._apply_loaded_agents_prepared(
        prep,
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
        persist_dismissed_changes=False,
    )

    (apply_span,) = trace_spans("agents.apply_loaded_agents_prepared")
    assert apply_span["finalize_plan"] == "absent"
    assert "finalize_plan_discard_reason" not in apply_span
    assert fleet.identity in [agent.identity for agent in app._agents]


def test_select_finalize_plan_refuses_plan_over_a_different_row_set() -> None:
    a = _make_agent(cl_name="alpha", status="RUNNING", raw_suffix="20260917090000")
    b = _make_agent(cl_name="beta", status="DONE", raw_suffix="20260917090100")
    app = FakeAgentApp()
    app._agents = [a, b]
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )
    plan = _compute_finalize_plan([a, b], snapshot)
    assert plan.input_row_identities == (a.identity, b.identity)

    extra: dict[str, Any] = {}
    for roster in ([a], [b, a]):
        app._agents = roster
        assert (
            app._select_finalize_plan(
                plan,
                on_agents_tab=False,
                selected_identity=None,
                trace_extra=extra,
            )
            is None
        )
        assert extra["finalize_plan_discard_reason"] == "roster_fingerprint"

    app._agents = [a, b]
    assert (
        app._select_finalize_plan(
            plan,
            on_agents_tab=False,
            selected_identity=None,
        )
        is plan
    )


def test_proc_rebase_reprojects_fleet_rows_and_drops_the_plan() -> None:
    """The proc rebase edits local rows and must keep the roster projected."""
    local = _make_agent(cl_name="alpha", status="RUNNING", raw_suffix="20260917090000")
    fleet = _fleet_epic_row()
    proc_shell = _make_agent(
        agent_type=AgentType.PROC_SHELL,
        cl_name="sase",
        raw_suffix="proc-1",
        status="RUNNING",
        proc_id="proc-1",
    )
    app = _FleetFakeAgentApp()
    app._agents_fleet_rows = [fleet]
    prep, snapshot, boundary = _prepare_with_plan(app, [local])

    rebased = rebase_prepared_apply_boundary_on_proc_projection(
        boundary,
        replace(
            app._make_prepared_apply_snapshot(
                on_agents_tab=False,
                selected_identity=None,
                load_state=None,
            ),
            cached_agents_with_children=[proc_shell],
            proc_generation=7,
        ),
    )

    assert rebased.finalize is None
    assert rebased.proc_generation == 7
    fold = rebased.fold
    assert [a.identity for a in fold.local_visible_agents] == [
        local.identity,
        proc_shell.identity,
    ]
    for roster in (fold.visible_agents, fold.unfiltered_agents):
        assert {a.identity for a in roster} == {
            local.identity,
            proc_shell.identity,
            fleet.identity,
        }
    del prep, snapshot


def test_finalize_query_filter_span_reports_input_and_output_counts(
    trace_spans: Callable[[str], list[dict[str, Any]]],
) -> None:
    a = _make_agent(cl_name="alpha", status="RUNNING", raw_suffix="20260917090000")
    b = _make_agent(cl_name="beta", status="FAILED", raw_suffix="20260917090100")
    app = FakeAgentApp(query="status:running")
    snapshot = app._make_prepared_apply_snapshot(
        on_agents_tab=False,
        selected_identity=None,
        load_state=None,
    )

    _compute_finalize_plan([a, b], snapshot)

    (span,) = trace_spans("agents.finalize_query_filter")
    assert (span["agents_in"], span["agents_out"]) == (2, 1)
    assert "agents" not in span


def _clan_members() -> list[Agent]:
    """Loader rows of one epic-tribe clan (the loader never returns containers)."""
    return [agent for agent in clan_graph() if not agent.is_clan_container]


def test_project_and_fold_rosters_keeps_the_container_of_a_collapsed_clan() -> None:
    """Folding first and projecting after drops the container of a collapsed clan.

    The clan-tree projection rebuilds a container only from member rows it still
    sees, and a collapsed clan's fold hides every member.
    """
    members = clan_graph()
    (container,) = [agent for agent in members if agent.is_clan_container]

    unfiltered, visible, _counts = project_and_fold_rosters(members, (), {})

    assert container.identity in [agent.identity for agent in unfiltered]
    assert [agent.identity for agent in visible] == [container.identity]


@pytest.mark.parametrize("with_worker_plan", [True, False])
@pytest.mark.parametrize("with_fleet_row", [True, False])
def test_apply_publishes_the_container_of_a_collapsed_clan(
    with_worker_plan: bool,
    with_fleet_row: bool,
) -> None:
    """A tribe panel made of clan containers survives every apply.

    The live regression: the inline apply projected the fold-filtered roster and
    lost every collapsed epic clan, so ``@epic`` vanished from the roster until
    the next fleet refresh rebuilt it (``2 -> 1 -> 2`` panels).
    """
    members = _clan_members()
    app = _FleetFakeAgentApp()
    if with_fleet_row:
        app._agents_fleet_rows = [
            _make_agent(
                cl_name="fleet-review",
                status="DONE",
                raw_suffix="apollo:fleet-review",
                tribe="review",
                fleet_origin_alias="apollo",
            )
        ]

    if with_worker_plan:
        _apply_with_plan(app, members)
    else:
        app._apply_loaded_agents_prepared(
            PreparedApplyData(
                filtered_agents=list(members),
                has_always_visible=True,
                hidden_count=0,
                hideable_agents=[],
                dismissed_agent_objects=[],
            ),
            on_agents_tab=False,
            selected_identity=None,
            load_state=None,
            persist_dismissed_changes=False,
        )

    assert [a.identity for a in app._agents if a.is_clan_container] == [
        (AgentType.RUNNING, "clan:epic-clan", "g1")
    ]
    assert "epic" in panel_keys_for(app._agents)
