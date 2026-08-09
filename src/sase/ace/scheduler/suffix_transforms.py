"""Suffix transformation logic for the axe scheduler.

This module handles:
- Transforming old proposal suffixes (error -> removed)
- Stripping error markers from old commit entry hooks (error -> plain)
- Stripping terminal status markers (error -> removed)
"""

from dataclasses import replace

from sase.workflows.commit_utils import update_stitch_suffix

from ..patch import (
    Patch,
    CommentEntry,
    HookEntry,
    MentorEntry,
    MentorStatusLine,
    parse_stitch_id,
)
from ..comments import transform_patch_comments_field
from ..hooks import (
    transform_patch_hooks_field,
    update_hook_status_line_suffix_type,
)
from ..mentors import update_patch_mentors_field

update_commit_entry_suffix = update_stitch_suffix  # legacy compatibility alias
transform_changespec_comments_field = (
    transform_patch_comments_field  # legacy compatibility alias
)
transform_changespec_hooks_field = (  # legacy compatibility alias
    transform_patch_hooks_field
)
update_changespec_mentors_field = (  # legacy compatibility alias
    update_patch_mentors_field
)


def transform_old_proposal_suffixes(patch: Patch) -> list[str]:
    """Remove suffixes from old proposal COMMITS entries.

    An "old proposal" is a proposed entry (Na) where N < the latest regular
    entry number. For example, if COMMITS has (3), then (2a), (2b) are old.

    This affects:
    - COMMITS entry lines with error suffixes (suffix is removed)
    - Hook status lines for those entry IDs (handled separately, transformed)

    Args:
        patch: The Patch to process.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    if not patch.commits:
        return updates

    # Get the last regular (non-proposed) history number
    last_regular_num = 0
    for entry in patch.commits:
        if entry.proposal_letter is None:
            last_regular_num = max(last_regular_num, entry.number)

    # If no regular entries, nothing is "old"
    if last_regular_num == 0:
        return updates

    # Find old proposals with error suffixes that need removal
    for entry in patch.commits:
        if entry.proposal_letter is not None:  # Is a proposal
            if entry.number < last_regular_num:  # Is "old"
                if entry.suffix_type == "error":  # Has error suffix
                    # Remove COMMITS entry suffix
                    success = update_stitch_suffix(
                        patch.file_path,
                        patch.name,
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


def strip_old_entry_error_markers(patch: Patch) -> list[str]:
    """Strip error markers from hook status lines for older commit entries.

    An "older" entry is one where the numeric part of the commit entry ID is
    less than the highest all-numeric entry ID. For example, if COMMITS has
    (1), (2), (3), (2a), then entries (1), (2), (2a) are all "older" than (3).

    This transforms:
        (1) [timestamp] FAILED - (!: message)
    To:
        (1) [timestamp] FAILED - (message)

    Args:
        patch: The Patch to process.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    if not patch.commits or not patch.hooks:
        return updates

    # Find the highest all-numeric commit entry ID
    highest_numeric_id = 0
    for entry in patch.commits:
        if entry.proposal_letter is None:  # All-numeric entry (no letter suffix)
            highest_numeric_id = max(highest_numeric_id, entry.number)

    # If no regular entries, nothing to strip
    if highest_numeric_id == 0:
        return updates

    # Process each hook's status lines
    for hook in patch.hooks:
        if not hook.status_lines:
            continue

        for sl in hook.status_lines:
            # Only process status lines with error suffix_type
            if sl.suffix_type != "error":
                continue

            # Parse the commit entry ID to get numeric part
            entry_num, _ = parse_stitch_id(sl.stitch_num)

            # Check if this entry is "older" (numeric part < highest)
            if entry_num < highest_numeric_id:
                # Strip the error marker by changing to "plain"
                success = update_hook_status_line_suffix_type(
                    patch.file_path,
                    patch.name,
                    hook.command,
                    sl.stitch_num,
                    "plain",
                )
                if success:
                    updates.append(
                        f"Stripped error marker from HOOK '{hook.display_command}' "
                        f"({sl.stitch_num}): {sl.suffix}"
                    )

    return updates


def _transform_terminal_hook_suffixes(
    hooks: list[HookEntry],
) -> tuple[list[HookEntry], list[str]]:
    """Transform terminal hook markers and describe actual changes."""
    updated_hooks: list[HookEntry] = []
    updates: list[str] = []

    for hook in hooks:
        if not hook.status_lines:
            updated_hooks.append(hook)
            continue

        updated_status_lines = []
        for status_line in hook.status_lines:
            if (
                status_line.suffix_type == "running_agent"
                and status_line.suffix is not None
            ):
                updated_status_lines.append(
                    replace(status_line, suffix_type="killed_agent")
                )
                updates.append(
                    f"Converted HOOK '{hook.display_command}' "
                    f"({status_line.stitch_num}) to killed_agent: "
                    f"{status_line.suffix}"
                )
            elif status_line.suffix_type == "error" and status_line.suffix:
                updated_status_lines.append(replace(status_line, suffix_type="plain"))
                updates.append(
                    f"Stripped error marker from HOOK '{hook.display_command}' "
                    f"({status_line.stitch_num}): {status_line.suffix}"
                )
            else:
                updated_status_lines.append(status_line)

        updated_hooks.append(replace(hook, status_lines=updated_status_lines))

    return updated_hooks, updates


def _transform_terminal_comment_suffixes(
    comments: list[CommentEntry],
) -> tuple[list[CommentEntry], list[str]]:
    """Clear terminal comment markers and describe actual changes."""
    updated_comments: list[CommentEntry] = []
    updates: list[str] = []

    for comment in comments:
        should_clear = (
            comment.suffix_type == "running_agent" and comment.suffix is not None
        ) or (comment.suffix_type == "error" and bool(comment.suffix))
        if should_clear:
            updated_comments.append(replace(comment, suffix=None, suffix_type=None))
            updates.append(
                f"Cleared COMMENT [{comment.reviewer}] suffix: {comment.suffix}"
            )
        else:
            updated_comments.append(comment)

    return updated_comments, updates


def strip_terminal_status_markers(patch: Patch) -> list[str]:
    """Strip error suffixes for terminal status Patches.

    For Patches with STATUS = "Reverted" or "Submitted", removes all
    error suffixes (`- (!: MSG)`) across COMMITS, HOOKS, and COMMENTS.

    Args:
        patch: The Patch to process.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    # Only process terminal statuses
    if patch.status not in ("Reverted", "Submitted", "Archived"):
        return updates

    # Process COMMITS entries with error or running_agent suffix
    if patch.commits:
        for entry in patch.commits:
            if entry.suffix_type in ("error", "running_agent"):
                success = update_commit_entry_suffix(  # legacy compatibility alias
                    patch.file_path,
                    patch.name,
                    entry.display_number,
                    "remove",
                )
                if success:
                    updates.append(
                        f"Cleared COMMITS ({entry.display_number}) "
                        f"suffix: {entry.suffix}"
                    )

    # Process HOOKS entries from current disk state so earlier transforms in the
    # same scheduler cycle cannot be undone by this terminal cleanup.
    hook_updates: list[str] = []

    def transform_hooks(hooks: list[HookEntry]) -> list[HookEntry]:
        updated_hooks, current_updates = _transform_terminal_hook_suffixes(hooks)
        hook_updates.extend(current_updates)
        return updated_hooks

    if transform_patch_hooks_field(
        patch.file_path,
        patch.name,
        transform_hooks,
    ):
        updates.extend(hook_updates)

    # Process COMMENTS from current disk state and preserve unrelated or
    # concurrently changed entries.
    comment_updates: list[str] = []

    def transform_comments(comments: list[CommentEntry]) -> list[CommentEntry]:
        updated_comments, current_updates = _transform_terminal_comment_suffixes(
            comments
        )
        comment_updates.extend(current_updates)
        return updated_comments

    if transform_patch_comments_field(
        patch.file_path,
        patch.name,
        transform_comments,
    ):
        updates.extend(comment_updates)

    # Process MENTORS entries with running_agent suffix_type
    if patch.mentors:
        mentors_to_update: list[MentorEntry] = []
        mentor_updates: list[str] = []

        for mentor_entry in patch.mentors:
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
            success = update_patch_mentors_field(
                patch.file_path,
                patch.name,
                mentors_to_update,
            )
            if success:
                updates.extend(mentor_updates)

    return updates
