"""Trace internals for mentor profile matching — structured per-profile diagnostics."""

import fnmatch
import re
from dataclasses import dataclass, field

from sase.config.mentor import MentorProfileConfig

from ..changespec import ChangeSpec, CommitEntry
from ._mentor_profile_helpers import CommitMatchArtifact


@dataclass
class CriterionResult:
    """Result of evaluating a single matching criterion."""

    criterion: str
    configured: bool
    matched: bool
    details: str = ""


@dataclass
class ProfileMatchTrace:
    """Trace of matching a single profile against commits."""

    profile_name: str
    criteria_results: list[CriterionResult] = field(default_factory=list)
    overall_match: bool = False


def trace_profile_match(
    profile: MentorProfileConfig,
    commits: list[CommitEntry],
    changespec: ChangeSpec | None,
    artifacts: list[CommitMatchArtifact],
) -> ProfileMatchTrace:
    """Trace how a profile matches against a set of commits, returning details."""
    trace = ProfileMatchTrace(profile_name=profile.profile_name)

    # projects scope
    if profile.projects is not None and changespec is not None:
        project_matched = changespec.project_basename in profile.projects
        trace.criteria_results.append(
            CriterionResult(
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
            CriterionResult(
                criterion="projects", configured=False, matched=False, details=""
            )
        )

    # first_commit
    has_first = any(c.display_number == "1" for c in commits)
    trace.criteria_results.append(
        CriterionResult(
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
            CriterionResult(
                criterion="file_globs",
                configured=True,
                matched=glob_matched,
                details="; ".join(details_parts) if details_parts else "no diffs",
            )
        )
    else:
        trace.criteria_results.append(
            CriterionResult(
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
            CriterionResult(
                criterion="diff_regexes",
                configured=True,
                matched=regex_matched,
                details="; ".join(regex_details) if regex_details else "no match",
            )
        )
    else:
        trace.criteria_results.append(
            CriterionResult(
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
            CriterionResult(
                criterion="amend_note_regexes",
                configured=True,
                matched=note_matched,
                details="; ".join(note_details) if note_details else "no match",
            )
        )
    else:
        trace.criteria_results.append(
            CriterionResult(
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
