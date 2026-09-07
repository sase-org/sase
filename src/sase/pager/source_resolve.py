"""Owner-aware source-path lookup for pager file links.

Selection and repository identity stay in Rust
(``resolve_document_source_target``). This module adapts pager context to
that wire and turns outcomes into diagnostics the UI can show without a
second search.
"""

from __future__ import annotations

from pathlib import Path

from sase.artifact_ref_models import ArtifactRefTargetResolution
from sase.artifact_ref_operations import resolve_document_source_target
from sase.pager.link_context import LinkResolutionContext
from sase.pager.owner import artifact_context_for_link_context

_SUCCESS_STATUSES = frozenset({"exact", "drifted"})
_RETRYABLE_FAILURES = frozenset(
    {"missing_checkout", "temporary_error", "unavailable_revision"}
)


def lookup_owned_source_path(
    path_text: str,
    *,
    context: LinkResolutionContext | None,
) -> ArtifactRefTargetResolution | None:
    """Resolve *path_text* in the document's owning repositories.

    Returns ``None`` when there is no recoverable owner, so the caller
    keeps ordinary cwd-relative search. A returned resolution is the one
    lookup for this press; do not search again to rebuild a toast.
    """
    if context is None or context.owner is None:
        return None
    artifact_context = artifact_context_for_link_context(context)
    if artifact_context is None:
        return None
    try:
        return resolve_document_source_target(
            path_text,
            owner=context.owner,
            context=artifact_context,
        )
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return None


def owned_source_is_success(resolution: ArtifactRefTargetResolution) -> bool:
    """Return whether *resolution* selected a concrete path."""
    return (
        resolution.status in _SUCCESS_STATUSES and resolution.resolved_path is not None
    )


def owned_source_is_retryable(resolution: ArtifactRefTargetResolution) -> bool:
    """Return whether a later reload or retry may succeed."""
    if resolution.retryable:
        return True
    return resolution.failure_category in _RETRYABLE_FAILURES


def owned_source_unresolved_message(
    path_text: str,
    resolution: ArtifactRefTargetResolution,
) -> str:
    """Return worker-computed copy for a failed owned-source lookup."""
    if resolution.diagnostic:
        return resolution.diagnostic
    if resolution.status == "ambiguous" or resolution.failure_category == "ambiguous":
        names = [
            candidate.path
            if candidate.repository is None
            else f"{candidate.repository}:{candidate.path}"
            for candidate in resolution.candidates
        ]
        listed = ", ".join(names) if names else "multiple repositories"
        return f"{path_text} is ambiguous ({listed})"
    if resolution.failure_category == "missing_checkout":
        return f"{path_text} checkout is unavailable"
    if resolution.failure_category == "unavailable_revision":
        return f"{path_text} revision is unavailable"
    if resolution.failure_category == "denied_filtered":
        return f"{path_text} is not accessible"
    if resolution.failure_category == "temporary_error":
        return f"{path_text} lookup failed temporarily"
    return f"{path_text} not found"


def owned_source_candidate_paths(
    resolution: ArtifactRefTargetResolution,
) -> tuple[Path, ...]:
    """Return concrete candidate files the user can follow after ambiguity."""
    paths: list[Path] = []
    seen: set[Path] = set()
    for candidate in resolution.candidates:
        path = Path(candidate.path)
        if not path.is_absolute():
            continue
        try:
            resolved = path.expanduser().resolve(strict=False)
        except OSError:
            continue
        if resolved in seen or not resolved.exists():
            continue
        seen.add(resolved)
        paths.append(resolved)
    return tuple(paths)


__all__ = [
    "lookup_owned_source_path",
    "owned_source_candidate_paths",
    "owned_source_is_retryable",
    "owned_source_is_success",
    "owned_source_unresolved_message",
]
