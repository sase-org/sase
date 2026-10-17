"""Tests for the agent MEMORY prompt-panel sub-section renderer.

Split facade: the tests now live in ``test_agent_memory_reads_basic`` and
``test_agent_memory_reads_summary`` (shared helpers in
``_agent_memory_reads_helpers``). This module re-exports the public names so
the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.widgets.test_agent_memory_reads_basic import (
    test_empty_events_appends_nothing,
    test_empty_events_can_render_placeholder,
    test_hint_state_maps_each_visible_event_and_aligns_reason,
    test_long_attributed_reason_wraps_within_limit_and_aligns,
    test_long_reason_is_wrapped_without_truncation,
    test_overflow_line_gets_no_hint,
    test_overflow_renders_truncation_footer,
    test_overlong_token_is_hard_split_within_limit,
    test_pathless_batch_event_displays_original_selectors,
    test_pathless_event_without_selectors_gets_no_hint,
    test_pathless_strand_event_maps_to_deferred_report,
    test_single_event_renders_timestamp_path_and_reason,
)
from tests.ace.tui.widgets.test_agent_memory_reads_summary import (
    test_attributed_reason_aligns_under_primary_text,
    test_attributed_rows_render_role_labels,
    test_batch_header_ignores_included_targets,
    test_batch_plus_overlapping_single_read_counts_distinct_files,
    test_chips_append_at_row_end_without_reflow,
    test_distinct_path_count_in_summary,
    test_explicit_launch_row_header_says_instructions_as_launched,
    test_frontmatter_marker_absent_when_not_stripped,
    test_frontmatter_marker_present_when_stripped,
    test_launch_row_alone_renders_without_reads,
    test_launch_row_renders_first_with_chip,
    test_past_chip_appends_version_and_newer_count,
    test_pathless_batch_header_counts_each_requested_file,
    test_role_column_padded_for_unlabeled_rows_in_attributed_lane,
    test_single_producer_summary_omits_agent_count,
    test_version_pin_registers_hint_number,
)

__test__ = False

__all__ = [
    "test_attributed_reason_aligns_under_primary_text",
    "test_attributed_rows_render_role_labels",
    "test_batch_header_ignores_included_targets",
    "test_batch_plus_overlapping_single_read_counts_distinct_files",
    "test_chips_append_at_row_end_without_reflow",
    "test_distinct_path_count_in_summary",
    "test_empty_events_appends_nothing",
    "test_empty_events_can_render_placeholder",
    "test_explicit_launch_row_header_says_instructions_as_launched",
    "test_frontmatter_marker_absent_when_not_stripped",
    "test_frontmatter_marker_present_when_stripped",
    "test_hint_state_maps_each_visible_event_and_aligns_reason",
    "test_launch_row_alone_renders_without_reads",
    "test_launch_row_renders_first_with_chip",
    "test_long_attributed_reason_wraps_within_limit_and_aligns",
    "test_long_reason_is_wrapped_without_truncation",
    "test_overflow_line_gets_no_hint",
    "test_overflow_renders_truncation_footer",
    "test_overlong_token_is_hard_split_within_limit",
    "test_past_chip_appends_version_and_newer_count",
    "test_pathless_batch_event_displays_original_selectors",
    "test_pathless_batch_header_counts_each_requested_file",
    "test_pathless_event_without_selectors_gets_no_hint",
    "test_pathless_strand_event_maps_to_deferred_report",
    "test_role_column_padded_for_unlabeled_rows_in_attributed_lane",
    "test_single_event_renders_timestamp_path_and_reason",
    "test_single_producer_summary_omits_agent_count",
    "test_version_pin_registers_hint_number",
]
