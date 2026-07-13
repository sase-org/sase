"""Prompt-bar candidate building for the ``+`` VCS project/PR completion menu.

This is the thin TUI bridge between the headless Phase-1 helpers in
:mod:`sase.xprompt.vcs_project_completion` (catalog, trigger detection, the
canonical expansion transform) and the prompt input bar's
:class:`~sase.ace.tui.widgets.file_completion.CompletionCandidate` machinery.

The accept path expands the *whole* prompt via
:func:`~sase.xprompt.vcs_project_completion.apply_vcs_project_selection`, so a
candidate's ``insertion`` is the entry's ``display_tag`` for display only -- it
is never used as a token-local replacement.
"""

from __future__ import annotations

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.xprompt.vcs_project_completion import (
    VcsProjectEntry,
    build_vcs_project_completion_entries,
    filter_vcs_project_entries,
)

VCS_PROJECT_COMPLETION_KIND = "vcs_project"
"""``_completion_kind`` value identifying the ``+`` project/PR menu."""

_NO_ACTIVE_PROJECTS_LABEL = "no enabled projects or PRs"
"""Placeholder row text shown when the enabled project/PR catalog is empty."""


def build_no_active_projects_placeholder() -> CompletionCandidate:
    """Return the single dim placeholder row for an empty project/PR catalog.

    The placeholder carries ``metadata=None`` so the accept path recognizes it
    as non-selectable (accepting it is a no-op dismiss) and the renderer styles
    it dim.
    """
    return CompletionCandidate(
        display=_NO_ACTIVE_PROJECTS_LABEL,
        insertion="",
        is_dir=False,
        name="",
        metadata=None,
    )


def _candidate(entry: VcsProjectEntry) -> CompletionCandidate:
    """Build one completion candidate from a project/PR *entry*."""
    return CompletionCandidate(
        display=entry.name,
        insertion=entry.display_tag,
        is_dir=False,
        name=entry.name,
        metadata=entry,
    )


def vcs_project_completion_candidates(
    query: str,
    *,
    entries: list[VcsProjectEntry] | None = None,
) -> tuple[list[CompletionCandidate], bool]:
    """Return ``(candidates, catalog_is_empty)`` for *query*.

    ``catalog_is_empty`` is ``True`` only when there are *zero* enabled project
    or PR entries, so the caller shows the
    :func:`build_no_active_projects_placeholder` row rather than dismissing the
    menu. When the catalog is non-empty but *query* filters everything out,
    ``candidates`` is empty and ``catalog_is_empty`` is ``False`` (the caller
    dismisses).

    The catalog build is cached by :mod:`sase.xprompt.vcs_project_completion`, so
    this stays cheap on the keystroke path once warmed.

    Args:
        query: The filter text after the ``+`` (empty matches all entries).
        entries: Pre-built catalog to filter; built lazily (cached) when omitted.
    """
    source = entries if entries is not None else build_vcs_project_completion_entries()
    if not source:
        return [], True
    return [_candidate(entry) for entry in filter_vcs_project_entries(source, query)], (
        False
    )


__all__ = [
    "VCS_PROJECT_COMPLETION_KIND",
    "build_no_active_projects_placeholder",
    "vcs_project_completion_candidates",
]
