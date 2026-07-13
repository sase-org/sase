"""ChangeSpec parsing utilities."""

from collections.abc import Sequence
from typing import Any

from .locking import (
    LockTimeoutError,
    acquire_edit_lock,
    changespec_lock,
    is_edit_locked,
    release_edit_lock,
    wait_for_edit_lock_release,
    write_changespec_atomic,
)
from .models import (
    ERROR_SUFFIX_MESSAGES,
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    DeltaEntry,
    DeltaLineStats,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
    TimestampEntry,
    extract_pid_from_agent_suffix,
    get_base_status,
    is_error_suffix,
    is_plain_suffix,
    is_running_agent_suffix,
    is_running_process_suffix,
    parse_commit_entry_id,
)
from .cache import (
    ChangeSpecSnapshotCache,
    find_all_changespecs_cached,
    get_global_snapshot_cache,
)
from .discovery import (
    iter_changespec_project_file_records,
    iter_changespec_project_files,
)
from .parser import parse_project_file
from .archive import (
    get_archive_file_path,
    get_main_file_path,
    is_archive_file,
    move_changespec_to_file,
)
from .project_spec_migration import (
    MigrationReport,
    migrate_all_projects,
    migrate_project_dir,
)
from .project_spec_path import (
    PROJECT_SPEC_EXTENSIONS,
    active_project_spec_filename,
    archive_project_spec_filename,
    legacy_active_project_spec_filename,
    legacy_archive_project_spec_filename,
)
from .raw_text import get_raw_changespec_text
from .validation import (
    all_hooks_passed_for_entries,
    count_agent_runners_global,
    count_all_runners_global,
    count_hook_runners_global,
    count_running_agents_global,
    count_running_hooks_global,
    get_current_and_proposal_entry_ids,
    has_any_error_suffix,
    has_any_running_agent,
    has_any_running_process,
    has_any_status_suffix,
    is_parent_ready_for_mail,
)

__all__ = [
    # Dataclasses
    "ChangeSpec",
    "CommitEntry",
    "HookEntry",
    "HookStatusLine",
    "CommentEntry",
    "DeltaEntry",
    "DeltaLineStats",
    "MentorEntry",
    "MentorStatusLine",
    "TimestampEntry",
    # Constants
    "ERROR_SUFFIX_MESSAGES",
    # Locking
    "LockTimeoutError",
    "acquire_edit_lock",
    "changespec_lock",
    "is_edit_locked",
    "release_edit_lock",
    "wait_for_edit_lock_release",
    "write_changespec_atomic",
    # Functions
    "extract_pid_from_agent_suffix",
    "is_error_suffix",
    "is_plain_suffix",
    "is_running_agent_suffix",
    "is_running_process_suffix",
    "get_base_status",
    "parse_commit_entry_id",
    "count_agent_runners_global",
    "count_all_runners_global",
    "count_hook_runners_global",
    "count_running_agents_global",
    "count_running_hooks_global",
    "has_any_error_suffix",
    "has_any_running_agent",
    "has_any_running_process",
    "has_any_status_suffix",
    "is_parent_ready_for_mail",
    "get_current_and_proposal_entry_ids",
    "all_hooks_passed_for_entries",
    "parse_project_file",
    "ChangeSpecSnapshotCache",
    "find_all_changespecs_cached",
    "get_global_snapshot_cache",
    "get_raw_changespec_text",
    "get_archive_file_path",
    "get_main_file_path",
    "is_archive_file",
    "move_changespec_to_file",
    "PROJECT_SPEC_EXTENSIONS",
    "active_project_spec_filename",
    "archive_project_spec_filename",
    "legacy_active_project_spec_filename",
    "legacy_archive_project_spec_filename",
    "MigrationReport",
    "migrate_all_projects",
    "migrate_project_dir",
    "find_all_changespecs",
    "get_eligible_parents_in_project",
    "get_entry_id",
]


def find_all_changespecs(
    include_states: Sequence[str] | str = ("enabled",),
) -> list[ChangeSpec]:
    """Find ChangeSpecs in lifecycle-selected project files.

    Returns:
        ChangeSpecs from enabled and archive ProjectSpec files for projects whose
        lifecycle state matches ``include_states``. Normal callers default to
        enabled projects; history/agent views can pass ``"all"`` explicitly.
    """
    all_changespecs: list[ChangeSpec] = []
    for item in iter_changespec_project_file_records(include_states=include_states):
        specs = parse_project_file(str(item.path))
        for spec in specs:
            spec.project_display_name = item.project_display_name
        all_changespecs.extend(specs)
    return all_changespecs


# Eligible statuses for rebase parent selection
_ELIGIBLE_REBASE_STATUSES = ("WIP", "Draft", "Ready", "Mailed")


def get_eligible_parents_in_project(
    project_file: str, exclude_name: str
) -> list[tuple[str, str]]:
    """Get all ChangeSpecs in the same project file eligible to be parents for rebase.

    Args:
        project_file: Path to the project file
        exclude_name: Name to exclude (the PR being rebased)

    Returns:
        List of (name, status) tuples for ChangeSpecs with status WIP/Draft/Ready/Mailed
    """
    changespecs = parse_project_file(project_file)
    eligible: list[tuple[str, str]] = []

    for cs in changespecs:
        # Skip the PR being rebased
        if cs.name == exclude_name:
            continue

        # Check if status is eligible (use base status to handle suffixes)
        base_status = get_base_status(cs.status)
        if base_status in _ELIGIBLE_REBASE_STATUSES:
            eligible.append((cs.name, base_status))

    return eligible


def get_entry_id(entry: dict[str, Any]) -> str:
    """Get the entry ID string (e.g., '1', '2a') from an entry dict.

    Args:
        entry: Dict with 'number' and optional 'letter' keys.

    Returns:
        Entry ID string like '1' or '2a'.
    """
    num = entry["number"]
    letter = entry.get("letter") or ""
    return f"{num}{letter}"
