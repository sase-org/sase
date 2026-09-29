"""Tests for typed ``#fork`` history assembly.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_fork_history_agents import (
    test_line_initial_enabled_false_marker_in_history_is_escaped,
    test_line_initial_enabled_true_marker_in_history_is_escaped,
    test_successful_multi_agent_history_is_unchanged,
)
from tests.test_fork_history_clan import (
    test_clan_block_contains_prompts_and_stats_but_no_reply_text,
    test_mixed_agent_and_clan_sources_keep_agent_reply_only,
)
from tests.test_fork_history_failed import (
    test_failed_source_missing_error_or_traceback_degrades,
    test_failed_source_without_transcript_quotes_launch_prompt,
    test_failed_traceback_renders_tail_and_truncation_marker,
    test_multi_agent_failed_parent_marks_only_that_section,
    test_single_failed_agent_source_marks_failure_and_keeps_transcript,
)
from tests.test_fork_history_proc import (
    test_failed_standalone_proc_source_marks_failed_status,
    test_multi_source_guidance_flags_proc_content_and_failure,
    test_proc_source_output_truncation_note_and_missing_output,
    test_running_proc_source_is_not_marked_done_or_failed,
    test_single_proc_source_renders_execution_record_not_conversation,
)
from tests.test_fork_history_session import (
    test_agent_session_block_renders_full_ordered_transcripts_without_ancestor_duplication,
    test_agent_session_mixed_with_agent_and_clan_uses_correct_source_guidance,
    test_agent_session_with_monitor_member_renders_named_proc_heading,
    test_legacy_family_kind_fork_source_renders_as_agent_session,
)

__test__ = False

__all__ = [
    "test_agent_session_block_renders_full_ordered_transcripts_without_ancestor_duplication",
    "test_agent_session_mixed_with_agent_and_clan_uses_correct_source_guidance",
    "test_agent_session_with_monitor_member_renders_named_proc_heading",
    "test_clan_block_contains_prompts_and_stats_but_no_reply_text",
    "test_failed_source_missing_error_or_traceback_degrades",
    "test_failed_source_without_transcript_quotes_launch_prompt",
    "test_failed_standalone_proc_source_marks_failed_status",
    "test_failed_traceback_renders_tail_and_truncation_marker",
    "test_legacy_family_kind_fork_source_renders_as_agent_session",
    "test_line_initial_enabled_false_marker_in_history_is_escaped",
    "test_line_initial_enabled_true_marker_in_history_is_escaped",
    "test_mixed_agent_and_clan_sources_keep_agent_reply_only",
    "test_multi_agent_failed_parent_marks_only_that_section",
    "test_multi_source_guidance_flags_proc_content_and_failure",
    "test_proc_source_output_truncation_note_and_missing_output",
    "test_running_proc_source_is_not_marked_done_or_failed",
    "test_single_failed_agent_source_marks_failure_and_keeps_transcript",
    "test_single_proc_source_renders_execution_record_not_conversation",
    "test_successful_multi_agent_history_is_unchanged",
]
