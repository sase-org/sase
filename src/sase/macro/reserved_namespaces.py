"""Shared xprompt namespace reservation checks."""

from __future__ import annotations

from pathlib import Path

from sase.content_layout import reserved_memory_namespace_issue

from .load_issues import record_load_issue

RESERVED_MEMORY_NAMESPACE_ISSUE_KIND = "reserved_memory_namespace"


def reject_reserved_memory_namespace(
    reference: str,
    *,
    source: Path | str,
) -> bool:
    """Return whether an ordinary definition illegally claims ``memory/``."""
    issue = reserved_memory_namespace_issue(source, reference)
    if issue is None:
        return False
    record_load_issue(
        issue.source, issue.message, kind=RESERVED_MEMORY_NAMESPACE_ISSUE_KIND
    )
    return True


__all__ = [
    "RESERVED_MEMORY_NAMESPACE_ISSUE_KIND",
    "reject_reserved_memory_namespace",
]
