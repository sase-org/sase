"""Inert helpers for mentor profile matching — no I/O or patched globals."""

import fnmatch
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from sase.config.mentor import MentorProfileConfig

from ..changespec import ChangeSpec, CommitEntry

logger = logging.getLogger(__name__)

LogCallback = Callable[[str, str | None], None]
_UNSET: Final = object()


@dataclass(frozen=True)
class CommitMatchArtifact:
    """Cached commit data used across profile matching checks."""

    entry_id: str
    diff_path: str | None
    amend_note: str | None
    diff_content: str | None
    changed_files: tuple[str, ...]
    used_vcs_fallback: bool = False


def get_commits_since_last_mentors(
    changespec: ChangeSpec,
) -> list[CommitEntry]:
    """Get all regular commits since the last MENTORS entry.

    Args:
        changespec: The ChangeSpec to check.

    Returns:
        List of CommitEntry objects for commits after the last MENTORS entry.
    """
    last_mentor_id: int | None = None
    if changespec.mentors:
        for me in changespec.mentors:
            if me.entry_id.isdigit():
                entry_num = int(me.entry_id)
                if last_mentor_id is None or entry_num > last_mentor_id:
                    last_mentor_id = entry_num

    result: list[CommitEntry] = []
    if changespec.commits:
        for entry in changespec.commits:
            if not entry.display_number.isdigit():
                continue
            entry_num = int(entry.display_number)
            if last_mentor_id is None or entry_num >= last_mentor_id:
                result.append(entry)
    return result


def extract_changed_files_from_diff(diff_content: str) -> list[str]:
    """Extract file paths from diff content (hg/git unified diff format).

    Args:
        diff_content: The diff content as a string.

    Returns:
        List of file paths that were changed.
    """
    files = []
    for line in diff_content.split("\n"):
        git_match = re.match(r"^diff --git a/(\S+) b/(\S+)", line)
        if git_match:
            files.append(git_match.group(2))
            continue

        # Mercurial revision tokens are not guaranteed to be lowercase hex.
        hg_match = re.match(r"^diff -r \S+(?: -r \S+)? (\S+)", line)
        if hg_match:
            files.append(hg_match.group(1))
            continue

    return files


def profile_matches_commit_artifact(
    profile: MentorProfileConfig,
    artifact: CommitMatchArtifact,
) -> bool:
    """Check if a profile's criteria match the commit.

    Args:
        profile: The mentor profile configuration.
        artifact: Cached commit artifact.

    Returns:
        True if any of the profile's criteria match.
    """
    try:
        if profile.file_globs and artifact.changed_files:
            for pattern in profile.file_globs:
                for filepath in artifact.changed_files:
                    if fnmatch.fnmatch(filepath, pattern):
                        return True

        if profile.diff_regexes and artifact.diff_content:
            for regex in profile.diff_regexes:
                if re.search(regex, artifact.diff_content):
                    return True

        if profile.amend_note_regexes and artifact.amend_note:
            for regex in profile.amend_note_regexes:
                if re.search(regex, artifact.amend_note):
                    return True

        return False
    except Exception:
        logger.warning(
            "Error matching profile '%s' against diff '%s'",
            profile.profile_name,
            artifact.diff_path,
            exc_info=True,
        )
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
