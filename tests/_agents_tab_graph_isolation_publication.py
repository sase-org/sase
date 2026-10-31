"""Load publication and reconciliation tests for the Agents tab graph."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_refresh import (
    ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S,
    TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
)
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.widgets._agent_list_helpers import ordered_row_providers
from tests._agents_tab_graph_isolation_helpers import (
    clan_container,
    clan_graph,
    delta_load_state,
    row_observation,
    row_prefix,
    unrelated_delta,
)
from tests._agents_tab_incomplete_merge_helpers import incomplete_tier1_snapshot
from tests._agents_tab_query_helpers import FakeAgentApp, make_agent
from tests.ace.tui._lazy_tier2_reconcile_helpers import FakeRefreshApp


def test_apply_publishes_legitimate_provider_and_child_updates() -> None:
    live = clan_graph()
    container = clan_container(live)
    prefix = row_prefix(container)
    new_member = make_agent(
        cl_name="epic-grok",
        raw_suffix="20260918090300",
        status="RUNNING",
        llm_provider="grok",
        agent_clan="epic-clan",
        agent_clan_generation="g1",
        tribe="epic",
        start_time=datetime(2026, 9, 18, 9, 3, 0),
        run_start_time=datetime(2026, 9, 18, 9, 3, 0),
    )
    incoming = [agent for agent in live if not agent.is_clan_container] + [new_member]
    app = FakeAgentApp()
    app._agents_with_children = live
    app._agents = list(live)
    app._agents_seen_complete_history = True
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=incoming,
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=delta_load_state(),
        persist_dismissed_changes=False,
    )
    assert row_prefix(container) == prefix
    published = clan_container(app._agents_with_children)
    assert published is not container
    published_prefix = row_prefix(published)
    assert "🎭" in published_prefix and "🤖" in published_prefix
    assert "🚀" in published_prefix


def test_incomplete_merge_does_not_alias_live_cached_rows() -> None:
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    other = unrelated_delta()
    prep = PreparedApplyData(
        filtered_agents=[other],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[other],
        dismissed_agent_objects=[],
    )
    snapshot = incomplete_tier1_snapshot(
        live,
        artifact_source="artifact_delta",
        used_artifact_index=False,
        capacity_agents_with_children=live,
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert row_observation(container) == before
    assert all(agent is not container for agent in prep.filtered_agents)
    published = clan_container(prep.filtered_agents)
    assert published is not container
    assert ordered_row_providers(published) == ("claude", "codex")
    assert all(agent is not live[0] for agent in prep.capacity_agents)


def test_bounded_prefix_then_completion_keeps_discovered_rows() -> None:
    first = make_agent(
        cl_name="startup-first",
        raw_suffix="20260918070100",
        status="RUNNING",
        llm_provider="claude",
    )
    second = make_agent(
        cl_name="startup-second",
        raw_suffix="20260918070200",
        status="RUNNING",
        llm_provider="codex",
    )
    app = FakeAgentApp()
    prefix_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=1,
        returned_count=1,
        has_more=True,
    )
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[first],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=prefix_state,
        persist_dismissed_changes=False,
    )
    assert [agent.identity for agent in app._agents_with_children] == [first.identity]
    live_first = app._agents_with_children[0]
    live_prefix = row_prefix(live_first)

    completion = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=2,
        returned_count=2,
        has_more=False,
    )
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[first, second],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=completion,
        persist_dismissed_changes=False,
    )
    identities = {agent.identity for agent in app._agents_with_children}
    assert first.identity in identities
    assert second.identity in identities
    assert row_prefix(live_first) == live_prefix


def test_exact_delta_deletion_and_dismissal_apply_on_publish() -> None:
    kept = make_agent(
        cl_name="kept",
        raw_suffix="20260918110100",
        status="RUNNING",
        artifacts_dir="/tmp/artifacts/ace-run/20260918110100",
    )
    removed = make_agent(
        cl_name="removed",
        raw_suffix="20260918110200",
        status="DONE",
        artifacts_dir="/tmp/artifacts/ace-run/20260918110200",
    )
    app = FakeAgentApp()
    app._agents_with_children = [kept, removed]
    app._agents = [kept, removed]
    app._agents_seen_complete_history = True
    app._dismissed_agents.add(removed.identity)
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[kept],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_delta",
            used_artifact_index=False,
            deleted_artifact_dirs=frozenset({"/tmp/artifacts/ace-run/20260918110200"}),
        ),
        persist_dismissed_changes=False,
    )
    assert [agent.identity for agent in app._agents_with_children] == [kept.identity]


def test_query_reconcile_then_tier1_does_not_retreat() -> None:
    historical = make_agent(
        cl_name="history-row",
        raw_suffix="20260917010100",
        status="DONE",
    )
    live = make_agent(
        cl_name="live-row",
        raw_suffix="20260918010100",
        status="RUNNING",
        llm_provider="claude",
    )
    app = FakeAgentApp(query="status:RUNNING")
    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[historical, live],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier2",
            complete_history=True,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
        persist_dismissed_changes=False,
    )
    discovered = {agent.identity for agent in app._agents_with_children}
    assert historical.identity in discovered
    assert live.identity in discovered

    app._apply_loaded_agents_prepared(
        PreparedApplyData(
            filtered_agents=[live],
            has_always_visible=True,
            hidden_count=0,
            hideable_agents=[],
            dismissed_agent_objects=[],
        ),
        on_agents_tab=False,
        selected_identity=None,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
            bounded_prefix=True,
            requested_limit=1,
            returned_count=1,
            has_more=True,
        ),
        persist_dismissed_changes=False,
    )
    retained = {agent.identity for agent in app._agents_with_children}
    assert historical.identity in retained
    assert live.identity in retained


def test_ten_unrelated_deltas_keep_live_clan_providers() -> None:
    live = clan_graph()
    container = clan_container(live)
    before = row_observation(container)
    prefix = row_prefix(container)
    app = FakeAgentApp()
    app._agents_with_children = live
    app._agents = list(live)
    app._agents_seen_complete_history = True
    for tick in range(10):
        other = make_agent(
            cl_name=f"delta-{tick}",
            raw_suffix=f"2026091811{tick:02d}00",
            status="DONE",
            start_time=datetime(2026, 9, 18, 11, tick, 0),
        )
        snapshot = app._make_prepared_apply_snapshot(
            on_agents_tab=False,
            selected_identity=None,
            load_state=delta_load_state(),
        )
        prepare_loaded_agents_worker_boundary(
            [other],
            [],
            set(),
            False,
            snapshot,
        )
        assert row_observation(container) == before
        assert row_prefix(container) == prefix


def test_quiet_thresholds_fire_roster_completion_then_tier2_with_fake_time() -> None:
    app = FakeRefreshApp()
    app._last_input_mono = 10.0
    app._arm_agents_history_reconcile(
        quiet_s=ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S,
        now_mono=10.0,
    )

    assert (
        app._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=10.0 + ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S - 0.1
        )
        is False
    )
    assert (
        app._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=10.0 + ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S + 0.1
        )
        is True
    )

    app._agents_refresh_scheduled = False
    app._last_input_mono = 10.0
    app._arm_agents_history_reconcile(
        quiet_s=TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
        now_mono=10.0,
    )
    assert (
        app._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=10.0 + ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S + 0.1
        )
        is False
    )
    assert (
        app._maybe_trigger_input_quiet_tier2_reconcile(
            now_mono=10.0 + TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S + 0.1
        )
        is True
    )
