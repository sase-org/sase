"""Worker/UI ownership isolation for Agents-tab row graphs.

The public test import path stays here; implementation tests live in focused,
private modules so pytest collects them only through this facade.
"""

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    merge_incomplete_load_after_complete_history,
    prepare_loaded_agents_worker_boundary,
)
from sase.ace.tui.actions.agents._loading_refresh import (
    ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S,
    TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.widgets._agent_list_helpers import ordered_row_providers
from tests._agents_tab_graph_isolation_helpers import (
    agent_session_graph,
    agent_session_root,
    clan_container,
    clan_graph,
    delta_load_state,
    row_observation,
    row_prefix,
    unrelated_delta,
)
from tests._agents_tab_query_helpers import FakeAgentApp
from tests.ace.tui._lazy_tier2_reconcile_helpers import FakeRefreshApp

from tests._agents_tab_graph_isolation_workers import (
    test_abandoned_worker_thread_cannot_mutate_live_graph,
    test_worker_exception_does_not_damage_live_graph,
    test_worker_pause_does_not_clear_live_agent_session_links,
    test_worker_pause_does_not_clear_live_clan_providers,
)
from tests._agents_tab_graph_isolation_publication import (
    test_apply_publishes_legitimate_provider_and_child_updates,
    test_bounded_prefix_then_completion_keeps_discovered_rows,
    test_exact_delta_deletion_and_dismissal_apply_on_publish,
    test_incomplete_merge_does_not_alias_live_cached_rows,
    test_query_reconcile_then_tier1_does_not_retreat,
    test_quiet_thresholds_fire_roster_completion_then_tier2_with_fake_time,
    test_ten_unrelated_deltas_keep_live_clan_providers,
)
from tests._agents_tab_graph_isolation_copy_cost import (
    test_authoritative_replacement_copies_no_cached_history,
    test_authoritative_with_capacity_report_leaves_cached_history_untouched,
    test_authoritative_without_proc_projection_copies_only_named_proc_fallback,
    test_delta_patch_with_empty_incoming_capacity_skips_capacity_copy,
    test_query_change_bounded_prefix_copies_no_cached_history,
)

__all__ = [
    "test_abandoned_worker_thread_cannot_mutate_live_graph",
    "test_apply_publishes_legitimate_provider_and_child_updates",
    "test_authoritative_replacement_copies_no_cached_history",
    "test_authoritative_with_capacity_report_leaves_cached_history_untouched",
    "test_authoritative_without_proc_projection_copies_only_named_proc_fallback",
    "test_bounded_prefix_then_completion_keeps_discovered_rows",
    "test_delta_patch_with_empty_incoming_capacity_skips_capacity_copy",
    "test_exact_delta_deletion_and_dismissal_apply_on_publish",
    "test_incomplete_merge_does_not_alias_live_cached_rows",
    "test_query_change_bounded_prefix_copies_no_cached_history",
    "test_query_reconcile_then_tier1_does_not_retreat",
    "test_quiet_thresholds_fire_roster_completion_then_tier2_with_fake_time",
    "test_ten_unrelated_deltas_keep_live_clan_providers",
    "test_worker_exception_does_not_damage_live_graph",
    "test_worker_pause_does_not_clear_live_agent_session_links",
    "test_worker_pause_does_not_clear_live_clan_providers",
    "Agent",
    "AgentLoadState",
    "FakeAgentApp",
    "FakeRefreshApp",
    "PreparedApplyData",
    "ROSTER_COMPLETION_INPUT_QUIET_THRESHOLD_S",
    "TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S",
    "agent_session_graph",
    "agent_session_root",
    "clan_container",
    "clan_graph",
    "delta_load_state",
    "merge_incomplete_load_after_complete_history",
    "ordered_row_providers",
    "prepare_loaded_agents_worker_boundary",
    "row_observation",
    "row_prefix",
    "unrelated_delta",
]
