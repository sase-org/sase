"""Commit-message helpers for folding memory edits into init commits."""

from __future__ import annotations

from sase.core.commit_subject_facade import parse_commit_subject
from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

from .constants import MEMORY_FOLD_DEFAULT_PREFIX


def _is_conventional_header(subject: str) -> bool:
    """Return whether ``subject`` already starts with an allowed header."""
    return parse_commit_subject(subject).valid


def _compose_fold_subject(
    subject: str, default_prefix: str = MEMORY_FOLD_DEFAULT_PREFIX
) -> str:
    """Return the fold subject, adding the default prefix when needed."""
    cleaned = subject.strip()
    if _is_conventional_header(cleaned):
        return cleaned
    return f"{default_prefix}{cleaned}"


def build_fold_commit_message(subject: str) -> str:
    """Return the full fold commit message with the memory provenance footer."""
    return apply_auto_commit_type_tag(_compose_fold_subject(subject), "memory")
