"""Data models for artifact panel navigation state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactRelationPageWire,
    ArtifactTypeCountWire,
)


ARTIFACT_PANEL_GROUP_PAGE_SIZE = 10
ARTIFACT_PANEL_GLOBAL_SEARCH_LIMIT = 25
ARTIFACT_PANEL_SHOW_MORE_ACTION = "show_more"
ArtifactPanelErrorOperation = Literal["load", "search", "page", "render"]


@dataclass(frozen=True)
class ArtifactPanelErrorSummary:
    """User-facing classification for recoverable artifact-panel failures."""

    title: str
    message: str
    style: str = "red"
    recoverable: bool = False


@dataclass(frozen=True)
class ArtifactPanelRow:
    """One row rendered in the artifact panel navigation list."""

    id: str
    label: str
    artifact_id: str | None = None
    artifact_kind: str | None = None
    file_type: str | None = None
    edge_direction: str | None = None
    link_type: str | None = None
    title: str = ""
    subtitle: str = ""
    updated_label: str = ""
    group_key: str | None = None
    page_action: str | None = None
    row_type: str = "artifact"
    group: str | None = None
    status_label: str = ""
    selectable: bool = True


@dataclass
class ArtifactPanelRows:
    rows: list[ArtifactPanelRow]
    total_selectable: int
    truncated: bool = False


@dataclass(frozen=True)
class ArtifactPanelRelationPageKey:
    """Stable key for one loaded relationship page in the modal."""

    group_key: str
    relation: str
    link_type: str | None = None


@dataclass
class ArtifactPanelPagedModel:
    """Paged artifact detail plus a legacy projection for current renderers."""

    paged_detail: ArtifactDetailPagedWire
    detail: ArtifactDetailWire
    relation_pages: dict[ArtifactPanelRelationPageKey, ArtifactRelationPageWire] = (
        field(default_factory=dict)
    )
    group_offsets: dict[ArtifactPanelRelationPageKey, int] = field(default_factory=dict)
    group_totals: dict[ArtifactPanelRelationPageKey, int] = field(default_factory=dict)


@dataclass(frozen=True)
class ArtifactRelationshipContext:
    """Compact relationship summary for detail-pane rendering."""

    link_type: str
    loaded_count: int
    total_count: int
    peer_labels: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArtifactDetailRenderContext:
    """Already-loaded relationship context available to detail renderers."""

    parent_label: str | None = None
    path_labels: tuple[str, ...] = ()
    children_loaded_count: int = 0
    children_total_count: int = 0
    child_labels: tuple[str, ...] = ()
    outbound: tuple[ArtifactRelationshipContext, ...] = ()
    inbound: tuple[ArtifactRelationshipContext, ...] = ()
    type_counts: tuple[ArtifactTypeCountWire, ...] = ()


@dataclass
class ArtifactPanelNavigationState:
    current_id: str
    back_stack: list[str] = field(default_factory=list)
    forward_stack: list[str] = field(default_factory=list)
    selected_row_id: str | None = None
    filter_text: str = ""
    detail: ArtifactDetailWire | None = None
    paged_model: ArtifactPanelPagedModel | None = None

    def navigate_to(self, artifact_id: str) -> bool:
        """Move to *artifact_id*, returning whether a fresh load is needed."""
        if artifact_id == self.current_id:
            return False
        self.back_stack.append(self.current_id)
        self.current_id = artifact_id
        self.forward_stack.clear()
        self.selected_row_id = None
        self.detail = None
        self.paged_model = None
        return True

    def back(self) -> str | None:
        if not self.back_stack:
            return None
        previous = self.back_stack.pop()
        self.forward_stack.append(self.current_id)
        self.current_id = previous
        self.selected_row_id = None
        self.detail = None
        self.paged_model = None
        return previous

    def forward(self) -> str | None:
        if not self.forward_stack:
            return None
        next_id = self.forward_stack.pop()
        self.back_stack.append(self.current_id)
        self.current_id = next_id
        self.selected_row_id = None
        self.detail = None
        self.paged_model = None
        return next_id

    def set_filter(self, filter_text: str) -> None:
        self.filter_text = filter_text.strip()
        self.selected_row_id = None

    def set_detail(self, detail: ArtifactDetailWire) -> None:
        self.detail = detail

    def set_paged_model(self, model: ArtifactPanelPagedModel) -> None:
        self.paged_model = model
        self.detail = model.detail


def classify_artifact_panel_error(
    error: BaseException | str | None,
    *,
    operation: ArtifactPanelErrorOperation,
) -> ArtifactPanelErrorSummary:
    """Return concise, stable UI copy for common artifact backend failures."""
    raw = str(error or f"Unknown artifact {operation} error").strip()
    if not raw:
        raw = f"Unknown artifact {operation} error"
    normalized = raw.casefold()

    if _looks_like_sqlite_busy(normalized):
        return ArtifactPanelErrorSummary(
            title="Artifact index busy",
            message=(
                f"The artifact index is busy or locked. Try again shortly.\n{raw}"
            ),
            style="yellow",
            recoverable=True,
        )
    if _looks_like_sqlite_readonly(normalized):
        return ArtifactPanelErrorSummary(
            title="Artifact index read-only",
            message=(
                "The artifact index is read-only or cannot be opened for this "
                f"operation.\n{raw}"
            ),
            style="yellow",
            recoverable=True,
        )
    if _looks_like_sqlite_read_failure(normalized):
        return ArtifactPanelErrorSummary(
            title="Artifact index read failed",
            message=f"The artifact index could not be read.\n{raw}",
            style="red",
            recoverable=True,
        )

    return ArtifactPanelErrorSummary(
        title=f"Artifact {operation} failed",
        message=raw,
        style="red",
        recoverable=False,
    )


def _looks_like_sqlite_busy(normalized: str) -> bool:
    busy_fragments = (
        "sqlite_busy",
        "sqlite locked",
        "sqlite_locked",
        "database is busy",
        "database busy",
        "database is locked",
        "database table is locked",
        "busy timeout",
        "database locked",
        "sqlite error 5",
        "sqlite error 6",
    )
    return any(fragment in normalized for fragment in busy_fragments)


def _looks_like_sqlite_readonly(normalized: str) -> bool:
    readonly_fragments = (
        "readonly database",
        "read-only database",
        "read only database",
        "attempt to write a readonly database",
        "attempt to write a read-only database",
        "sqlite_readonly",
    )
    return any(fragment in normalized for fragment in readonly_fragments)


def _looks_like_sqlite_read_failure(normalized: str) -> bool:
    read_fragments = (
        "disk i/o error",
        "unable to open database file",
        "database disk image is malformed",
        "file is not a database",
        "not a database",
        "sqlite_ioerr",
        "sqlite_corrupt",
        "sqlite_notadb",
    )
    return any(fragment in normalized for fragment in read_fragments)
