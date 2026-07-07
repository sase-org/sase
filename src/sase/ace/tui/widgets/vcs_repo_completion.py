"""Prompt-bar candidate building for VCS repository completion menus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.workspace_provider import VcsRepoEntry
from sase.xprompt.vcs_repo_completion import (
    VcsRepoFetchResult,
    filter_vcs_repo_entries,
)

VCS_REPO_COMPLETION_KIND = "vcs_repo"
"""``_completion_kind`` value identifying the VCS repository menu."""

VcsRepoPlaceholderKind = Literal["loading", "empty", "error"]


@dataclass(frozen=True)
class VcsRepoCompletionPlaceholder:
    """Non-selectable placeholder row for repo completion menu states."""

    kind: VcsRepoPlaceholderKind
    message: str


def build_loading_placeholder(namespace: str) -> CompletionCandidate:
    """Return a loading row while a repo list worker is in flight."""
    return _placeholder(
        "loading",
        f"fetching {namespace}/ repositories...",
    )


def vcs_repo_completion_candidates(
    result: VcsRepoFetchResult,
    query: str,
    namespace: str,
) -> tuple[list[CompletionCandidate], bool]:
    """Return ``(candidates, used_placeholder)`` for a repo fetch *result*."""
    if result.entries:
        candidates = [
            _candidate(entry)
            for entry in filter_vcs_repo_entries(result.entries, query)
        ]
        return candidates, False

    if result.status == "error":
        message = result.message or "repo listing failed"
        return [_placeholder("error", message)], True

    return [_placeholder("empty", f"no repositories found for {namespace}")], True


def vcs_repo_completion_title(
    result: VcsRepoFetchResult | None,
    *,
    workflow: str,
    namespace: str,
) -> str:
    """Return the completion panel title for the provider/namespace pair."""
    provider = result.provider_display if result is not None else ""
    if not provider:
        provider = workflow
    return f"{provider} · {namespace}/"


def _candidate(entry: VcsRepoEntry) -> CompletionCandidate:
    return CompletionCandidate(
        display=entry.name,
        insertion=entry.ref,
        is_dir=False,
        name=entry.name,
        metadata=entry,
    )


def _placeholder(
    kind: VcsRepoPlaceholderKind,
    message: str,
) -> CompletionCandidate:
    return CompletionCandidate(
        display=message,
        insertion="",
        is_dir=False,
        name="",
        metadata=VcsRepoCompletionPlaceholder(kind=kind, message=message),
    )


__all__ = [
    "VCS_REPO_COMPLETION_KIND",
    "VcsRepoCompletionPlaceholder",
    "build_loading_placeholder",
    "vcs_repo_completion_candidates",
    "vcs_repo_completion_title",
]
