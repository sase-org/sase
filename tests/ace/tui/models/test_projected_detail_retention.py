"""Bounded-retention ownership tests: one snapshot generation, bounded detail.

Phase ``bounded-retention`` (child epic ``sase-1t3.10.1``): the TUI retains
one compact snapshot generation and a bounded selected-detail owner instead
of an eight-entry cache plus unbounded per-selection full-record
accumulation.

This module preserves the original pytest and public import path while the
test groups live in private implementation modules.
"""

from ._test_projected_detail_retention_cache import (
    test_compact_cache_retains_single_generation,
    test_compact_lock_busy_serves_only_same_key_stale,
    test_list_path_never_decodes_full_records,
    test_superseded_compact_query_cannot_publish_old_window,
)
from ._test_projected_detail_retention_owner import (
    test_orphaned_hydrated_agents_stay_collectible,
    test_release_restores_compact_list_facts,
    test_roster_copies_restore_compact_facts_without_detail,
    test_same_identity_replacements_release_displaced_payloads,
    test_selected_detail_owner_bounds_hydrated_agents,
)
from ._test_projected_detail_retention_worker import (
    test_canceled_hydration_worker_never_applies_detached_payload,
    test_hydration_worker_drops_result_after_tab_switch,
    test_hydration_worker_drops_result_for_equal_identity_replacement,
    test_monitor_identity_uses_compact_scalar_without_metadata_file_read,
)

__all__ = (
    "test_canceled_hydration_worker_never_applies_detached_payload",
    "test_compact_cache_retains_single_generation",
    "test_compact_lock_busy_serves_only_same_key_stale",
    "test_hydration_worker_drops_result_after_tab_switch",
    "test_hydration_worker_drops_result_for_equal_identity_replacement",
    "test_list_path_never_decodes_full_records",
    "test_monitor_identity_uses_compact_scalar_without_metadata_file_read",
    "test_orphaned_hydrated_agents_stay_collectible",
    "test_release_restores_compact_list_facts",
    "test_roster_copies_restore_compact_facts_without_detail",
    "test_same_identity_replacements_release_displaced_payloads",
    "test_selected_detail_owner_bounds_hydrated_agents",
    "test_superseded_compact_query_cannot_publish_old_window",
)
