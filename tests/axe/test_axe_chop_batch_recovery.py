"""Compatibility facade for chop batch recovery tests.

The concrete tests live in focused modules. Keep their original import path
available without collecting the re-exported tests a second time.
"""

from __future__ import annotations

from tests.axe._test_axe_chop_batch_recovery_shared import (
    recovery_isolated_home as isolated_home,
)
from tests.axe.test_axe_chop_batch_recovery_cancel import (
    test_cancel_matches_a_secondary_clan_in_the_batch,
    test_cancel_never_fires_for_individual_member_selection,
    test_cancel_scoped_to_requested_clan_generation,
    test_cancel_targets_only_matching_clan_generation,
    test_cancelled_dead_executor_no_spawn_settles,
    test_cancelled_dead_executor_proven_spawn_acknowledges,
    test_older_generation_does_not_cancel_a_batch_without_recorded_generation,
    test_pending_batch_for_run_skips_complete_batches,
    test_pending_batch_for_run_waits_for_cancelled_inflight_dispatch,
    test_rust_generation_match_binding_rejects_older_unrecorded_generation,
    test_rust_generation_match_binding_scopes_to_clan,
    test_stop_signal_is_thread_safe_pause_fn,
    test_typed_bundle_cancel_failure_is_logged_and_surfaced,
)
from tests.axe.test_axe_chop_batch_recovery_notices import (
    test_deterministic_recovery_launch_failure_is_bounded,
    test_disabled_batch_hold_is_notified_once,
    test_dry_run_is_readonly,
    test_interruption_and_resume_notices_have_separate_episode_keys,
    test_notice_delivery_retry_reuses_one_notification_row,
    test_once_per_claim_release_follows_batch_member_journal,
    test_typed_once_per_claim_release_uses_outer_journal,
)
from tests.axe.test_axe_chop_batch_recovery_observations import (
    test_collect_observations_ignores_prefix_cl_name_without_linkage,
    test_collect_observations_ignores_records_from_other_runs,
    test_collect_observations_marks_unlinked_live_owner_as_foreign_conflict,
    test_collect_observations_matches_by_proposal_id_without_index,
    test_collect_observations_matches_by_run_linkage_not_cl_name,
    test_collect_observations_tells_live_reserver_from_dead_reservation,
    test_replay_rebuilds_first_run_launch_context_and_merges_history,
    test_strict_observations_corrupt_linkage_holds_and_recovers,
    test_strict_observations_hold_on_unreadable_linkage,
)

__all__ = [
    "isolated_home",
    "test_cancel_matches_a_secondary_clan_in_the_batch",
    "test_cancel_never_fires_for_individual_member_selection",
    "test_cancel_scoped_to_requested_clan_generation",
    "test_cancel_targets_only_matching_clan_generation",
    "test_cancelled_dead_executor_no_spawn_settles",
    "test_cancelled_dead_executor_proven_spawn_acknowledges",
    "test_collect_observations_ignores_prefix_cl_name_without_linkage",
    "test_collect_observations_ignores_records_from_other_runs",
    "test_collect_observations_marks_unlinked_live_owner_as_foreign_conflict",
    "test_collect_observations_matches_by_proposal_id_without_index",
    "test_collect_observations_matches_by_run_linkage_not_cl_name",
    "test_collect_observations_tells_live_reserver_from_dead_reservation",
    "test_deterministic_recovery_launch_failure_is_bounded",
    "test_disabled_batch_hold_is_notified_once",
    "test_dry_run_is_readonly",
    "test_interruption_and_resume_notices_have_separate_episode_keys",
    "test_notice_delivery_retry_reuses_one_notification_row",
    "test_older_generation_does_not_cancel_a_batch_without_recorded_generation",
    "test_once_per_claim_release_follows_batch_member_journal",
    "test_pending_batch_for_run_skips_complete_batches",
    "test_pending_batch_for_run_waits_for_cancelled_inflight_dispatch",
    "test_replay_rebuilds_first_run_launch_context_and_merges_history",
    "test_rust_generation_match_binding_rejects_older_unrecorded_generation",
    "test_rust_generation_match_binding_scopes_to_clan",
    "test_stop_signal_is_thread_safe_pause_fn",
    "test_strict_observations_corrupt_linkage_holds_and_recovers",
    "test_strict_observations_hold_on_unreadable_linkage",
    "test_typed_bundle_cancel_failure_is_logged_and_surfaced",
    "test_typed_once_per_claim_release_uses_outer_journal",
]

__test__ = False
