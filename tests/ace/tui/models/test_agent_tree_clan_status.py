"""Clan-container status mirrors a lone running member's refined label.

Split facade: the tests now live in ``test_agent_tree_clan_status_monitor``,
``test_agent_tree_clan_status_queued``, and
``test_agent_tree_clan_status_finalizing``. This module re-exports the public
names so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.models.test_agent_tree_clan_status_finalizing import (
    test_clan_finalizing_member_plus_failed_has_no_pointer,
    test_clan_finalizing_settles_back_to_running_then_clears,
    test_clan_render_key_invalidates_when_member_finalizer_changes,
    test_clan_retrying_countdown_matches_member,
    test_clan_row_shows_finalizing_for_lone_running_member_declaring,
    test_clan_row_shows_finalizing_for_lone_running_member_executing,
    test_clan_row_shows_finalizing_for_lone_running_session_member,
    test_clan_two_running_members_one_finalizing_stays_running,
)
from tests.ace.tui.models.test_agent_tree_clan_status_monitor import (
    test_clan_all_waiting_members_keep_existing_fallback,
    test_clan_duplicate_member_identity_does_not_create_competing_member,
    test_clan_honors_effective_bucket_override,
    test_clan_lone_failed_label_stays_in_failed_count_and_bucket,
    test_clan_mirrors_lone_failed_monitor_stop_label_and_counts,
    test_clan_mirrors_lone_starting_member,
    test_clan_mirrors_lone_testing_member_status_and_style,
    test_clan_multiple_relevant_members_keep_canonical_aggregate,
    test_clan_queued_and_waiting_companions_do_not_mask_lone_failed_label,
    test_clan_status_preserves_precedence_over_lone_running_member,
    test_clan_status_reprojection_clears_failed_source_after_second_member,
    test_clan_status_reprojection_clears_stale_monitor_fields,
    test_clan_status_reprojection_replaces_failed_label_with_later_running_member,
    test_clan_stays_running_for_lone_plain_running_member,
    test_clan_stays_running_when_two_members_are_running,
)
from tests.ace.tui.models.test_agent_tree_clan_status_queued import (
    test_clan_mirrors_lone_failed_gate_presentation,
    test_clan_mirrors_lone_queued_agent_session_turn_rank,
    test_clan_mirrors_lone_queued_member_admission_rank,
    test_clan_mirrors_lone_running_member_gate_presentation,
    test_clan_mirrors_lone_stopped_member_label,
    test_clan_queued_rank_reprojection_clears_wait_display_source,
    test_clan_two_queued_members_keep_generic_queued_without_rank,
    test_clan_waiting_companions_do_not_block_lone_queued_rank,
)

__test__ = False
