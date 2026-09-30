"""Rows and detail rendering for the Artifacts Beads pane.

Facade preserving the original import path. The suites moved into the
sibling ``_artifacts_beads_rendering_*`` modules so every file stays at or
under 500 lines; this module re-exports each public test and fixture name.
Only public names cross the module boundary here.
"""

from __future__ import annotations

from tests.ace.tui._artifacts_beads_helpers import pinned_clock
from tests.ace.tui._artifacts_beads_rendering_detail import (
    test_detail_and_preview_share_the_full_creation_label,
    test_detail_drops_empty_property_rows_for_a_sparse_task,
    test_detail_keeps_populated_property_rows,
    test_detail_keeps_unrecorded_resolution_on_a_closed_bead,
    test_detail_uses_shared_metadata_and_triage_callout,
    test_external_issue_links_render_in_rows_detail_and_preview,
    test_first_run_empty_detail_points_to_create_and_triage,
    test_flag_detail_omits_due_state_when_unresolved,
)
from tests.ace.tui._artifacts_beads_rendering_evidence import (
    test_detail_body_renders_structured_notes_as_markdown_entries,
    test_detail_note_attachments_render_chips_and_descriptor_strip,
    test_detail_note_without_attachments_renders_verbatim,
    test_task_rows_and_detail_render_plus_one_badges_and_evidence,
    test_task_rows_and_detail_render_post_close_plus_one_badges,
    test_task_rows_and_detail_render_reopen_badges_and_close_history,
)
from tests.ace.tui._artifacts_beads_rendering_flags import (
    test_flag_group_rows_status_and_detail_render_due_metadata,
    test_flag_task_rows_keep_countdown_and_gain_task_type_chip,
)
from tests.ace.tui._artifacts_beads_rendering_rows import (
    test_rows_label_created_and_updated_ages_separately,
    test_rows_show_triage_plan_status_and_project_chips,
    test_rows_suppress_the_updated_cell_for_a_never_updated_bead,
    test_tasks_precede_epics_and_every_bead_has_one_row,
)

__all__ = [
    "pinned_clock",
    "test_detail_and_preview_share_the_full_creation_label",
    "test_detail_body_renders_structured_notes_as_markdown_entries",
    "test_detail_drops_empty_property_rows_for_a_sparse_task",
    "test_detail_keeps_populated_property_rows",
    "test_detail_keeps_unrecorded_resolution_on_a_closed_bead",
    "test_detail_note_attachments_render_chips_and_descriptor_strip",
    "test_detail_note_without_attachments_renders_verbatim",
    "test_detail_uses_shared_metadata_and_triage_callout",
    "test_external_issue_links_render_in_rows_detail_and_preview",
    "test_first_run_empty_detail_points_to_create_and_triage",
    "test_flag_detail_omits_due_state_when_unresolved",
    "test_flag_group_rows_status_and_detail_render_due_metadata",
    "test_flag_task_rows_keep_countdown_and_gain_task_type_chip",
    "test_rows_label_created_and_updated_ages_separately",
    "test_rows_show_triage_plan_status_and_project_chips",
    "test_rows_suppress_the_updated_cell_for_a_never_updated_bead",
    "test_tasks_precede_epics_and_every_bead_has_one_row",
    "test_task_rows_and_detail_render_plus_one_badges_and_evidence",
    "test_task_rows_and_detail_render_post_close_plus_one_badges",
    "test_task_rows_and_detail_render_reopen_badges_and_close_history",
]
