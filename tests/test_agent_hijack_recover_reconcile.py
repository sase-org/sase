"""Compatibility facade for keep-work recovery reconcile tests.

The concrete tests live in focused modules. Keep their original import path
available without collecting the re-exported tests a second time.
"""

from __future__ import annotations

from tests.test_agent_hijack_recover_reconcile_resolver import (
    test_absent_with_launch_evidence_retains,
    test_absent_without_launch_evidence_returns_to_held,
    test_live_resolver_keeps_resolving,
    test_malformed_record_retains_without_crash,
    test_matching_queued_request_stays_authoritative,
    test_mismatched_queued_retains,
    test_name_only_successor_retains,
    test_reused_resolver_pid_is_dead,
    test_second_cleanup_does_not_duplicate,
    test_too_young_dead_resolver_waits,
)
from tests.test_agent_hijack_recover_reconcile_settlement import (
    test_settlement_cleanup_never_releases_resolving,
    test_settlement_crash_after_ack_adopts,
    test_settlement_crash_after_child_creation_retains,
    test_settlement_crash_before_admission_returns_to_held,
    test_settlement_crash_while_queued_keeps_resolving,
    test_settlement_double_cleanup_does_not_double_settle,
    test_settlement_malformed_metadata_keeps_custody,
    test_settlement_not_dispatched_returns_to_held,
    test_settlement_pending_drains_without_resolving,
    test_settlement_recover_resolved_repairs,
    test_settlement_resolving_claim_matches_successor_pid,
    test_settlement_resume_queued_returns_queued,
    test_settlement_return_to_held_cas_lost_reports_retain,
    test_settlement_stale_cleanup_reconciles_every_resolving,
    test_settlement_uncertain_journal_stays_uncertain,
)
from tests.test_agent_hijack_recover_reconcile_waits import (
    test_chained_recovery_follows_two_hops,
    test_expired_hijack_stays_parked,
    test_missing_successor_stays_waiting,
    test_name_wait_follows_failure,
    test_name_wait_follows_resolved_successor,
    test_pending_hijack_stays_parked,
    test_session_wait_follows_successor_in_same_session,
    test_settlement_expired_neither_resolved_nor_failed,
    test_settlement_newest_artifact_wins_name_collision,
)

__all__ = (
    "test_absent_with_launch_evidence_retains",
    "test_absent_without_launch_evidence_returns_to_held",
    "test_chained_recovery_follows_two_hops",
    "test_expired_hijack_stays_parked",
    "test_live_resolver_keeps_resolving",
    "test_malformed_record_retains_without_crash",
    "test_matching_queued_request_stays_authoritative",
    "test_mismatched_queued_retains",
    "test_missing_successor_stays_waiting",
    "test_name_only_successor_retains",
    "test_name_wait_follows_failure",
    "test_name_wait_follows_resolved_successor",
    "test_pending_hijack_stays_parked",
    "test_reused_resolver_pid_is_dead",
    "test_second_cleanup_does_not_duplicate",
    "test_session_wait_follows_successor_in_same_session",
    "test_settlement_cleanup_never_releases_resolving",
    "test_settlement_crash_after_ack_adopts",
    "test_settlement_crash_after_child_creation_retains",
    "test_settlement_crash_before_admission_returns_to_held",
    "test_settlement_crash_while_queued_keeps_resolving",
    "test_settlement_double_cleanup_does_not_double_settle",
    "test_settlement_expired_neither_resolved_nor_failed",
    "test_settlement_malformed_metadata_keeps_custody",
    "test_settlement_newest_artifact_wins_name_collision",
    "test_settlement_not_dispatched_returns_to_held",
    "test_settlement_pending_drains_without_resolving",
    "test_settlement_recover_resolved_repairs",
    "test_settlement_resolving_claim_matches_successor_pid",
    "test_settlement_resume_queued_returns_queued",
    "test_settlement_return_to_held_cas_lost_reports_retain",
    "test_settlement_stale_cleanup_reconciles_every_resolving",
    "test_settlement_uncertain_journal_stays_uncertain",
    "test_too_young_dead_resolver_waits",
)

__test__ = False
