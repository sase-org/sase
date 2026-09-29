"""Rebuild and discovery tests for the durable agent-name registry.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_agent_name_registry_rebuild_containers import (
    test_registry_rebuild_agent_session_container_outranks_auto_prefix,
    test_registry_rebuild_clan_container_outranks_auto_prefix,
    test_registry_rebuild_collects_active_agent,
    test_registry_rebuild_collects_agent_session_container,
    test_registry_rebuild_collects_clan_container,
    test_registry_rebuild_collects_numeric_auto_prefix,
)
from tests.test_agent_name_registry_rebuild_pending import (
    test_locked_fallback_keeps_live_identity_pending_claim,
    test_registry_rebuild_derives_named_meta_landing_after_scan,
    test_registry_rebuild_drops_claim_for_removed_dir,
    test_registry_rebuild_drops_claim_when_dir_names_another_identity,
    test_registry_rebuild_drops_dead_identity_pending_claim,
    test_registry_rebuild_keeps_live_identity_pending_claim,
    test_registry_rebuild_keeps_live_identity_pending_clan_claim,
)
from tests.test_agent_name_registry_rebuild_sources import (
    test_registry_rebuild_collects_bundle_only_agent,
    test_registry_rebuild_collects_dismissed_artifact,
    test_registry_rebuild_collects_done_agent,
    test_registry_rebuild_collects_sharded_agent_and_tracks_day_dir,
    test_registry_rebuild_resolves_one_identity_snapshot_for_all_sources,
    test_registry_rebuild_stays_under_sase_home,
    test_registry_signature_detects_dismissed_bundle_changes,
    test_registry_signature_ignores_live_artifact_output,
    test_registry_source_scan_caches_unchanged_artifact_walks,
    test_registry_source_scan_caches_unchanged_shards,
)
from tests.test_agent_name_registry_rebuild_staleness import (
    test_cached_registry_avoids_repeated_tree_walks,
    test_display_agent_session_read_never_rebuilds_a_stale_registry,
    test_display_agent_session_read_rebuilds_when_no_registry_exists,
    test_legacy_v2_registry_with_agent_family_kinds_upgrades_to_session_v3,
    test_lowest_name_suggestion,
    test_missing_index_rebuilds_on_lookup,
    test_registry_load_session_memoizes_source_signature,
    test_registry_load_session_reuses_validated_cache,
    test_registry_missing_scan_version_is_stale_and_rebuilds_once,
    test_reservation_reads_skip_the_stale_proof_memo,
    test_stale_index_rebuilds_when_owner_disappears,
    test_stale_proof_memo_expires_after_ttl,
    test_stale_proof_memo_invalidated_by_mutation,
    test_stale_proof_memo_reused_across_repeated_loads,
    test_stale_proof_memo_still_detects_deleted_owner_after_ttl,
    test_v3_rebuild_emits_no_legacy_kinds,
)

__test__ = False

__all__ = [
    "test_cached_registry_avoids_repeated_tree_walks",
    "test_display_agent_session_read_never_rebuilds_a_stale_registry",
    "test_display_agent_session_read_rebuilds_when_no_registry_exists",
    "test_legacy_v2_registry_with_agent_family_kinds_upgrades_to_session_v3",
    "test_locked_fallback_keeps_live_identity_pending_claim",
    "test_lowest_name_suggestion",
    "test_missing_index_rebuilds_on_lookup",
    "test_registry_load_session_memoizes_source_signature",
    "test_registry_load_session_reuses_validated_cache",
    "test_registry_missing_scan_version_is_stale_and_rebuilds_once",
    "test_registry_rebuild_agent_session_container_outranks_auto_prefix",
    "test_registry_rebuild_clan_container_outranks_auto_prefix",
    "test_registry_rebuild_collects_active_agent",
    "test_registry_rebuild_collects_agent_session_container",
    "test_registry_rebuild_collects_bundle_only_agent",
    "test_registry_rebuild_collects_clan_container",
    "test_registry_rebuild_collects_dismissed_artifact",
    "test_registry_rebuild_collects_done_agent",
    "test_registry_rebuild_collects_numeric_auto_prefix",
    "test_registry_rebuild_collects_sharded_agent_and_tracks_day_dir",
    "test_registry_rebuild_derives_named_meta_landing_after_scan",
    "test_registry_rebuild_drops_claim_for_removed_dir",
    "test_registry_rebuild_drops_claim_when_dir_names_another_identity",
    "test_registry_rebuild_drops_dead_identity_pending_claim",
    "test_registry_rebuild_keeps_live_identity_pending_claim",
    "test_registry_rebuild_keeps_live_identity_pending_clan_claim",
    "test_registry_rebuild_resolves_one_identity_snapshot_for_all_sources",
    "test_registry_rebuild_stays_under_sase_home",
    "test_registry_signature_detects_dismissed_bundle_changes",
    "test_registry_signature_ignores_live_artifact_output",
    "test_registry_source_scan_caches_unchanged_artifact_walks",
    "test_registry_source_scan_caches_unchanged_shards",
    "test_reservation_reads_skip_the_stale_proof_memo",
    "test_stale_index_rebuilds_when_owner_disappears",
    "test_stale_proof_memo_expires_after_ttl",
    "test_stale_proof_memo_invalidated_by_mutation",
    "test_stale_proof_memo_reused_across_repeated_loads",
    "test_stale_proof_memo_still_detects_deleted_owner_after_ttl",
    "test_v3_rebuild_emits_no_legacy_kinds",
]
