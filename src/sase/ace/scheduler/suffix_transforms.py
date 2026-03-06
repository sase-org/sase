"""Suffix transformation logic for the axe scheduler.

This module handles:
- Transforming old proposal suffixes (error -> removed)
- Stripping error markers from old commit entry hooks (error -> plain)
- Stripping terminal status markers (error -> removed)
"""

from sase.commit_utils import update_commit_entry_suffix

from ..changespec import (
    ChangeSpec,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
    parse_commit_entry_id,
)
from ..comments import clear_comment_suffix
from ..hooks import update_changespec_hooks_field, update_hook_status_line_suffix_type
from ..mentors import update_changespec_mentors_field


def transform_old_proposal_suffixes(changespec: ChangeSpec) -> list[str]:
    """Remove suffixes from old proposal COMMITS entries.

    An "old proposal" is a proposed entry (Na) where N < the latest regular
    entry number. For example, if COMMITS has (3), then (2a), (2b) are old.

    This affects:
    - COMMITS entry lines with error suffixes (suffix is removed)
    - Hook status lines for those entry IDs (handled separately, transformed)

    Args:
        changespec: The ChangeSpec to process.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    if not changespec.commits:
        return updates

    # Get the last regular (non-proposed) history number
    last_regular_num = 0
    for entry in changespec.commits:
        if entry.proposal_letter is None:
            last_regular_num = max(last_regular_num, entry.number)

    # If no regular entries, nothing is "old"
    if last_regular_num == 0:
        return updates

    # Find old proposals with error suffixes that need removal
    for entry in changespec.commits:
        if entry.proposal_letter is not None:  # Is a proposal
            if entry.number < last_regular_num:  # Is "old"
                if entry.suffix_type == "error":  # Has error suffix
                    # Remove COMMITS entry suffix
                    success = update_commit_entry_suffix(
                        changespec.file_path,
                        changespec.name,
                        entry.display_number,
                        "remove",
                    )
                    if success:
                        updates.append(
                            f"Cleared suffix from old proposal ({entry.display_number})"
                        )

    # Transform hook status line suffixes for old proposal entry IDs
    # (hook suffixes are handled separately by the hooks formatting code)

    return updates


def strip_old_entry_error_markers(changespec: ChangeSpec) -> list[str]:
    """Strip error markers from hook status lines for older commit entries.

    An "older" entry is one where the numeric part of the commit entry ID is
    less than the highest all-numeric entry ID. For example, if COMMITS has
    (1), (2), (3), (2a), then entries (1), (2), (2a) are all "older" than (3).

    This transforms:
        (1) [timestamp] FAILED - (!: message)
    To:
        (1) [timestamp] FAILED - (message)

    Args:
        changespec: The ChangeSpec to process.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    if not changespec.commits or not changespec.hooks:
        return updates

    # Find the highest all-numeric commit entry ID
    highest_numeric_id = 0
    for entry in changespec.commits:
        if entry.proposal_letter is None:  # All-numeric entry (no letter suffix)
            highest_numeric_id = max(highest_numeric_id, entry.number)

    # If no regular entries, nothing to strip
    if highest_numeric_id == 0:
        return updates

    # Process each hook's status lines
    for hook in changespec.hooks:
        if not hook.status_lines:
            continue

        for sl in hook.status_lines:
            # Only process status lines with error suffix_type
            if sl.suffix_type != "error":
                continue

            # Parse the commit entry ID to get numeric part
            entry_num, _ = parse_commit_entry_id(sl.commit_entry_num)

            # Check if this entry is "older" (numeric part < highest)
            if entry_num < highest_numeric_id:
                # Strip the error marker by changing to "plain"
                success = update_hook_status_line_suffix_type(
                    changespec.file_path,
                    changespec.name,
                    hook.command,
                    sl.commit_entry_num,
                    "plain",
                )
                if success:
                    updates.append(
                        f"Stripped error marker from HOOK '{hook.display_command}' "
                        f"({sl.commit_entry_num}): {sl.suffix}"
                    )

    return updates


def strip_terminal_status_markers(changespec: ChangeSpec) -> list[str]:
    """Strip error suffixes for terminal status ChangeSpecs.

    For ChangeSpecs with STATUS = "Reverted" or "Submitted", removes all
    error suffixes (`- (!: MSG)`) across COMMITS, HOOKS, and COMMENTS.

    Args:
        changespec: The ChangeSpec to process.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    # Only process terminal statuses
    if changespec.status not in ("Reverted", "Submitted", "Archived"):
        return updates

    # Process COMMITS entries with error or running_agent suffix
    if changespec.commits:
        for entry in changespec.commits:
            if entry.suffix_type in ("error", "running_agent"):
                success = update_commit_entry_suffix(
                    changespec.file_path,
                    changespec.name,
                    entry.display_number,
                    "remove",
                )
                if success:
                    updates.append(
                        f"Cleared COMMITS ({entry.display_number}) "
                        f"suffix: {entry.suffix}"
                    )

    # Process HOOKS entries with error or running_agent suffix_type
    # Build modified hooks list with cleared suffixes
    if changespec.hooks:
        hooks_to_update: list[HookEntry] = []
        hook_updates: list[str] = []

        for hook in changespec.hooks:
            if hook.status_lines:
                updated_status_lines: list[HookStatusLine] = []
                for sl in hook.status_lines:
                    if sl.suffix_type == "running_agent" and sl.suffix is not None:
                        # Convert running_agent (@:) to killed_agent (~@:)
                        updated_status_lines.append(
                            HookStatusLine(
                                commit_entry_num=sl.commit_entry_num,
                                timestamp=sl.timestamp,
                                status=sl.status,
                                duration=sl.duration,
                                suffix=sl.suffix,
                                suffix_type="killed_agent",
                            )
                        )
                        hook_updates.append(
                            f"Converted HOOK '{hook.display_command}' "
                            f"({sl.commit_entry_num}) to killed_agent: {sl.suffix}"
                        )
                    elif sl.suffix_type == "error" and sl.suffix:
                        # Convert error (!:) to plain (no prefix)
                        updated_status_lines.append(
                            HookStatusLine(
                                commit_entry_num=sl.commit_entry_num,
                                timestamp=sl.timestamp,
                                status=sl.status,
                                duration=sl.duration,
                                suffix=sl.suffix,
                                suffix_type="plain",
                            )
                        )
                        hook_updates.append(
                            f"Stripped error marker from HOOK '{hook.display_command}' "
                            f"({sl.commit_entry_num}): {sl.suffix}"
                        )
                    else:
                        updated_status_lines.append(sl)
                hooks_to_update.append(
                    HookEntry(command=hook.command, status_lines=updated_status_lines)
                )
            else:
                hooks_to_update.append(hook)

        if hook_updates:
            success = update_changespec_hooks_field(
                changespec.file_path,
                changespec.name,
                hooks_to_update,
            )
            if success:
                updates.extend(hook_updates)

    # Process COMMENTS entries with error or running_agent suffix_type
    if changespec.comments:
        for comment in changespec.comments:
            # Clear error suffixes (must be non-empty) and running_agent
            # suffixes (including empty "- (@)" markers)
            if (
                comment.suffix_type == "running_agent" and comment.suffix is not None
            ) or (comment.suffix_type == "error" and comment.suffix):
                success = clear_comment_suffix(
                    changespec.file_path,
                    changespec.name,
                    comment.reviewer,
                    changespec.comments,
                )
                if success:
                    updates.append(
                        f"Cleared COMMENT [{comment.reviewer}] suffix: {comment.suffix}"
                    )

    # Process MENTORS entries with running_agent suffix_type
    if changespec.mentors:
        mentors_to_update: list[MentorEntry] = []
        mentor_updates: list[str] = []

        for mentor_entry in changespec.mentors:
            if mentor_entry.status_lines:
                updated_mentor_status_lines: list[MentorStatusLine] = []
                for msl in mentor_entry.status_lines:
                    if msl.suffix_type == "running_agent" and msl.suffix is not None:
                        # Convert running_agent (@:) to killed_agent (~@:)
                        updated_mentor_status_lines.append(
                            MentorStatusLine(
                                profile_name=msl.profile_name,
                                mentor_name=msl.mentor_name,
                                status=msl.status,
                                timestamp=msl.timestamp,
                                duration=msl.duration,
                                suffix=msl.suffix,
                                suffix_type="killed_agent",
                            )
                        )
                        mentor_updates.append(
                            f"Converted MENTOR '{msl.profile_name}:{msl.mentor_name}' "
                            f"({mentor_entry.entry_id}) to killed_agent: {msl.suffix}"
                        )
                    else:
                        updated_mentor_status_lines.append(msl)
                mentors_to_update.append(
                    MentorEntry(
                        entry_id=mentor_entry.entry_id,
                        profiles=mentor_entry.profiles,
                        status_lines=updated_mentor_status_lines,
                    )
                )
            else:
                mentors_to_update.append(mentor_entry)

        if mentor_updates:
            success = update_changespec_mentors_field(
                changespec.file_path,
                changespec.name,
                mentors_to_update,
            )
            if success:
                updates.extend(mentor_updates)

    return updates
