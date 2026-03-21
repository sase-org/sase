"""Mentor profile matching logic — determines which profiles match which commits."""

import fnmatch
import os
import re
from collections.abc import Callable

from sase.config.mentor import (
    MentorProfileConfig,
    get_all_mentor_profiles,
)

from ..changespec import (
    ChangeSpec,
    CommitEntry,
)

# Type alias for logging callback
LogCallback = Callable[[str, str | None], None]


def _get_commits_since_last_mentors(
    changespec: ChangeSpec,
) -> list[CommitEntry]:
    """Get all regular commits since the last MENTORS entry.

    Args:
        changespec: The ChangeSpec to check.

    Returns:
        List of CommitEntry objects for commits after the last MENTORS entry.
    """
    # Find the highest numeric entry_id in mentors
    last_mentor_id: int | None = None
    if changespec.mentors:
        for me in changespec.mentors:
            if me.entry_id.isdigit():
                entry_num = int(me.entry_id)
                if last_mentor_id is None or entry_num > last_mentor_id:
                    last_mentor_id = entry_num

    # Get all regular commits after that ID
    result: list[CommitEntry] = []
    if changespec.commits:
        for entry in changespec.commits:
            # Skip proposals (entries with letters like "5a")
            if not entry.display_number.isdigit():
                continue
            entry_num = int(entry.display_number)
            # Include if no mentors yet, or at/after last mentor entry
            if last_mentor_id is None or entry_num >= last_mentor_id:
                result.append(entry)
    return result


def _extract_changed_files_from_diff(diff_content: str) -> list[str]:
    """Extract file paths from diff content (hg/git unified diff format).

    Args:
        diff_content: The diff content as a string.

    Returns:
        List of file paths that were changed.
    """
    files = []
    for line in diff_content.split("\n"):
        # Match "diff --git a/path/to/file b/path/to/file"
        git_match = re.match(r"^diff --git a/(\S+) b/(\S+)", line)
        if git_match:
            files.append(git_match.group(2))
            continue

        # Match "diff -r ... path/to/file" (hg format)
        hg_match = re.match(r"^diff -r [a-f0-9]+ (\S+)", line)
        if hg_match:
            files.append(hg_match.group(1))
            continue

    return files


def _profile_matches_commit(
    profile: MentorProfileConfig,
    diff_path: str | None,
    amend_note: str | None,
) -> bool:
    """Check if a profile's criteria match the commit.

    Args:
        profile: The mentor profile configuration.
        diff_path: Path to the diff file, or None.
        amend_note: The commit's note text, or None.

    Returns:
        True if any of the profile's criteria match.
    """
    # Check file_globs
    if profile.file_globs and diff_path:
        full_path = os.path.expanduser(diff_path)
        if os.path.exists(full_path):
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                diff_content = f.read()
            changed_files = _extract_changed_files_from_diff(diff_content)
            for pattern in profile.file_globs:
                for filepath in changed_files:
                    if fnmatch.fnmatch(filepath, pattern):
                        return True

    # Check diff_regexes
    if profile.diff_regexes and diff_path:
        full_path = os.path.expanduser(diff_path)
        if os.path.exists(full_path):
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                diff_content = f.read()
            for regex in profile.diff_regexes:
                if re.search(regex, diff_content):
                    return True

    # Check amend_note_regexes
    if profile.amend_note_regexes and amend_note:
        for regex in profile.amend_note_regexes:
            if re.search(regex, amend_note):
                return True

    return False


def profile_matches_any_commit(
    profile: MentorProfileConfig,
    commits: list[CommitEntry],
) -> bool:
    """Check if a profile matches ANY of the given commits.

    Args:
        profile: The mentor profile config.
        commits: List of commit entries to check.

    Returns:
        True if the profile matches any commit's diff/note.
    """
    if profile.first_commit:
        for commit in commits:
            if commit.display_number == "1":
                return True

    for commit in commits:
        diff_path = commit.diff
        amend_note = commit.note
        if _profile_matches_commit(profile, diff_path, amend_note):
            return True
    return False


def get_profiles_registered_for_entry(
    changespec: ChangeSpec, entry_id: str
) -> set[str]:
    """Get set of profile names already registered for an entry.

    Args:
        changespec: The ChangeSpec to check.
        entry_id: The commit entry ID.

    Returns:
        Set of profile names that are in the MENTORS entry for this entry_id.
    """
    registered: set[str] = set()
    if not changespec.mentors:
        return registered

    for me in changespec.mentors:
        if me.entry_id == entry_id:
            registered.update(me.profiles)

    return registered


def _get_matching_profiles_for_entry(
    changespec: ChangeSpec,
) -> list[tuple[str, MentorProfileConfig]]:
    """Get profiles that match commits (regardless of hook readiness).

    Unlike _get_mentor_profiles_to_run(), this doesn't check hook readiness.
    Used to add profile entries to MENTORS upfront.

    Args:
        changespec: The ChangeSpec to check.

    Returns:
        List of (entry_id, profile) tuples for profiles not yet registered.
    """
    result: list[tuple[str, MentorProfileConfig]] = []

    if not changespec.commits:
        return result

    # Get the latest non-proposal commit entry
    latest_entry_id = None
    for entry in reversed(changespec.commits):
        if entry.display_number.isdigit():
            latest_entry_id = entry.display_number
            break

    if latest_entry_id is None:
        return result

    # Get all commits to check for profile matching
    commits_to_check = _get_commits_since_last_mentors(changespec)
    if not commits_to_check:
        return result

    # Filter out commits that already have MENTORS entries (except latest).
    # This prevents old completed commits from triggering new profile additions.
    # The latest commit is kept because it may have partial coverage (fe712c83).
    mentored_entry_ids = {me.entry_id for me in changespec.mentors or []}
    commits_to_check = [
        c
        for c in commits_to_check
        if c.display_number == latest_entry_id
        or c.display_number not in mentored_entry_ids
    ]
    if not commits_to_check:
        return result

    # Get profiles already registered for this entry
    registered_profiles = get_profiles_registered_for_entry(changespec, latest_entry_id)

    for profile in get_all_mentor_profiles():
        # Skip profiles already registered
        if profile.profile_name in registered_profiles:
            continue
        # Check if profile matches any commit
        if profile_matches_any_commit(profile, commits_to_check):
            result.append((latest_entry_id, profile))

    return result


def add_matching_profiles_upfront(
    changespec: ChangeSpec,
    log: LogCallback,
) -> list[str]:
    """Add matching profiles to MENTORS entry before mentors are ready to run.

    This adds profiles with [0/N] counts as soon as they're detected,
    even before hooks finish. The actual mentors only start when hooks are ready.

    Args:
        changespec: The ChangeSpec to check.
        log: Logging callback.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    # Don't add profiles for non-review statuses
    if changespec.status in ("Draft", "WIP", "Reverted", "Submitted", "Archived"):
        return updates

    matching_profiles = _get_matching_profiles_for_entry(changespec)
    if not matching_profiles:
        return updates

    # Import here to avoid circular imports
    from ..mentors import add_mentor_entry

    for entry_id, profile in matching_profiles:
        success = add_mentor_entry(
            changespec.file_path,
            changespec.name,
            entry_id,
            [profile.profile_name],
        )
        if success:
            total = len(profile.mentors)
            updates.append(
                f"Added profile {profile.profile_name}[0/{total}] to MENTORS ({entry_id})"
            )
            log(
                f"Added profile {profile.profile_name}[0/{total}] to MENTORS ({entry_id})",
                "dim",
            )

    return updates
