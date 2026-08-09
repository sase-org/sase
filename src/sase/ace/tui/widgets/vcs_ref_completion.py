"""Prompt-bar candidate building for VCS ref-root completion menus."""

from __future__ import annotations

from typing import Literal

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.workspace_provider import VcsNamespaceEntry, get_display_name
from sase.xprompt.vcs_project_completion import VcsProjectEntry
from sase.xprompt.vcs_ref_completion import (
    VcsRefCandidate,
    build_vcs_ref_candidates,
    filter_vcs_ref_candidates,
)

VCS_REF_COMPLETION_KIND = "vcs_ref"
"""``_completion_kind`` value identifying the VCS ref-root menu."""

_NO_KNOWN_REFS_LABEL = "no known projects, PRs, or organizations"
"""Placeholder row text shown when a workflow has no ref-root candidates."""

VcsRefCandidateKind = Literal["project", "patch", "namespace"]


def build_no_known_refs_placeholder() -> CompletionCandidate:
    """Return the dim placeholder row for an empty ref-root catalog."""
    return CompletionCandidate(
        display=_NO_KNOWN_REFS_LABEL,
        insertion="",
        is_dir=False,
        name="",
        metadata=None,
    )


def vcs_ref_completion_candidates(
    workflow: str,
    query: str,
    *,
    entries: list[VcsRefCandidate] | None = None,
) -> tuple[list[CompletionCandidate], bool, bool]:
    """Return ``(candidates, source_empty, has_namespaces)`` for *query*."""
    source = entries if entries is not None else build_vcs_ref_candidates(workflow)
    has_namespaces = any(
        isinstance(candidate, VcsNamespaceEntry) for candidate in source
    )
    if not source:
        return [], True, has_namespaces
    return (
        [_candidate(entry) for entry in filter_vcs_ref_candidates(source, query)],
        False,
        has_namespaces,
    )


def vcs_ref_completion_title(workflow: str, *, has_namespaces: bool) -> str:
    """Return the completion panel title for a workflow ref-root menu."""
    try:
        provider = get_display_name(workflow) or workflow
    except Exception:
        provider = workflow
    suffix = "projects & PRs & orgs" if has_namespaces else "projects & PRs"
    return f"{provider} · {suffix}"


def _candidate(entry: VcsRefCandidate) -> CompletionCandidate:
    if isinstance(entry, VcsNamespaceEntry):
        label = f"{entry.name.rstrip('/')}/"
        return CompletionCandidate(
            display=label,
            insertion=label,
            is_dir=False,
            name=entry.name,
            metadata=entry,
        )

    return CompletionCandidate(
        display=entry.name,
        insertion=entry.name,
        is_dir=False,
        name=entry.name,
        metadata=entry,
    )


__all__ = [
    "VCS_REF_COMPLETION_KIND",
    "build_no_known_refs_placeholder",
    "vcs_ref_completion_candidates",
    "vcs_ref_completion_title",
]
