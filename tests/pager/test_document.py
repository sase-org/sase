"""Facade preserving the historic ``tests.pager.test_document`` import path.

The document tests now live in :mod:`test_document_body`,
:mod:`test_document_adapters`, and :mod:`test_document_sections`;
this module re-exports their public test functions so existing import paths
keep working.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from .test_document_adapters import (
    test_bead_show_batch_adapter_matches_single_bead_rendering,
    test_bead_show_batch_adapter_uses_one_section_per_bead,
    test_bead_show_freezes_kinds_for_note_refs_when_issue_has_no_refs,
    test_bead_show_section_anchors_to_entry_primary_workspace,
    test_equal_visible_labels_keep_distinct_action_destinations,
    test_path_list_adapter_builds_one_file_section_per_path,
    test_path_list_adapter_collapses_a_workspace_checkout_into_the_ws_token,
    test_path_list_adapter_freezes_context_known_kinds,
)
from .test_document_body import (
    test_ansi_body_round_trips_plain_text_and_styles,
    test_attached_target_span_must_fit_body,
    test_attached_target_suppresses_overlapping_scanned_span,
    test_raw_source_defaults_to_none_and_does_not_affect_rendering,
    test_section_syntax_language_is_none_when_ineligible,
    test_section_syntax_language_is_none_without_a_language_hint,
    test_section_syntax_language_returns_the_spec_language_when_eligible,
    test_string_body_does_not_double_trailing_newline_when_from_ansi_keeps_it,
    test_string_body_keeps_a_single_trailing_newline,
    test_string_body_preserves_double_trailing_newline,
)
from .test_document_sections import (
    test_local_anchor_fragment_classifies_targets,
    test_local_anchor_fragment_rejects_attached_targets,
    test_pager_section_bead_id_prefixes_normalize,
    test_section_content_digest_matches_and_memoizes,
    test_section_line_prefix_bounds_distinct_widths,
    test_section_line_prefix_matches_per_line_estimates,
    test_section_local_anchor_lines_line_range_and_memoization,
    test_section_target_spans_are_memoized_per_section_and_origin,
    test_section_target_spans_honors_bead_id_prefixes,
    test_section_with_bead_id_prefixes_returns_copy_with_fresh_spans,
    test_section_with_bead_id_prefixes_returns_same_object_for_equal,
)

__all__ = [
    "test_ansi_body_round_trips_plain_text_and_styles",
    "test_attached_target_span_must_fit_body",
    "test_attached_target_suppresses_overlapping_scanned_span",
    "test_bead_show_batch_adapter_matches_single_bead_rendering",
    "test_bead_show_batch_adapter_uses_one_section_per_bead",
    "test_bead_show_freezes_kinds_for_note_refs_when_issue_has_no_refs",
    "test_bead_show_section_anchors_to_entry_primary_workspace",
    "test_equal_visible_labels_keep_distinct_action_destinations",
    "test_local_anchor_fragment_classifies_targets",
    "test_local_anchor_fragment_rejects_attached_targets",
    "test_pager_section_bead_id_prefixes_normalize",
    "test_path_list_adapter_builds_one_file_section_per_path",
    "test_path_list_adapter_collapses_a_workspace_checkout_into_the_ws_token",
    "test_path_list_adapter_freezes_context_known_kinds",
    "test_raw_source_defaults_to_none_and_does_not_affect_rendering",
    "test_section_content_digest_matches_and_memoizes",
    "test_section_line_prefix_bounds_distinct_widths",
    "test_section_line_prefix_matches_per_line_estimates",
    "test_section_local_anchor_lines_line_range_and_memoization",
    "test_section_syntax_language_is_none_when_ineligible",
    "test_section_syntax_language_is_none_without_a_language_hint",
    "test_section_syntax_language_returns_the_spec_language_when_eligible",
    "test_section_target_spans_are_memoized_per_section_and_origin",
    "test_section_target_spans_honors_bead_id_prefixes",
    "test_section_with_bead_id_prefixes_returns_copy_with_fresh_spans",
    "test_section_with_bead_id_prefixes_returns_same_object_for_equal",
    "test_string_body_does_not_double_trailing_newline_when_from_ansi_keeps_it",
    "test_string_body_keeps_a_single_trailing_newline",
    "test_string_body_preserves_double_trailing_newline",
]
