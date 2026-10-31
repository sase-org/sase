"""Tests for agent-session chat resolution.

Split into focused modules; this facade preserves the original import path.
"""

from __future__ import annotations

from tests.test_agent_chat_from_name_agent_session_resolution import (
    test_agent_session_name_and_explicit_children_use_member_owned_transcripts,
    test_explicit_target_is_honored_without_a_bound_launch_record,
    test_agent_session_source_reads_dismissed_member_transcript_from_bundle,
    test_agent_session_source_includes_completed_members_in_chain_order,
    test_dotted_numeric_agent_session_root_resolves_as_agent_session_not_legacy_child,
    test_agent_session_and_explicit_member_duplicate_transcript_are_coalesced,
    test_agent_then_overlapping_agent_session_keeps_unique_later_member,
    test_legacy_rootless_agent_session_source_includes_all_completed_members,
)
from tests.test_agent_chat_from_name_agent_session_forks import (
    test_bound_session_fork_history_selects_the_recorded_root_generation,
    test_bound_turn_fork_history_omits_members_after_pinned_turn,
    test_legacy_bound_bare_agent_record_heals_to_promoted_session,
    test_bound_exact_member_fork_history_uses_the_recorded_artifact,
)
from tests.test_agent_chat_from_name_agent_session_members import (
    test_agent_session_source_includes_intermediate_handoff_without_done_marker,
    test_agent_session_source_reports_running_tip_as_excluded,
    test_agent_session_source_omits_current_member_from_own_agent_session_history,
    test_agent_session_source_includes_failed_member_excludes_unavailable_transcripts,
    test_agent_session_source_requires_at_least_one_completed_transcript,
)

__test__ = False

__all__ = [
    "test_agent_session_and_explicit_member_duplicate_transcript_are_coalesced",
    "test_agent_session_name_and_explicit_children_use_member_owned_transcripts",
    "test_agent_session_source_includes_completed_members_in_chain_order",
    "test_agent_session_source_includes_failed_member_excludes_unavailable_transcripts",
    "test_agent_session_source_includes_intermediate_handoff_without_done_marker",
    "test_agent_session_source_omits_current_member_from_own_agent_session_history",
    "test_agent_session_source_reads_dismissed_member_transcript_from_bundle",
    "test_agent_session_source_reports_running_tip_as_excluded",
    "test_agent_session_source_requires_at_least_one_completed_transcript",
    "test_agent_then_overlapping_agent_session_keeps_unique_later_member",
    "test_bound_exact_member_fork_history_uses_the_recorded_artifact",
    "test_bound_session_fork_history_selects_the_recorded_root_generation",
    "test_bound_turn_fork_history_omits_members_after_pinned_turn",
    "test_dotted_numeric_agent_session_root_resolves_as_agent_session_not_legacy_child",
    "test_explicit_target_is_honored_without_a_bound_launch_record",
    "test_legacy_bound_bare_agent_record_heals_to_promoted_session",
    "test_legacy_rootless_agent_session_source_includes_all_completed_members",
]
