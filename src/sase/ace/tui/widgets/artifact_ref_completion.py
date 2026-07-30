"""Stable facade for artifact-reference completion and catalog discovery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

from sase.artifact_refs import (
    ArtifactRefContext,
    at_reference_context,
    at_reference_inventory,
    at_reference_menu,
)
from sase.ace.tui.widgets import _artifact_ref_completion_catalog as _catalog
from sase.ace.tui.widgets import _artifact_ref_completion_context as _context
from sase.ace.tui.widgets import _artifact_ref_completion_menu as _menu
from sase.ace.tui.widgets._artifact_ref_completion_catalog import (
    read_cached_artifact_index,
)
from sase.ace.tui.widgets._artifact_ref_completion_menu import (
    ArtifactRefCompletionCatalog,
)
from sase.ace.tui.widgets._artifact_ref_completion_models import (
    ArtifactRefBugCandidate,
    ArtifactRefChatCandidate,
    ArtifactRefCommitCandidate,
    ArtifactRefCompletionContext,
    ArtifactRefCompletionResult,
    ArtifactRefCompletionStage,
    ArtifactRefDocumentCandidate,
    ArtifactRefFileCandidate,
    ArtifactRefKindCompletionMetadata,
    ArtifactRefLoadedCandidates,
    ArtifactRefPayloadCompletionMetadata,
    ArtifactRefPayloadSource,
    AtReferenceFileCompletionMetadata,
    AtReferenceLoadingCompletionMetadata,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_path_inventory import PromptPathRow


ARTIFACT_REF_COMPLETION_KIND = "artifact_ref"

_MAX_DOCUMENT_ROWS_PER_KIND = 5000
_MAX_ARTIFACT_FILE_ROWS = 5000
_MAX_CHAT_SCAN_ROWS = 5000
_MAX_CHAT_ROWS = 5000

# Keep the original private helper/cache names available to tests and local callers.
_ARTIFACT_INDEX_CACHE = _catalog._ARTIFACT_INDEX_CACHE
_ArtifactIndexCacheEntry = _catalog.ArtifactIndexCacheEntry
_SNAPSHOT_PAYLOAD_MEMOS = _menu._SNAPSHOT_PAYLOAD_MEMOS
_SnapshotPayloadMemo = _menu.SnapshotPayloadMemo
_ArtifactRefChatCandidate = ArtifactRefChatCandidate
_ArtifactRefDocumentCandidate = ArtifactRefDocumentCandidate
_ArtifactRefFileCandidate = ArtifactRefFileCandidate
_LoadedCandidates = ArtifactRefLoadedCandidates
_accepted_project_names = _catalog.accepted_project_names
_age_label = _menu.age_label
_artifact_ref_payload_panel_title = _context.artifact_ref_payload_panel_title
_document_kind_details = _catalog.document_kind_details
_kind_inventory = _menu.kind_inventory
_payload_rows = _menu.payload_rows
_wire_match_runs = _menu.wire_match_runs
_build_catalog_payload_memos = _menu.build_catalog_payload_memos
_index_payload_rows = _menu.index_payload_rows
_snapshot_payload_memo = _menu.snapshot_payload_memo


def at_reference_leading_match_count(
    candidates: Sequence[CompletionCandidate],
) -> int:
    """Count selectable rows in the menu's leading shared-core group."""
    return _context.at_reference_leading_match_count(candidates)


def detect_artifact_ref_completion_context(
    text: str,
    cursor_offset: int,
    known_kinds: Iterable[str] = (),
) -> ArtifactRefCompletionContext | None:
    """Map the shared Rust cursor policy into prompt-local context."""
    return _context.detect_artifact_ref_completion_context(
        text,
        cursor_offset,
        known_kinds,
        _context_detector=at_reference_context,
    )


def build_artifact_ref_completion_result(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    include_files: bool = False,
    commits: Sequence[ArtifactRefCommitCandidate] = (),
    bugs: Sequence[ArtifactRefBugCandidate] = (),
    paths: Sequence[PromptPathRow] = (),
    paths_loading: bool = False,
) -> ArtifactRefCompletionResult:
    """Map shared Rust menu rows onto prompt completion candidates."""
    return _menu.build_artifact_ref_completion_result(
        context,
        catalog,
        include_files=include_files,
        commits=commits,
        bugs=bugs,
        paths=paths,
        paths_loading=paths_loading,
        _menu_builder=at_reference_menu,
        _inventory_builder=at_reference_inventory,
        _payload_inventory_builder=_payload_inventory,
    )


def load_artifact_ref_completion_catalog(
    project: str | None,
    context: ArtifactRefContext,
) -> ArtifactRefCompletionCatalog:
    """Discover bounded payload rows; callers must run this off the UI thread."""
    return _catalog.load_artifact_ref_completion_catalog(
        project,
        context,
        max_document_rows_per_kind=_MAX_DOCUMENT_ROWS_PER_KIND,
        max_artifact_file_rows=_MAX_ARTIFACT_FILE_ROWS,
        max_chat_scan_rows=_MAX_CHAT_SCAN_ROWS,
        max_chat_rows=_MAX_CHAT_ROWS,
        read_artifact_index=_read_cached_artifact_index,
        load_document_candidates=_load_document_candidate_catalog,
        load_artifact_file_candidates=_load_artifact_file_candidate_catalog,
        load_chat_candidates=_load_chat_candidate_catalog,
    )


def _load_document_candidate_catalog(
    context: ArtifactRefContext,
) -> ArtifactRefLoadedCandidates[ArtifactRefDocumentCandidate]:
    return _catalog.load_document_candidate_catalog(
        context,
        max_rows_per_kind=_MAX_DOCUMENT_ROWS_PER_KIND,
    )


def _load_artifact_file_candidate_catalog(
    project: str | None,
    context: ArtifactRefContext,
) -> ArtifactRefLoadedCandidates[ArtifactRefFileCandidate]:
    return _catalog.load_artifact_file_candidate_catalog(
        project,
        context,
        max_rows=_MAX_ARTIFACT_FILE_ROWS,
        read_artifact_index=_read_cached_artifact_index,
    )


def _read_cached_artifact_index(index_path: Path) -> tuple[object, ...]:
    return read_cached_artifact_index(index_path)


def _load_chat_candidate_catalog(
    context: ArtifactRefContext,
) -> ArtifactRefLoadedCandidates[ArtifactRefChatCandidate]:
    return _catalog.load_chat_candidate_catalog(
        context,
        max_scan_rows=_MAX_CHAT_SCAN_ROWS,
        max_rows=_MAX_CHAT_ROWS,
    )


def _payload_inventory(
    context: ArtifactRefCompletionContext,
    catalog: ArtifactRefCompletionCatalog,
    *,
    commits: Sequence[ArtifactRefCommitCandidate],
    bugs: Sequence[ArtifactRefBugCandidate],
) -> tuple[
    list[dict[str, object]],
    object | None,
    Mapping[str, ArtifactRefPayloadCompletionMetadata],
    int,
]:
    return _menu.payload_inventory(
        context,
        catalog,
        commits=commits,
        bugs=bugs,
        inventory_builder=at_reference_inventory,
    )


__all__ = [
    "ARTIFACT_REF_COMPLETION_KIND",
    "AtReferenceFileCompletionMetadata",
    "AtReferenceLoadingCompletionMetadata",
    "ArtifactRefBugCandidate",
    "ArtifactRefCommitCandidate",
    "ArtifactRefCompletionCatalog",
    "ArtifactRefCompletionContext",
    "ArtifactRefCompletionResult",
    "ArtifactRefKindCompletionMetadata",
    "ArtifactRefPayloadCompletionMetadata",
    "at_reference_leading_match_count",
    "build_artifact_ref_completion_result",
    "detect_artifact_ref_completion_context",
    "load_artifact_ref_completion_catalog",
]
