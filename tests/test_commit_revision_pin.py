"""Coverage for the ``repos.linked[].revision_pin`` pin-follow behavior.

Split into focused modules; this module re-exports every test so the
original import path keeps working.
"""

from __future__ import annotations

from tests.test_commit_revision_pin_config import (
    test_doctor_accepts_valid_pin_file,
    test_doctor_flags_absolute_pin_path,
    test_doctor_flags_missing_pin_file,
    test_doctor_flags_non_sha_pin_file,
    test_doctor_flags_symlinked_pin_path,
    test_normalize_revision_pin_accepts_relative_paths,
    test_normalize_revision_pin_rejects_absolute_and_escaping_paths,
    test_normalize_revision_pin_rejects_non_strings,
    test_normalize_revision_pin_rejects_windows_drive_paths,
    test_revision_pin_for_entry_returns_none_when_unset,
    test_revision_pin_models_carry_the_field,
    test_revision_pins_ignore_cwd_project_config,
    test_revision_pins_read_from_project_local_config,
)
from tests.test_commit_revision_pin_dispatch import (
    test_dispatch_commits_pinned_sibling_first_and_follows_pin,
    test_dispatch_keeps_today_order_without_pin,
    test_order_unchanged_when_sibling_deferred,
    test_order_unchanged_without_main_commit,
    test_order_unchanged_without_pin,
    test_pinned_sibling_ordered_first,
    test_without_pin_protected_drops_host_pin,
)
from tests.test_commit_revision_pin_write import (
    test_pin_write_recovery_resume_idempotent,
    test_pin_write_skips_absolute_pin_rel,
    test_pin_write_skips_symlinked_parent_outside_checkout,
    test_pin_write_skips_symlinked_pin_file_outside_checkout,
    test_pin_write_skips_when_pin_not_ancestor,
    test_pin_write_skips_when_sha_not_on_default_branch,
    test_pin_write_skip_conditions_never_fail,
    test_pin_written_and_included_in_evidence,
)

__test__ = False

__all__ = [
    "test_dispatch_commits_pinned_sibling_first_and_follows_pin",
    "test_dispatch_keeps_today_order_without_pin",
    "test_doctor_accepts_valid_pin_file",
    "test_doctor_flags_absolute_pin_path",
    "test_doctor_flags_missing_pin_file",
    "test_doctor_flags_non_sha_pin_file",
    "test_doctor_flags_symlinked_pin_path",
    "test_normalize_revision_pin_accepts_relative_paths",
    "test_normalize_revision_pin_rejects_absolute_and_escaping_paths",
    "test_normalize_revision_pin_rejects_non_strings",
    "test_normalize_revision_pin_rejects_windows_drive_paths",
    "test_order_unchanged_when_sibling_deferred",
    "test_order_unchanged_without_main_commit",
    "test_order_unchanged_without_pin",
    "test_pin_write_recovery_resume_idempotent",
    "test_pin_write_skips_absolute_pin_rel",
    "test_pin_write_skips_symlinked_parent_outside_checkout",
    "test_pin_write_skips_symlinked_pin_file_outside_checkout",
    "test_pin_write_skips_when_pin_not_ancestor",
    "test_pin_write_skips_when_sha_not_on_default_branch",
    "test_pin_write_skip_conditions_never_fail",
    "test_pin_written_and_included_in_evidence",
    "test_pinned_sibling_ordered_first",
    "test_revision_pin_for_entry_returns_none_when_unset",
    "test_revision_pin_models_carry_the_field",
    "test_revision_pins_ignore_cwd_project_config",
    "test_revision_pins_read_from_project_local_config",
    "test_without_pin_protected_drops_host_pin",
]
