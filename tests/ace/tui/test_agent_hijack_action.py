"""Agents-tab ingress for durable Agent Hijack operations.

Split facade: the tests now live in
``test_agent_hijack_action_ingress``,
``test_agent_hijack_action_ledger``, and
``test_agent_hijack_action_pending``. This module re-exports the public
names so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_agent_hijack_action_ingress import (
    test_agent_can_offer_hijack_uses_cheap_row_local_refusals,
    test_claimless_wait_redirect_opens_kill_and_edit_flow,
    test_footer_and_kill_modal_follow_cached_decision,
    test_gate_review_redirect_dispatches_enter_gate_targets,
    test_hijack_submits_occupying_member_name,
    test_open_recovery_redirect_opens_panel,
    test_refused_decision_toasts_code_message_and_next_action,
    test_remote_hijack_ingress_copies_host_command,
    test_remote_hijack_ingress_records_a_local_referral,
    test_select_member_redirect_retargets_lone_live_member,
    test_show_active_hijack_redirect_toasts_decision,
)
from tests.ace.tui.test_agent_hijack_action_ledger import (
    test_active_ledger_records_drive_hijack_overlays_and_summary,
    test_collapsed_session_mirrors_hijack_record,
    test_hijack_submission_shows_pending_and_stop_failed_rows,
    test_latched_ledger_record_projects_pending_overlay_on_member_and_container,
    test_notify_hijack_moot_transitions_toasts_once,
    test_pending_tracker_ignores_cancelled_disappearance,
    test_pending_tracker_notifies_finished_first_once,
    test_remote_referral_overlay_is_projected_from_the_store,
    test_settled_hijack_record_is_loaded_by_done_marker_id,
    test_x_on_hijacked_agent_submits_durable_dismiss,
)
from tests.ace.tui.test_agent_hijack_action_pending import (
    test_delayed_completion_applies_to_current_identity_row,
    test_footer_and_kill_modal_offer_hijack_for_pending_latch,
    test_help_lists_pending_cancel_and_force,
    test_latched_occupying_completion_stays_pending,
    test_moot_completion_toasts_exact_phrase,
    test_pending_cancel_submits_durable_cancel,
    test_pending_force_choice_appears_only_after_120s,
    test_pending_ingress_skips_when_selection_moves,
    test_pending_row_opens_cancel_force_panel,
    test_refused_force_keeps_pending_overlay,
)

__test__ = False

__all__ = [
    "test_active_ledger_records_drive_hijack_overlays_and_summary",
    "test_agent_can_offer_hijack_uses_cheap_row_local_refusals",
    "test_claimless_wait_redirect_opens_kill_and_edit_flow",
    "test_collapsed_session_mirrors_hijack_record",
    "test_delayed_completion_applies_to_current_identity_row",
    "test_footer_and_kill_modal_follow_cached_decision",
    "test_footer_and_kill_modal_offer_hijack_for_pending_latch",
    "test_gate_review_redirect_dispatches_enter_gate_targets",
    "test_help_lists_pending_cancel_and_force",
    "test_hijack_submission_shows_pending_and_stop_failed_rows",
    "test_hijack_submits_occupying_member_name",
    "test_latched_ledger_record_projects_pending_overlay_on_member_and_container",
    "test_latched_occupying_completion_stays_pending",
    "test_moot_completion_toasts_exact_phrase",
    "test_notify_hijack_moot_transitions_toasts_once",
    "test_open_recovery_redirect_opens_panel",
    "test_pending_cancel_submits_durable_cancel",
    "test_pending_force_choice_appears_only_after_120s",
    "test_pending_ingress_skips_when_selection_moves",
    "test_pending_row_opens_cancel_force_panel",
    "test_pending_tracker_ignores_cancelled_disappearance",
    "test_pending_tracker_notifies_finished_first_once",
    "test_refused_decision_toasts_code_message_and_next_action",
    "test_refused_force_keeps_pending_overlay",
    "test_remote_hijack_ingress_copies_host_command",
    "test_remote_hijack_ingress_records_a_local_referral",
    "test_remote_referral_overlay_is_projected_from_the_store",
    "test_select_member_redirect_retargets_lone_live_member",
    "test_settled_hijack_record_is_loaded_by_done_marker_id",
    "test_show_active_hijack_redirect_toasts_decision",
    "test_x_on_hijacked_agent_submits_durable_dismiss",
]
