"""Archive restore, fork, and copy tests (phase sase-1jm.5).

Proves the ⏎ chooser's ARCHIVE section (Restore to inbox by default,
Restore and show, Fork, Open chat, Copy), container and marked bulk restore
with skip reasons, restored rows staying in place behind the ⌂ restored
overlay, ``y`` copying the @agent reference on the Agents tab, and the
``%`` copy-palette targets ported from the pane (! handoff, l link,
j json, d artifacts dir).

Split facade: the tests now live in ``test_agent_archive_restore_run``,
``test_agent_archive_restore_chooser``, and
``test_agent_archive_restore_copy``. This module re-exports the public
names so the original import path keeps working. It collects no tests itself.
"""

from __future__ import annotations

from tests.ace.tui.test_agent_archive_restore_chooser import (
    test_chooser_model_defaults_to_restore,
    test_chooser_model_falls_back_to_open_chat,
    test_chooser_model_hides_fork_when_unaccepted,
    test_chooser_model_marks_change_default_label,
    test_fork_acceptance_rules,
    test_fork_prefills_prompt,
    test_open_archive_chat_paths,
    test_open_chooser_pushes_modal_with_initial,
    test_open_chooser_unreadable_warns,
)
from tests.ace.tui.test_agent_archive_restore_copy import (
    test_copy_artifacts_dir_missing_warns,
    test_copy_handoff_prefills_prompt,
    test_copy_json_payload_is_metadata,
    test_copy_link_format_is_followable,
    test_copy_palette_new_targets_dispatch,
    test_footer_offers_restore_without_live_chips,
    test_help_archive_box_lists_action_rows,
    test_y_copies_agent_reference_on_agents_tab,
)
from tests.ace.tui.test_agent_archive_restore_run import (
    test_collect_banner_and_pulse_skipped,
    test_collect_collapsed_container_skipped_with_hint,
    test_collect_container_expands_loaded_members,
    test_collect_marked_wins_over_cursor,
    test_collect_single_row_key,
    test_hydrate_capability_rechecked_before_submit,
    test_hydrate_chip_does_not_block_revivable_bundle,
    test_run_bulk_reports_counts_with_reasons,
    test_run_failed_rows_reported_without_overlay,
    test_run_restore_and_show_filter_hidden_warns,
    test_run_restore_and_show_reload_pending_stays_neutral,
    test_run_restore_and_show_reveals_in_inbox,
    test_run_single_restore_marks_overlay_and_toasts,
)

__test__ = False

__all__ = [
    "test_chooser_model_defaults_to_restore",
    "test_chooser_model_falls_back_to_open_chat",
    "test_chooser_model_hides_fork_when_unaccepted",
    "test_chooser_model_marks_change_default_label",
    "test_collect_banner_and_pulse_skipped",
    "test_collect_collapsed_container_skipped_with_hint",
    "test_collect_container_expands_loaded_members",
    "test_collect_marked_wins_over_cursor",
    "test_collect_single_row_key",
    "test_copy_artifacts_dir_missing_warns",
    "test_copy_handoff_prefills_prompt",
    "test_copy_json_payload_is_metadata",
    "test_copy_link_format_is_followable",
    "test_copy_palette_new_targets_dispatch",
    "test_footer_offers_restore_without_live_chips",
    "test_fork_acceptance_rules",
    "test_fork_prefills_prompt",
    "test_help_archive_box_lists_action_rows",
    "test_hydrate_capability_rechecked_before_submit",
    "test_hydrate_chip_does_not_block_revivable_bundle",
    "test_open_archive_chat_paths",
    "test_open_chooser_pushes_modal_with_initial",
    "test_open_chooser_unreadable_warns",
    "test_run_bulk_reports_counts_with_reasons",
    "test_run_failed_rows_reported_without_overlay",
    "test_run_restore_and_show_filter_hidden_warns",
    "test_run_restore_and_show_reload_pending_stays_neutral",
    "test_run_restore_and_show_reveals_in_inbox",
    "test_run_single_restore_marks_overlay_and_toasts",
    "test_y_copies_agent_reference_on_agents_tab",
]
