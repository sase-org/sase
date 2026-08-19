"""Data models shared by artifact-reference completion modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.prompt_commit_inventory import ArtifactRefCommitRow


ArtifactRefCompletionStage = Literal["kind", "payload"]
ArtifactRefPayloadSource = Literal[
    "document",
    "file",
    "commit",
    "bug",
    "bead",
    "agent",
]


@dataclass(frozen=True, slots=True)
class ArtifactRefCompletionContext:
    """Artifact-reference token and replacement span at one cursor."""

    replacement_start: int
    replacement_end: int
    stage: ArtifactRefCompletionStage
    partial_kind: str
    partial_payload: str
    kind: str | None
    panel_title: str
    path_directory: str | None = None
    path_partial: str = ""
    query_start: int = 0
    query_end: int = 0
    wire: dict[str, object] | None = None

    @property
    def prefix(self) -> str:
        """Return the stage-local text used to filter candidates."""
        return self.partial_kind if self.stage == "kind" else self.partial_payload


@dataclass(frozen=True, slots=True)
class ArtifactRefKindCompletionMetadata:
    """Metadata for one builtin or project-defined artifact kind."""

    kind: str
    builtin: bool
    detail: str = ""
    label_match: tuple[tuple[int, int], ...] = ()
    match_tier: int = 0

    @property
    def source_label(self) -> str:
        return self.detail or ("builtin" if self.builtin else "document")


@dataclass(frozen=True, slots=True)
class ArtifactRefPayloadCompletionMetadata:
    """Metadata rendered beside one artifact payload candidate."""

    kind: str
    payload: str
    source: ArtifactRefPayloadSource
    label: str = ""
    detail: str = ""
    age: str = ""
    scope: str = ""
    rank: int | None = None
    body: str = ""
    label_match: tuple[tuple[int, int], ...] = ()
    title_match: tuple[tuple[int, int], ...] = ()
    match_tier: int = 0
    is_new: bool = False


@dataclass(frozen=True, slots=True)
class ArtifactRefSyncCompletionMetadata:
    """Non-selectable pinned row showing ``@<kind>::`` sync status.

    ``phase`` is one of ``running``/``settled_ok``/``settled_error``.
    """

    kind: str
    phase: str
    label: str
    detail: str = ""
    frame: int = 0


@dataclass(frozen=True, slots=True)
class AtReferenceFileCompletionMetadata:
    """Metadata for one local path row in the shared ``@`` menu."""

    is_dir: bool
    directory: str
    label_match: tuple[tuple[int, int], ...] = ()
    match_tier: int = 0


@dataclass(frozen=True, slots=True)
class AtReferenceLoadingCompletionMetadata:
    """Non-selectable row shown while a local path snapshot is cold."""


@dataclass(frozen=True, slots=True)
class ArtifactRefDocumentCandidate:
    kind: str
    payload: str
    title: str = ""
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactRefFileCandidate:
    payload: str
    label: str
    file_kind: str
    created_at: str = ""


ArtifactRefCommitCandidate = ArtifactRefCommitRow


@dataclass(frozen=True, slots=True)
class ArtifactRefBugCandidate:
    project: str
    number: int
    title: str = ""
    updated_at: str = ""

    @property
    def payload(self) -> str:
        return f"{self.project}#{self.number}"


@dataclass(frozen=True, slots=True)
class ArtifactRefCompletionResult:
    """Candidates and shared extension for one detected context."""

    context: ArtifactRefCompletionContext
    candidates: list[CompletionCandidate]
    shared_extension: str
    payload_count: int = 0
    payload_total: int = 0
    truncated_payloads: int = 0
    files_suppressed: bool = False


@dataclass(frozen=True, slots=True)
class ArtifactRefLoadedCandidates[CandidateT]:
    rows: tuple[CandidateT, ...]
    truncated_by_kind: tuple[tuple[str, int], ...] = ()
