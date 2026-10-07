"""Facade preserving the historic ``test_continuation_replay_hydration`` import path.

The hydration tests now live in :mod:`test_continuation_replay_hydration_basic`,
:mod:`test_continuation_replay_hydration_policy`, and
:mod:`test_continuation_replay_hydration_retry`; this module re-exports their
public test functions so existing import paths keep working.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from tests.history._continuation_replay_hydration_helpers import (
    ORIGINAL_CONSTRAINT_SENTINEL,
)
from tests.history.test_continuation_replay_hydration_basic import (
    test_alias_reuse_does_not_rediscover_a_newer_agent_session_member,
    test_delayed_starter_settlement_hydrates_from_starter_dir,
    test_direct_child_hydrates_original_constraint_from_production_capture,
    test_hundred_handoff_from_final_monitor_result_grows_linearly,
    test_literal_disabled_regions_survive_hydration,
    test_replay_renders_materialized_segments_and_checkpoint_bodies,
    test_shared_ancestry_hydrates_once_for_manual_multi_parent,
)
from tests.history.test_continuation_replay_hydration_policy import (
    test_cross_run_archived_node_is_not_spliced,
    test_digest_mismatch_is_explicit_missing_source,
    test_failed_starter_without_checkpoint_is_nonlaunchable,
    test_historical_agent_session_monitor_records_prefix_reset,
    test_legacy_mixed_protected_and_raw_none_policy_conflicts,
    test_legacy_none_policy_reports_conflict_for_raw_monitor_logs,
    test_missing_parent_blocks_automatic_launch,
    test_portable_file_ref_resolves_with_digest_check,
    test_unknown_parent_still_refuses_automatic_launch,
)
from tests.history.test_continuation_replay_hydration_retry import (
    test_legacy_retried_attempt_edge_spliced_from_replay,
    test_multi_attempt_chain_spliced_recursively,
    test_retry_then_fork_replay_end_to_end,
    test_superseded_splice_preserves_launch_ancestry,
)

__all__ = [
    "ORIGINAL_CONSTRAINT_SENTINEL",
    "test_alias_reuse_does_not_rediscover_a_newer_agent_session_member",
    "test_cross_run_archived_node_is_not_spliced",
    "test_delayed_starter_settlement_hydrates_from_starter_dir",
    "test_digest_mismatch_is_explicit_missing_source",
    "test_direct_child_hydrates_original_constraint_from_production_capture",
    "test_failed_starter_without_checkpoint_is_nonlaunchable",
    "test_historical_agent_session_monitor_records_prefix_reset",
    "test_hundred_handoff_from_final_monitor_result_grows_linearly",
    "test_legacy_mixed_protected_and_raw_none_policy_conflicts",
    "test_legacy_none_policy_reports_conflict_for_raw_monitor_logs",
    "test_legacy_retried_attempt_edge_spliced_from_replay",
    "test_literal_disabled_regions_survive_hydration",
    "test_missing_parent_blocks_automatic_launch",
    "test_multi_attempt_chain_spliced_recursively",
    "test_portable_file_ref_resolves_with_digest_check",
    "test_replay_renders_materialized_segments_and_checkpoint_bodies",
    "test_retry_then_fork_replay_end_to_end",
    "test_shared_ancestry_hydrates_once_for_manual_multi_parent",
    "test_superseded_splice_preserves_launch_ancestry",
    "test_unknown_parent_still_refuses_automatic_launch",
]
