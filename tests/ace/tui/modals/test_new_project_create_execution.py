"""Public import facade for new-project create execution tests.

The suites now live in the sibling ``test_new_project_create_execution_*``
modules (shared helpers in ``_new_project_create_execution_helpers``); this
module re-exports every public test so existing import paths keep working.
Only public names cross the module boundary here.
"""

from __future__ import annotations

# Tests live in the split modules below; keep this facade out of pytest
# collection so each test runs once while the import path keeps working.
__test__ = False

from tests.ace.tui.modals.test_new_project_create_execution_apply import (
    test_add_complete_does_not_record_visibility,
    test_dismissed_create_success_records_visibility,
    test_failed_create_does_not_overwrite_visibility,
)
from tests.ace.tui.modals.test_new_project_create_execution_cli import (
    test_create_apply_submission_matches_cli_request_from_args,
    test_create_check_argv_preserves_option_values,
    test_create_submission_round_trips_through_request_sidecar,
    test_options_from_argv_keeps_transport_spellings_as_data,
)
from tests.ace.tui.modals.test_new_project_create_execution_review import (
    test_bare_git_create_review_omits_visibility_copy,
    test_create_review_button_enters_review_and_back_restores_configure,
    test_create_review_compact_heading_stays_visible,
    test_create_review_renders_danger_heading_and_keep_notice,
    test_create_y_submits_project_create,
    test_duplicate_create_stays_on_review,
)

__all__ = [
    "test_options_from_argv_keeps_transport_spellings_as_data",
    "test_create_check_argv_preserves_option_values",
    "test_create_apply_submission_matches_cli_request_from_args",
    "test_create_submission_round_trips_through_request_sidecar",
    "test_create_review_renders_danger_heading_and_keep_notice",
    "test_bare_git_create_review_omits_visibility_copy",
    "test_create_review_compact_heading_stays_visible",
    "test_create_review_button_enters_review_and_back_restores_configure",
    "test_create_y_submits_project_create",
    "test_duplicate_create_stays_on_review",
    "test_dismissed_create_success_records_visibility",
    "test_failed_create_does_not_overwrite_visibility",
    "test_add_complete_does_not_record_visibility",
]
