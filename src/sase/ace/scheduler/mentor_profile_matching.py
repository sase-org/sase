"""Mentor profile matching logic — determines which profiles match which commits."""

import fnmatch
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field

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

# Module-level cache: (changespec_name, latest_entry_id) pairs already diagnosed
_diagnosed_entries: set[tuple[str, str]] = set()


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

        # Match "diff -r ... path/to/file" (hg format, single or double -r)
        hg_match = re.match(r"^diff -r [a-f0-9]+(?: -r [a-f0-9]+)? (\S+)", line)
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
        # Skip profiles scoped to other projects
        if (
            profile.projects is not None
            and changespec.project_basename not in profile.projects
        ):
            continue
        # Check if profile matches any commit
        if profile_matches_any_commit(profile, commits_to_check):
            result.append((latest_entry_id, profile))

    return result


def _log_no_match_diagnostics(
    changespec: ChangeSpec,
    log: LogCallback,
) -> None:
    """Log diagnostic trace when no mentor profiles match eligible commits.

    Only emits once per (changespec_name, latest_entry_id) to avoid noise.
    """
    # Find latest non-proposal entry ID
    latest_entry_id: str | None = None
    if changespec.commits:
        for entry in reversed(changespec.commits):
            if entry.display_number.isdigit():
                latest_entry_id = entry.display_number
                break

    if latest_entry_id is None:
        return

    # Only diagnose once per (changespec, entry) pair
    cache_key = (changespec.name, latest_entry_id)
    if cache_key in _diagnosed_entries:
        return

    # Only log if there are eligible commits
    commits_to_check = _get_commits_since_last_mentors(changespec)
    if not commits_to_check:
        return

    _diagnosed_entries.add(cache_key)

    # Use existing trace infrastructure for detailed per-profile breakdown
    traces = trace_profile_matching(changespec)
    if not traces:
        log(f"No mentor profiles loaded for {changespec.name}", "dim")
        return

    log(
        f"No mentor profiles matched for {changespec.name} ({len(traces)} evaluated)",
        "dim",
    )
    for trace in traces:
        reasons = []
        for cr in trace.criteria_results:
            if not cr.configured:
                continue
            if not cr.matched:
                reasons.append(
                    f"{cr.criterion}: {cr.details}" if cr.details else cr.criterion
                )
        reason_str = (
            "; ".join(reasons) if reasons else "no matching criteria configured"
        )
        log(f"  {trace.profile_name}: {reason_str}", "dim")


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
    if changespec.status in (
        "Draft",
        "WIP",
        "Reverted",
        "Submitted",
        "Archived",
    ):
        return updates

    matching_profiles = _get_matching_profiles_for_entry(changespec)
    if not matching_profiles:
        _log_no_match_diagnostics(changespec, log)
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


@dataclass
class _CriterionResult:
    """Result of evaluating a single matching criterion."""

    criterion: str
    configured: bool
    matched: bool
    details: str = ""


@dataclass
class _ProfileMatchTrace:
    """Trace of matching a single profile against commits."""

    profile_name: str
    criteria_results: list[_CriterionResult] = field(default_factory=list)
    overall_match: bool = False


def _trace_profile_match(
    profile: MentorProfileConfig,
    commits: list[CommitEntry],
    changespec: ChangeSpec | None = None,
) -> _ProfileMatchTrace:
    """Trace how a profile matches against a set of commits, returning details."""
    trace = _ProfileMatchTrace(profile_name=profile.profile_name)

    # projects scope
    if profile.projects is not None and changespec is not None:
        project_matched = changespec.project_basename in profile.projects
        trace.criteria_results.append(
            _CriterionResult(
                criterion="projects",
                configured=True,
                matched=project_matched,
                details=(
                    f"project '{changespec.project_basename}' "
                    f"{'in' if project_matched else 'not in'} {profile.projects}"
                ),
            )
        )
        if not project_matched:
            trace.overall_match = False
            return trace
    else:
        trace.criteria_results.append(
            _CriterionResult(
                criterion="projects", configured=False, matched=False, details=""
            )
        )

    # first_commit
    has_first = any(c.display_number == "1" for c in commits)
    trace.criteria_results.append(
        _CriterionResult(
            criterion="first_commit",
            configured=profile.first_commit,
            matched=profile.first_commit and has_first,
            details="commit (1) present" if has_first else "no commit (1)",
        )
    )

    # file_globs
    if profile.file_globs:
        glob_matched = False
        details_parts: list[str] = []
        for commit in commits:
            if not commit.diff:
                continue
            full_path = os.path.expanduser(commit.diff)
            if not os.path.exists(full_path):
                details_parts.append(f"diff {commit.diff}: file not found")
                continue
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                diff_content = f.read()
            changed_files = _extract_changed_files_from_diff(diff_content)
            for pattern in profile.file_globs:
                for filepath in changed_files:
                    if fnmatch.fnmatch(filepath, pattern):
                        details_parts.append(f"{pattern} matched {filepath}")
                        glob_matched = True
            if not glob_matched and changed_files:
                details_parts.append(
                    f"checked {len(changed_files)} files, no glob match"
                )
        trace.criteria_results.append(
            _CriterionResult(
                criterion="file_globs",
                configured=True,
                matched=glob_matched,
                details="; ".join(details_parts) if details_parts else "no diffs",
            )
        )
    else:
        trace.criteria_results.append(
            _CriterionResult(
                criterion="file_globs", configured=False, matched=False, details=""
            )
        )

    # diff_regexes
    if profile.diff_regexes:
        regex_matched = False
        regex_details: list[str] = []
        for commit in commits:
            if not commit.diff:
                continue
            full_path = os.path.expanduser(commit.diff)
            if not os.path.exists(full_path):
                continue
            with open(full_path, encoding="utf-8", errors="ignore") as f:
                diff_content = f.read()
            for regex in profile.diff_regexes:
                if re.search(regex, diff_content):
                    regex_details.append(f"/{regex}/ matched in {commit.diff}")
                    regex_matched = True
        trace.criteria_results.append(
            _CriterionResult(
                criterion="diff_regexes",
                configured=True,
                matched=regex_matched,
                details="; ".join(regex_details) if regex_details else "no match",
            )
        )
    else:
        trace.criteria_results.append(
            _CriterionResult(
                criterion="diff_regexes", configured=False, matched=False, details=""
            )
        )

    # amend_note_regexes
    if profile.amend_note_regexes:
        note_matched = False
        note_details: list[str] = []
        for commit in commits:
            if not commit.note:
                continue
            for regex in profile.amend_note_regexes:
                if re.search(regex, commit.note):
                    note_details.append(
                        f"/{regex}/ matched note ({commit.display_number})"
                    )
                    note_matched = True
        trace.criteria_results.append(
            _CriterionResult(
                criterion="amend_note_regexes",
                configured=True,
                matched=note_matched,
                details="; ".join(note_details) if note_details else "no match",
            )
        )
    else:
        trace.criteria_results.append(
            _CriterionResult(
                criterion="amend_note_regexes",
                configured=False,
                matched=False,
                details="",
            )
        )

    trace.overall_match = any(
        cr.configured and cr.matched for cr in trace.criteria_results
    )
    return trace


def trace_profile_matching(
    changespec: ChangeSpec,
) -> list[_ProfileMatchTrace]:
    """Trace profile matching for a ChangeSpec, returning structured results.

    Args:
        changespec: The ChangeSpec to trace matching for.

    Returns:
        List of _ProfileMatchTrace, one per loaded profile.
    """
    commits = _get_commits_since_last_mentors(changespec)
    profiles = get_all_mentor_profiles()

    if not profiles:
        return []

    return [_trace_profile_match(profile, commits, changespec) for profile in profiles]
