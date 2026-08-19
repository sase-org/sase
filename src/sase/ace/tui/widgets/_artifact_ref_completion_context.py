"""Cursor-context detection and shared-menu grouping helpers."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any

from sase.artifact_refs import at_reference_context
from sase.ace.tui.widgets._artifact_ref_completion_models import (
    ArtifactRefCompletionContext,
    ArtifactRefSyncCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate


_NON_SELECTABLE_ARTIFACT_REF_METADATA = (
    AtReferenceLoadingCompletionMetadata,
    ArtifactRefSyncCompletionMetadata,
)


def at_reference_leading_match_count(
    candidates: Sequence[CompletionCandidate],
) -> int:
    """Count selectable rows in the menu's leading shared-core group."""
    if not candidates:
        return 0
    first_metadata = candidates[0].metadata
    if isinstance(
        first_metadata,
        (AtReferenceLoadingCompletionMetadata, ArtifactRefSyncCompletionMetadata),
    ):
        return 0
    first_group = type(first_metadata)
    count = 0
    for candidate in candidates:
        if type(candidate.metadata) is not first_group:
            break
        count += 1
    return count


def artifact_ref_first_selectable_index(
    candidates: Sequence[CompletionCandidate],
) -> int:
    """Return the first selectable row, skipping pinned status rows."""
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate.metadata, _NON_SELECTABLE_ARTIFACT_REF_METADATA):
            return index
    return 0


def artifact_ref_next_selectable_index(
    candidates: Sequence[CompletionCandidate],
    current: int,
    delta: int,
) -> int:
    """Step *current* by *delta*, wrapping past pinned status rows.

    Bounded to one lap so a menu with only non-selectable rows (e.g. a lone
    sync status row) leaves the index unchanged instead of spinning.
    """
    size = len(candidates)
    if size == 0:
        return current
    index = current
    for _ in range(size):
        index = (index + delta) % size
        if not isinstance(
            candidates[index].metadata,
            _NON_SELECTABLE_ARTIFACT_REF_METADATA,
        ):
            return index
    return current


def detect_artifact_ref_completion_context(
    text: str,
    cursor_offset: int,
    known_kinds: Iterable[str] = (),
    *,
    _context_detector: Callable[
        [str, int, Iterable[str]],
        dict[str, Any] | None,
    ] = at_reference_context,
) -> ArtifactRefCompletionContext | None:
    """Map the shared Rust cursor policy into prompt-local context."""
    raw = _context_detector(text, cursor_offset, known_kinds)
    if raw is None:
        return None
    stage = str(raw["stage"])
    candidate_start, candidate_end = (int(value) for value in raw["candidate_span"])
    query_start, query_end = (int(value) for value in raw["query_span"])
    query = str(raw["query"])
    kind_value = raw.get("kind")
    kind = None if kind_value is None else str(kind_value)
    path_query = raw.get("path_query")
    path_directory: str | None = None
    path_partial = ""
    if isinstance(path_query, dict):
        path_directory = str(path_query.get("directory", ""))
        path_partial = str(path_query.get("partial", ""))
    return ArtifactRefCompletionContext(
        replacement_start=candidate_start,
        replacement_end=candidate_end,
        stage="kind" if stage == "kind" else "payload",
        partial_kind=query if stage == "kind" else (kind or ""),
        partial_payload=query if stage == "payload" else "",
        kind=kind,
        panel_title=(
            "artifact kinds"
            if stage == "kind"
            else artifact_ref_payload_panel_title(kind or "")
        ),
        path_directory=path_directory,
        path_partial=path_partial,
        query_start=query_start,
        query_end=query_end,
        wire=raw,
    )


def artifact_ref_payload_panel_title(kind: str) -> str:
    """Return the shared panel title for one resolved payload provider."""
    folded = kind.casefold()
    if folded == "file":
        return "file: artifacts"
    if folded == "commit":
        return "commit: commits"
    if folded == "bug":
        return "bug: bugs"
    if folded == "bead":
        return "bead: beads"
    if folded == "agent":
        return "agent: agents"
    return f"{kind}: documents"
