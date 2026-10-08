"""Unit coverage for ACE Plan Decisions (sase-1hi.6).

Split facade: the tests now live in ``test_plan_decision_ace_draft``,
``test_plan_decision_ace_document``, ``test_plan_decision_ace_modal``,
``test_plan_decision_ace_verdict``, ``test_plan_decision_ace_stale``, and
``test_plan_decision_ace_render``. This module re-exports the public names so
the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_plan_decision_ace_draft import (
    test_draft_preserves_author_order_and_effective_defaults,
    test_step_wraps_choices_and_sets_toggles,
    test_flip_and_reset,
    test_decision_map_keys,
    test_sheet_counts_and_revision,
    test_collapsed_and_expanded_row_text,
    test_unverified_copy_and_human_override,
    test_new_chip_for_missing_memory_note,
    test_feedback_carry_lines_only_changed,
)
from tests.ace.tui.test_plan_decision_ace_document import (
    test_fold_maps_many_yaml_lines_to_one,
    test_scroll_prefers_callout_then_id_and_uses_fold,
    test_classify_callout_chosen_and_dimmed,
    test_classify_no_branch_callout,
    test_tint_dims_unselected_without_dropping_lines,
    test_inbox_suffix_counts_and_memory,
    test_decision_option_inputs_same_map_and_reject_omits,
    test_receipt_has_no_gate_card_and_is_silent,
    test_custom_gate_decision_handlers_noop,
)
from tests.ace.tui.test_plan_decision_ace_modal import (
    test_modal_decisions_focus_step_reset_and_enter,
    test_esc_store_freeze_and_settled,
    test_toast_second_line_and_plan_document_sheet,
    test_modal_result_carries_displayed_revision_and_decisions,
    test_gate_card_decisions_block_pending_and_answered,
    test_gate_card_pending_toggles_use_checkboxes,
)
from tests.ace.tui.test_plan_decision_ace_verdict import (
    test_compact_verdict_three_lines_with_without_and_epic,
    test_plan_short_labels_and_generic_unchanged,
    test_scroll_uses_cached_fold_map,
    test_freeze_banner_visible_and_submit_blocked,
    test_feedback_bar_shows_carries_readonly,
    test_settled_labels_truthful,
)
from tests.ace.tui.test_plan_decision_ace_stale import (
    test_stale_review_reloads_revision_keeping_values,
    test_plan_section_render_path_no_stat_no_validate,
)
from tests.ace.tui.test_plan_decision_ace_render import (
    test_compact_verdict_stays_inside_rail_with_stylesheet,
    test_first_frame_tint_keeps_syntax,
    test_draft_edit_avoids_revalidate_relex,
    test_settled_polling_reads_only_open_modal,
)

__test__ = False

__all__ = [
    "test_classify_callout_chosen_and_dimmed",
    "test_classify_no_branch_callout",
    "test_collapsed_and_expanded_row_text",
    "test_compact_verdict_stays_inside_rail_with_stylesheet",
    "test_compact_verdict_three_lines_with_without_and_epic",
    "test_custom_gate_decision_handlers_noop",
    "test_decision_map_keys",
    "test_decision_option_inputs_same_map_and_reject_omits",
    "test_draft_edit_avoids_revalidate_relex",
    "test_draft_preserves_author_order_and_effective_defaults",
    "test_esc_store_freeze_and_settled",
    "test_feedback_bar_shows_carries_readonly",
    "test_feedback_carry_lines_only_changed",
    "test_first_frame_tint_keeps_syntax",
    "test_flip_and_reset",
    "test_fold_maps_many_yaml_lines_to_one",
    "test_freeze_banner_visible_and_submit_blocked",
    "test_gate_card_decisions_block_pending_and_answered",
    "test_gate_card_pending_toggles_use_checkboxes",
    "test_inbox_suffix_counts_and_memory",
    "test_modal_decisions_focus_step_reset_and_enter",
    "test_modal_result_carries_displayed_revision_and_decisions",
    "test_new_chip_for_missing_memory_note",
    "test_plan_section_render_path_no_stat_no_validate",
    "test_plan_short_labels_and_generic_unchanged",
    "test_receipt_has_no_gate_card_and_is_silent",
    "test_scroll_prefers_callout_then_id_and_uses_fold",
    "test_scroll_uses_cached_fold_map",
    "test_settled_labels_truthful",
    "test_settled_polling_reads_only_open_modal",
    "test_sheet_counts_and_revision",
    "test_stale_review_reloads_revision_keeping_values",
    "test_step_wraps_choices_and_sets_toggles",
    "test_tint_dims_unselected_without_dropping_lines",
    "test_toast_second_line_and_plan_document_sheet",
    "test_unverified_copy_and_human_override",
]
