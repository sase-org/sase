"""Mentor profile matching logic — determines which profiles match which commits."""

import logging
import os

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
from ._mentor_profile_helpers import (
    CommitMatchArtifact,
    LogCallback,
    _UNSET,
    extract_changed_files_from_diff,
    get_commits_since_last_mentors,
    get_profiles_registered_for_entry,
    profile_matches_commit_artifact,
)
from ._mentor_profile_tracing import (
    CriterionResult,
    ProfileMatchTrace,
    trace_profile_match,
)
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _build_commit_match_artifacts(
    commits: list[CommitEntry],
    changespec: ChangeSpec | None = None,
    *,
    preloaded_vcs_fallback: str | None | object = _UNSET,
    require_diff_content: bool = True,
) -> list[CommitMatchArtifact]:
    """Build commit artifacts once per invocation to avoid repeated file reads."""
    latest_entry_id = max(
        (commit.display_number for commit in commits),
        key=parse_commit_entry_id,
        default=None,
    )
    fallback_diff_content: object | str | None = (
        preloaded_vcs_fallback if preloaded_vcs_fallback is not _UNSET else _UNSET
    )
    artifacts: list[CommitMatchArtifact] = []

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
            changed_files = tuple(extract_changed_files_from_diff(diff_content))
        else:
            changed_files = ()

        artifacts.append(
            CommitMatchArtifact(
                entry_id=commit.display_number,
                diff_path=commit.diff,
                amend_note=commit.note,
                diff_content=diff_content,
                changed_files=changed_files,
                used_vcs_fallback=used_fallback,
            )
        )

    return artifacts


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
    commit_artifacts: list[CommitMatchArtifact] | None = None,
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
        if profile_matches_commit_artifact(profile, artifact):
            return True
    return False


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

    latest_entry_id = None
    for entry in reversed(changespec.commits):
        if entry.display_number.isdigit():
            latest_entry_id = entry.display_number
            break

    if latest_entry_id is None:
        return result

    commits_to_check = get_commits_since_last_mentors(changespec)
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

    registered_profiles = get_profiles_registered_for_entry(changespec, latest_entry_id)

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
        if profile.profile_name in registered_profiles:
            continue
        if (
            profile.projects is not None
            and changespec.project_basename not in profile.projects
        ):
            continue
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


def trace_profile_matching(
    changespec: ChangeSpec,
) -> list[ProfileMatchTrace]:
    """Trace profile matching for a ChangeSpec, returning structured results.

    Args:
        changespec: The ChangeSpec to trace matching for.

    Returns:
        List of ProfileMatchTrace, one per loaded profile.
    """
    commits = get_commits_since_last_mentors(changespec)
    profiles = get_all_mentor_profiles()

    if not profiles:
        return []

    preloaded_fallback = preload_vcs_fallback_diff(changespec, commits)
    commit_artifacts = _build_commit_match_artifacts(
        commits,
        changespec,
        preloaded_vcs_fallback=preloaded_fallback,
    )

    return [
        trace_profile_match(profile, commits, changespec, commit_artifacts)
        for profile in profiles
    ]
