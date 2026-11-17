"""Public collection and import facade for agent hijack latch tests."""

from tests._agent_hijack_latch_support import shared_latch_store as latch_store
from tests._test_agent_hijack_latch_application import (
    test_application_holds_claim_and_retries_snapshot_failure,
    test_cancel_race_winner_is_reported_without_releasing_application_custody,
    test_latched_settlement_rewrites_only_the_matching_artifact_generation,
)
from tests._test_agent_hijack_latch_force import (
    test_force_refuses_before_timeout_without_signalling,
    test_eligible_force_reuses_latch_id_and_persists_interruption_custody,
    test_force_preserves_custody_when_transition_commit_result_is_uncertain,
    test_force_rejects_a_stale_selected_id_and_cancelled_latch,
    test_adopted_successor_moots_latch_after_claim_transfer,
    test_stale_reconciliation_applies_dead_owner_once_and_finishes_evidence,
)
from tests._test_agent_hijack_latch_request import (
    test_monitor_latch_request_uses_monitor_scope,
    test_pending_followup_monitor_latch_applies_at_request,
    test_delivered_monitor_latch_is_refused,
    test_gate_latch_is_still_refused,
    test_request_deduplicates_by_target_and_rejects_recycled_occupant,
    test_second_resolution_change_releases_unwritten_reservation,
    test_cancel_and_moot_release_only_their_own_target_reservation,
)
