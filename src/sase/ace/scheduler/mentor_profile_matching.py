"""Mentor profile matching logic — determines which profiles match which commits."""

import fnmatch
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final

from sase.config.mentor import (
    MentorProfileConfig,
    get_all_mentor_profiles,
)
from sase.running_field import get_workspace_directory
from sase.vcs_provider import VCSProviderNotFoundError, get_vcs_provider

from ..changespec import (
    ChangeSpec,
    CommitEntry,
    parse_commit_entry_id,
)

logger = logging.getLogger(__name__)

# Type alias for logging callback
LogCallback = Callable[[str, str | None], None]
_UNSET: Final = object()


@dataclass(frozen=True)
class _CommitMatchArtifact:
    """Cached commit data used across profile matching checks."""

    entry_id: str
    diff_path: str | None
    amend_note: str | None
    diff_content: str | None
    changed_files: tuple[str, ...]
    used_vcs_fallback: bool = False


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
        # Mercurial revision tokens are not guaranteed to be lowercase hex.
        hg_match = re.match(r"^diff -r \S+(?: -r \S+)? (\S+)", line)
        if hg_match:
            files.append(hg_match.group(1))
            continue

    return files


def _build_commit_match_artifacts(
    commits: list[CommitEntry],
    changespec: ChangeSpec | None = None,
    *,
    preloaded_vcs_fallback: str | None | object = _UNSET,
    require_diff_content: bool = True,
) -> list[_CommitMatchArtifact]:
    """Build commit artifacts once per invocation to avoid repeated file reads."""
    latest_entry_id = max(
        (commit.display_number for commit in commits),
        key=parse_commit_entry_id,
        default=None,
    )
    fallback_diff_content: object | str | None = (
        preloaded_vcs_fallback if preloaded_vcs_fallback is not _UNSET else _UNSET
    )
    artifacts: list[_CommitMatchArtifact] = []

    for commit in commits:
        diff_content = _read_diff_content(commit.diff) if require_diff_content else None
        used_fallback = False
        should_use_fallback = (
            require_diff_content
            and diff_content is None
            and changespec is not None
            and latest_entry_id is not None
            and commit.display_number == latest_entry_id
        )
        if should_use_fallback:
            if fallback_diff_content is _UNSET:
                assert changespec is not None
                fallback_diff_content = _load_latest_diff_from_vcs(changespec)
            if isinstance(fallback_diff_content, str):
                diff_content = fallback_diff_content
                used_fallback = True

        changed_files: tuple[str, ...]
        if diff_content:
            changed_files = tuple(_extract_changed_files_from_diff(diff_content))
        else:
            changed_files = ()

        artifacts.append(
            _CommitMatchArtifact(
                entry_id=commit.display_number,
                diff_path=commit.diff,
                amend_note=commit.note,
                diff_content=diff_content,
                changed_files=changed_files,
                used_vcs_fallback=used_fallback,
            )
        )

    return artifacts


def _profile_matches_commit_artifact(
    profile: MentorProfileConfig,
    artifact: _CommitMatchArtifact,
) -> bool:
    """Check if a profile's criteria match the commit.

    Args:
        profile: The mentor profile configuration.
        artifact: Cached commit artifact.

    Returns:
        True if any of the profile's criteria match.
    """
    try:
        # Check file_globs
        if profile.file_globs and artifact.changed_files:
            for pattern in profile.file_globs:
                for filepath in artifact.changed_files:
                    if fnmatch.fnmatch(filepath, pattern):
                        return True

        # Check diff_regexes
        if profile.diff_regexes and artifact.diff_content:
            for regex in profile.diff_regexes:
                if re.search(regex, artifact.diff_content):
                    return True

        # Check amend_note_regexes
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


def _read_diff_content(diff_path: str | None) -> str | None:
    """Read diff content from a path if it exists and is readable."""
    if not diff_path:
        return None

    full_path = os.path.expanduser(diff_path)
    if not os.path.exists(full_path):
        return None

    try:
        with open(full_path, encoding="utf-8", errors="ignore") as f:
            return f.read()
    except OSError:
        return None


def _load_latest_diff_from_vcs(changespec: ChangeSpec) -> str | None:
    """Load latest commit diff via VCS for cross-machine DIFF-path fallback."""
    try:
        workspace_dir = get_workspace_directory(changespec.project_basename, 1)
    except RuntimeError:
        return None

    try:
        provider = get_vcs_provider(workspace_dir)
    except VCSProviderNotFoundError:
        return None

    rev_candidates = [changespec.name]
    if changespec.cl:
        rev_candidates.append(changespec.cl)

    for revision in rev_candidates:
        try:
            resolved = provider.resolve_revision(
                revision, changespec.project_basename, workspace_dir
            )
            success, diff_text = provider.diff_revision(resolved, workspace_dir)
        except Exception:
            continue

        if success and diff_text:
            return diff_text

    return None


def preload_vcs_fallback_diff(
    changespec: ChangeSpec,
    commits: list[CommitEntry],
) -> str | None:
    """Pre-load VCS fallback diff for the latest commit if its local diff is missing.

    Call once before iterating over profiles to avoid repeated
    _load_latest_diff_from_vcs() calls (which may trigger network operations).
    """
    latest_entry_id = max(
        (commit.display_number for commit in commits),
        key=parse_commit_entry_id,
        default=None,
    )
    if latest_entry_id is None:
        return None

    for commit in commits:
        if commit.display_number == latest_entry_id:
            if _read_diff_content(commit.diff) is None:
                return _load_latest_diff_from_vcs(changespec)
            return None  # Local diff exists, no fallback needed

    return None


def profile_matches_any_commit(
    profile: MentorProfileConfig,
    commits: list[CommitEntry],
    changespec: ChangeSpec | None = None,
    preloaded_vcs_fallback: str | None | object = _UNSET,
    commit_artifacts: list[_CommitMatchArtifact] | None = None,
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

    artifacts = commit_artifacts
    if artifacts is None:
        artifacts = _build_commit_match_artifacts(
            commits,
            changespec,
            preloaded_vcs_fallback=preloaded_vcs_fallback,
            require_diff_content=bool(profile.file_globs or profile.diff_regexes),
        )

    for artifact in artifacts:
        if _profile_matches_commit_artifact(profile, artifact):
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


def get_matching_profiles_for_entry(
    changespec: ChangeSpec,
    mentor_profiles: list[MentorProfileConfig] | None = None,
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

    # Pre-load VCS fallback diff once for all profiles
    preloaded_fallback = preload_vcs_fallback_diff(changespec, commits_to_check)
    commit_artifacts = _build_commit_match_artifacts(
        commits_to_check,
        changespec,
        preloaded_vcs_fallback=preloaded_fallback,
    )
    profiles = (
        mentor_profiles if mentor_profiles is not None else get_all_mentor_profiles()
    )

    for profile in profiles:
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
        if profile_matches_any_commit(
            profile,
            commits_to_check,
            changespec,
            commit_artifacts=commit_artifacts,
        ):
            result.append((latest_entry_id, profile))

    return result


@dataclass(frozen=True)
class _UpfrontMatchResult:
    """Outcome of one ``add_matching_profiles_upfront`` invocation.

    ``newly_matched`` lets callers know which (entry_id, profile) pairs were
    just written to MENTORS this cycle — important because the in-memory
    ``ChangeSpec`` is not refreshed until the next axe poll.
    """

    updates: list[str]
    newly_matched: list[tuple[str, "MentorProfileConfig"]]


def add_matching_profiles_upfront(
    changespec: ChangeSpec,
    log: LogCallback,
    mentor_profiles: list[MentorProfileConfig] | None = None,
) -> _UpfrontMatchResult:
    """Add matching profiles to MENTORS entry before mentors are ready to run.

    This adds profiles with [0/N] counts as soon as they're detected,
    even before hooks finish. The actual mentors only start when hooks are ready.

    Args:
        changespec: The ChangeSpec to check.
        log: Logging callback.

    Returns:
        ``UpfrontMatchResult`` with human-readable update messages and the
        list of (entry_id, profile) pairs that were successfully written to
        the MENTORS field this cycle.
    """
    updates: list[str] = []
    newly_matched: list[tuple[str, MentorProfileConfig]] = []

    # Don't add profiles for non-review statuses
    if changespec.status in (
        "Draft",
        "WIP",
        "Reverted",
        "Submitted",
        "Archived",
    ):
        return _UpfrontMatchResult(updates=updates, newly_matched=newly_matched)

    all_profiles = (
        mentor_profiles if mentor_profiles is not None else get_all_mentor_profiles()
    )
    log(
        f"Mentor matching: {len(all_profiles)} profile(s) loaded for"
        f" '{changespec.name}'",
        "dim",
    )

    matching_profiles = get_matching_profiles_for_entry(
        changespec,
        mentor_profiles=all_profiles,
    )
    if not matching_profiles:
        log(
            f"Mentor matching: 0 new profiles matched for '{changespec.name}'",
            "dim",
        )
        return _UpfrontMatchResult(updates=updates, newly_matched=newly_matched)

    log(
        f"Mentor matching: {len(matching_profiles)} new profile(s) matched for"
        f" '{changespec.name}'",
        "dim",
    )

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
            newly_matched.append((entry_id, profile))
            total = len(profile.mentors)
            updates.append(
                f"Added profile {profile.profile_name}[0/{total}] to MENTORS ({entry_id})"
            )
            log(
                f"Added profile {profile.profile_name}[0/{total}] to MENTORS ({entry_id})",
                "dim",
            )

    return _UpfrontMatchResult(updates=updates, newly_matched=newly_matched)


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
    preloaded_vcs_fallback: str | None | object = _UNSET,
    commit_artifacts: list[_CommitMatchArtifact] | None = None,
) -> _ProfileMatchTrace:
    """Trace how a profile matches against a set of commits, returning details."""
    trace = _ProfileMatchTrace(profile_name=profile.profile_name)
    artifacts = commit_artifacts
    if artifacts is None:
        artifacts = _build_commit_match_artifacts(
            commits,
            changespec,
            preloaded_vcs_fallback=preloaded_vcs_fallback,
        )

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
        for artifact in artifacts:
            if artifact.diff_content is None:
                if artifact.diff_path:
                    details_parts.append(f"diff {artifact.diff_path}: file not found")
                continue
            for pattern in profile.file_globs:
                for filepath in artifact.changed_files:
                    if fnmatch.fnmatch(filepath, pattern):
                        details_parts.append(f"{pattern} matched {filepath}")
                        if artifact.used_vcs_fallback:
                            details_parts.append("used VCS fallback diff")
                        glob_matched = True
            if not glob_matched and artifact.changed_files:
                details_parts.append(
                    f"checked {len(artifact.changed_files)} files, no glob match"
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
        for artifact in artifacts:
            if artifact.diff_content is None:
                continue
            for regex in profile.diff_regexes:
                if re.search(regex, artifact.diff_content):
                    regex_details.append(f"/{regex}/ matched in {artifact.diff_path}")
                    if artifact.used_vcs_fallback:
                        regex_details.append("used VCS fallback diff")
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
        for artifact in artifacts:
            if not artifact.amend_note:
                continue
            for regex in profile.amend_note_regexes:
                if re.search(regex, artifact.amend_note):
                    note_details.append(f"/{regex}/ matched note ({artifact.entry_id})")
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

    # Pre-load VCS fallback diff once for all profiles
    preloaded_fallback = preload_vcs_fallback_diff(changespec, commits)
    commit_artifacts = _build_commit_match_artifacts(
        commits,
        changespec,
        preloaded_vcs_fallback=preloaded_fallback,
    )

    return [
        _trace_profile_match(
            profile,
            commits,
            changespec,
            commit_artifacts=commit_artifacts,
        )
        for profile in profiles
    ]
