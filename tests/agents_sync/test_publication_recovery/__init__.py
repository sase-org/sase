"""Push-rejection recovery tests.

Split from a single module into focused modules; this package preserves the
original ``tests.agents_sync.test_publication_recovery`` import path and
re-exports every public test for backward compatibility.
"""

from __future__ import annotations

from tests.agents_sync.test_publication_recovery._helpers import (
    BLOCKED_REL,
    CLEAN_REL,
    SECOND_BLOCKED_REL,
    TOKEN,
    commit,
    gh013_stderr,
    git,
    isolate_protection,
    recover,
    scope_for,
    setup_repo,
    tip,
    upstream_tip,
)
from tests.agents_sync.test_publication_recovery.test_classification import (
    test_classifier_failure_degrades_to_unknown,
    test_empty_push_output_is_an_unattributed_unknown,
    test_push_cannot_contain_secrets_is_a_secret_rejection,
    test_sanitized_rule_error_confirms_no_secret,
    test_sanitized_secret_error_names_paths_but_never_the_token,
    test_secret_scan_precedes_fetch_first_hints,
)
from tests.agents_sync.test_publication_recovery.test_push_paths import (
    test_commit_drain_recovers_from_gh013_and_rebuilds_clean,
    test_full_sync_recovers_from_gh013_and_publishes_clean,
    test_migration_push_detail_sanitizes_secret_rejections,
    test_pre_stage_verification_passes_unblocked_candidates,
    test_pre_stage_verification_withholds_rejection_blocked_candidates,
    test_prompt_publish_gh013_resets_and_sanitizes,
    test_snapshot_regeneration_publishes_unblocked_bytes,
    test_snapshot_regeneration_withholds_rejection_blocked_bytes,
)
from tests.agents_sync.test_publication_recovery.test_recovery import (
    test_concurrent_upstream_movement_survives_recovery,
    test_fetch_failure_leaves_the_batch_but_still_blocks,
    test_interrupted_recovery_resumes_idempotently,
    test_multiple_offending_units_are_all_blocked,
    test_no_location_rejection_resets_without_blaming_a_clean_row,
    test_older_commit_bytes_and_early_objects_are_reconciled,
    test_repository_rule_is_sanitized_without_reset_or_blocks,
    test_reset_refuses_a_foreign_checkout,
    test_secret_rejection_blocks_paths_and_resets_to_upstream_tip,
    test_unknown_failure_stops_without_reset_or_blocks,
)

__all__ = [
    "BLOCKED_REL",
    "CLEAN_REL",
    "SECOND_BLOCKED_REL",
    "TOKEN",
    "commit",
    "gh013_stderr",
    "git",
    "isolate_protection",
    "recover",
    "scope_for",
    "setup_repo",
    "test_classifier_failure_degrades_to_unknown",
    "test_commit_drain_recovers_from_gh013_and_rebuilds_clean",
    "test_concurrent_upstream_movement_survives_recovery",
    "test_empty_push_output_is_an_unattributed_unknown",
    "test_fetch_failure_leaves_the_batch_but_still_blocks",
    "test_full_sync_recovers_from_gh013_and_publishes_clean",
    "test_interrupted_recovery_resumes_idempotently",
    "test_migration_push_detail_sanitizes_secret_rejections",
    "test_multiple_offending_units_are_all_blocked",
    "test_no_location_rejection_resets_without_blaming_a_clean_row",
    "test_older_commit_bytes_and_early_objects_are_reconciled",
    "test_pre_stage_verification_passes_unblocked_candidates",
    "test_pre_stage_verification_withholds_rejection_blocked_candidates",
    "test_prompt_publish_gh013_resets_and_sanitizes",
    "test_push_cannot_contain_secrets_is_a_secret_rejection",
    "test_repository_rule_is_sanitized_without_reset_or_blocks",
    "test_reset_refuses_a_foreign_checkout",
    "test_sanitized_rule_error_confirms_no_secret",
    "test_sanitized_secret_error_names_paths_but_never_the_token",
    "test_secret_rejection_blocks_paths_and_resets_to_upstream_tip",
    "test_secret_scan_precedes_fetch_first_hints",
    "test_snapshot_regeneration_publishes_unblocked_bytes",
    "test_snapshot_regeneration_withholds_rejection_blocked_bytes",
    "test_unknown_failure_stops_without_reset_or_blocks",
    "tip",
    "upstream_tip",
]
