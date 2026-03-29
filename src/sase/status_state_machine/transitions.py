"""Main status transition logic for ChangeSpecs.

This module contains the core transition_changespec_status function that
orchestrates the transition workflow by delegating to specialized handlers.
"""

import logging
from typing import TYPE_CHECKING

from sase.ace.changespec import changespec_lock

from .constants import ARCHIVE_STATUSES
from .field_updates import read_status_from_lines
from .handlers import (
    handle_archived_transition,
    handle_draft_transition,
    handle_ready_transition,
    handle_reverted_transition,
    handle_wip_to_draft_transition,
)
from .siblings import SiblingRevertResult
from .suffix import handle_suffix_append, handle_suffix_strip

if TYPE_CHECKING:
    from rich.console import Console

logger = logging.getLogger(__name__)


def transition_changespec_status(
    project_file: str,
    changespec_name: str,
    new_status: str,
    validate: bool = True,
    console: "Console | None" = None,
) -> tuple[bool, str | None, str | None, list[SiblingRevertResult]]:
    """
    Transition a ChangeSpec to a new STATUS with optional validation.

    Acquires a lock for the entire read-validate-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        changespec_name: NAME of the ChangeSpec to update
        new_status: New STATUS value
        validate: If True, validate the transition is allowed
        console: Optional Rich console for output during sibling reverts

    Returns:
        Tuple of (success, old_status, error_msg, sibling_revert_results)
        - success: True if transition succeeded
        - old_status: Previous status value (None if not found)
        - error_msg: Error message if failed (None if succeeded)
        - sibling_revert_results: List of SiblingRevertResult for reverted siblings
    """
    # Track if we need to strip/append suffix after lock releases
    suffix_strip_info: tuple[str, str] | None = None
    suffix_append_info: tuple[str, str] | None = None
    result: tuple[bool, str | None, str | None] | None = None
    sibling_results: list[SiblingRevertResult] = []

    with changespec_lock(project_file):
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        # Read current status
        old_status = read_status_from_lines(lines, changespec_name)

        if old_status is None:
            error_msg = f"ChangeSpec '{changespec_name}' not found in {project_file}"
            logger.error(error_msg)
            result = (False, None, error_msg)

        elif new_status == "Draft" and old_status == "WIP":
            # WIP→Draft: simple status change, no suffix/mentor manipulation
            result = handle_wip_to_draft_transition(
                project_file, changespec_name, old_status, new_status, lines, validate
            )

        elif new_status == "Draft" and old_status == "Ready":
            # Ready→Draft: append suffix, set mentor draft flags
            success, old_st, err, suffix_append_info = handle_draft_transition(
                project_file, changespec_name, old_status, new_status, lines, validate
            )
            result = (success, old_st, err)

        elif new_status == "Ready":
            # WIP→Ready or Draft→Ready: strip suffix, revert siblings
            success, old_st, err, suffix_strip_info = handle_ready_transition(
                project_file, changespec_name, old_status, new_status, lines, validate
            )
            result = (success, old_st, err)

        elif new_status == "Reverted":
            result = handle_reverted_transition(
                project_file, changespec_name, old_status, new_status, lines, validate
            )

        elif new_status == "Archived":
            result = handle_archived_transition(
                project_file, changespec_name, old_status, new_status, lines, validate
            )

        else:
            # Mailed, Submitted, etc. - use ready transition handler
            success, old_st, err, _ = handle_ready_transition(
                project_file, changespec_name, old_status, new_status, lines, validate
            )
            result = (success, old_st, err)

    # Strip __<N> suffix when transitioning to Ready (outside lock)
    if suffix_strip_info is not None:
        suffixed_name, base_name = suffix_strip_info
        sibling_results = handle_suffix_strip(
            project_file, suffixed_name, base_name, console
        )

    # Append __<N> suffix when transitioning from Ready to Draft (outside lock)
    if suffix_append_info is not None:
        base_name, suffixed_name = suffix_append_info
        handle_suffix_append(project_file, base_name, suffixed_name)

    # Move ChangeSpec between main and archive files based on status change
    assert result is not None
    if result[0]:  # success
        from sase.ace.changespec.archive import (
            get_archive_file_path,
            get_main_file_path,
            is_archive_file,
            move_changespec_to_file,
        )

        old_status_val = result[1]
        old_is_archive = old_status_val in ARCHIVE_STATUSES if old_status_val else False
        new_is_archive = new_status in ARCHIVE_STATUSES

        if new_is_archive != old_is_archive:
            # Determine main and archive file paths, handling the case
            # where project_file itself is the archive file
            if is_archive_file(project_file):
                main_file = get_main_file_path(project_file)
                archive_file = project_file
            else:
                main_file = project_file
                archive_file = get_archive_file_path(project_file)

            if new_is_archive:
                move_changespec_to_file(main_file, archive_file, changespec_name)
            else:
                move_changespec_to_file(archive_file, main_file, changespec_name)

    # Record STATUS timestamp on successful transition
    if result[0] and result[1] is not None:
        from sase.ace.timestamps.recording import add_timestamp_entry_atomic

        add_timestamp_entry_atomic(
            project_file,
            changespec_name,
            "STATUS",
            f"{result[1]} -> {new_status}",
        )

    return (result[0], result[1], result[2], sibling_results)
