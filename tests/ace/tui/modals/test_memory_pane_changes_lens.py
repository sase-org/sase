"""Tests for the Changes lens (phase `changes-lens`).

Facade preserving the historic
``tests.ace.tui.modals.test_memory_pane_changes_lens`` import path. The
suites now live in the sibling ``test_memory_pane_changes_lens_*``
modules (shared fixtures in ``_memory_pane_changes_lens_helpers``); this
module re-exports every public test so existing import paths keep working.
Only public names cross the module boundary here.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from tests.ace.tui.modals.test_memory_pane_changes_lens_interactions import (
    test_changes_key_is_inert_in_timeline,
    test_changes_lens_opens_and_esc_restores_notes,
    test_pager_handoff_uses_diff_view_at_changeset_version,
    test_preview_fire_drops_superseded_motion,
    test_stale_feed_load_is_dropped,
    test_changes_filter_routes_to_lens_rows,
    test_timeline_key_is_inert_in_changes,
    test_window_extends_at_more_row,
)
from tests.ace.tui.modals.test_memory_pane_changes_lens_review import (
    test_changes_lens_shows_review_chip_and_dots,
    test_lens_footer_names_mark_reviewed,
    test_lens_header_detail_leads_with_review_chip,
    test_mark_key_is_inert_outside_changes,
    test_mark_reviewed_clears_dots_and_toasts,
    test_mark_reviewed_failure_restores_dots,
    test_mark_reviewed_marks_each_scope_in_all_scopes,
    test_opening_changes_lens_marks_nothing,
)
from tests.ace.tui.modals.test_memory_pane_changes_lens_rows import (
    test_all_scopes_merge_and_tag_home,
    test_changes_row_ids_are_stable,
    test_day_headers_are_not_selectable,
    test_day_labels_name_today_and_yesterday,
    test_failed_scope_shows_as_chip,
    test_filter_matches_whole_feed,
    test_header_detail_names_window_and_regen,
    test_lens_footer_names_configured_keys,
    test_lens_rows_group_days_with_changesets,
    test_lens_rows_survive_missing_feed,
    test_provenance_uses_artifact_icons,
    test_section_titles_number_subjects,
    test_totals_count_subjects_and_regenerated,
    test_window_bounds_newest_and_appends_more_row,
)

__all__ = [
    "test_all_scopes_merge_and_tag_home",
    "test_changes_key_is_inert_in_timeline",
    "test_changes_lens_opens_and_esc_restores_notes",
    "test_changes_lens_shows_review_chip_and_dots",
    "test_changes_row_ids_are_stable",
    "test_day_headers_are_not_selectable",
    "test_day_labels_name_today_and_yesterday",
    "test_failed_scope_shows_as_chip",
    "test_filter_matches_whole_feed",
    "test_header_detail_names_window_and_regen",
    "test_lens_footer_names_configured_keys",
    "test_lens_footer_names_mark_reviewed",
    "test_lens_header_detail_leads_with_review_chip",
    "test_lens_rows_group_days_with_changesets",
    "test_lens_rows_survive_missing_feed",
    "test_mark_key_is_inert_outside_changes",
    "test_mark_reviewed_clears_dots_and_toasts",
    "test_mark_reviewed_failure_restores_dots",
    "test_mark_reviewed_marks_each_scope_in_all_scopes",
    "test_opening_changes_lens_marks_nothing",
    "test_pager_handoff_uses_diff_view_at_changeset_version",
    "test_preview_fire_drops_superseded_motion",
    "test_provenance_uses_artifact_icons",
    "test_section_titles_number_subjects",
    "test_stale_feed_load_is_dropped",
    "test_changes_filter_routes_to_lens_rows",
    "test_timeline_key_is_inert_in_changes",
    "test_totals_count_subjects_and_regenerated",
    "test_window_bounds_newest_and_appends_more_row",
    "test_window_extends_at_more_row",
]
