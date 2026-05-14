"""Shared provider contract for ACE read surfaces.

The Textual widgets still consume the existing full-list models today.  This
module gives daemon-backed and direct providers one common vocabulary for the
incremental migration: stable row handles, snapshot/page metadata, fallback
reasons, deltas, and selection generations for future lazy detail loads.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .util.trace import trace_event


@dataclass(frozen=True)
class AceProviderCapabilities:
    """Capabilities a provider can use for a surface."""

    pages: bool = False
    deltas: bool = False
    lazy_details: bool = False
    counts: bool = False


@dataclass(frozen=True)
class AceFallbackMetadata:
    """Reason a provider used direct fallback instead of daemon reads."""

    reason: str | None = None
    message: str | None = None

    @property
    def used_fallback(self) -> bool:
        return self.reason is not None


@dataclass(frozen=True)
class AceProviderInfo:
    """Provider identity and source metadata for traces and tests."""

    identity: str
    surface: str
    source: str
    prefers_daemon: bool
    capabilities: AceProviderCapabilities = field(
        default_factory=AceProviderCapabilities
    )
    fallback: AceFallbackMetadata = field(default_factory=AceFallbackMetadata)


@dataclass(frozen=True)
class AceRowHandle:
    """Stable row identity shared by daemon and direct providers."""

    surface: str
    stable_id: str
    daemon_handle: str | None = None
    local_identity: str | None = None


@dataclass(frozen=True)
class AcePage[T]:
    """One provider page. Direct providers may expose their full list as page 1."""

    rows: list[T] = field(default_factory=list)
    row_handles: list[AceRowHandle] = field(default_factory=list)
    cursor: str | None = None
    next_cursor: str | None = None
    requested_start: int | None = None
    requested_limit: int | None = None
    query: str | None = None
    estimated_total: int | None = None
    bounded: bool = False
    truncated: bool = False


@dataclass(frozen=True)
class AceSnapshot[T]:
    """Provider snapshot for a single ACE surface."""

    surface: str
    schema_version: int
    snapshot_id: str | None
    generation_id: int
    total_count: int | None
    provider: AceProviderInfo
    first_page: AcePage[T]
    facets: Mapping[str, Any] = field(default_factory=dict)
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def rows(self) -> list[T]:
        return self.first_page.rows

    @property
    def row_handles(self) -> list[AceRowHandle]:
        return self.first_page.row_handles


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
@dataclass(frozen=True)
class AceCountPatch:
    """Count/facet patch carried by a delta batch."""

    key: str
    value: int


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
@dataclass(frozen=True)
class AceRowPatch[T]:
    """A row-level delta operation."""

    operation: str
    handle: AceRowHandle
    row: T | None = None
    index: int | None = None


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
@dataclass(frozen=True)
class AceDeltaBatch[T]:
    """Batch of row/count updates tied to a provider snapshot."""

    surface: str
    snapshot_id: str | None
    sequence: int | None
    row_patches: list[AceRowPatch[T]] = field(default_factory=list)
    count_patches: list[AceCountPatch] = field(default_factory=list)
    facet_patches: Mapping[str, Any] = field(default_factory=dict)
    invalidation_reason: str | None = None
    resync_hint: str | None = None

    @property
    def requires_resync(self) -> bool:
        return self.invalidation_reason is not None or self.resync_hint is not None


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
@dataclass(frozen=True)
class AceDetailRequest:
    """Lazy detail request guarded by the active selection generation."""

    row_handle: AceRowHandle
    selection_generation: int


# pyvision: sdd/epics/202605/rust_daemon_epic9_ace_ui_virtualization.md
class SelectionGeneration:
    """Monotonic generation used to ignore stale lazy detail responses."""

    def __init__(self) -> None:
        self._value = 0

    @property
    def current(self) -> int:
        return self._value

    def bump(self) -> int:
        self._value += 1
        return self._value

    def request(self, row_handle: AceRowHandle) -> AceDetailRequest:
        return AceDetailRequest(row_handle, self._value)

    def accepts(self, request: AceDetailRequest) -> bool:
        return request.selection_generation == self._value


def make_snapshot[T](
    *,
    surface: str,
    rows: Sequence[T],
    row_handles: Sequence[AceRowHandle],
    provider: AceProviderInfo,
    snapshot_id: str | None = None,
    generation_id: int = 0,
    page_count: int = 1,
    next_cursor: str | None = None,
    total_count: int | None = None,
    facets: Mapping[str, Any] | None = None,
    metadata: Mapping[str, Any] | None = None,
    full_reload: bool = True,
) -> AceSnapshot[T]:
    """Build a snapshot from current provider rows without widget coupling."""

    rows_list = rows if isinstance(rows, list) else list(rows)
    handle_list = list(row_handles)
    snapshot = AceSnapshot(
        surface=surface,
        schema_version=1,
        snapshot_id=snapshot_id,
        generation_id=generation_id,
        total_count=len(rows_list) if total_count is None else total_count,
        provider=provider,
        first_page=AcePage(
            rows=rows_list,
            row_handles=handle_list,
            next_cursor=next_cursor,
            requested_start=0,
            requested_limit=len(rows_list),
            estimated_total=len(rows_list) if total_count is None else total_count,
        ),
        facets=dict(facets or {}),
        metadata={
            "page_count": page_count,
            "full_reload": full_reload,
            **dict(metadata or {}),
        },
    )
    return snapshot


def trace_provider_snapshot(snapshot: AceSnapshot[Any]) -> None:
    """Emit provider metadata without putting daemon wire dictionaries in widgets."""

    trace_event(
        "ace.provider_snapshot",
        surface=snapshot.surface,
        provider_source=snapshot.provider.source,
        provider_identity=snapshot.provider.identity,
        snapshot_id=snapshot.snapshot_id,
        page_count=snapshot.metadata.get("page_count", 1),
        fallback_reason=snapshot.provider.fallback.reason,
        full_reload=bool(snapshot.metadata.get("full_reload", False)),
        row_count=len(snapshot.rows),
    )


__all__ = [
    "AceCountPatch",
    "AceDeltaBatch",
    "AceDetailRequest",
    "AceFallbackMetadata",
    "AcePage",
    "AceProviderCapabilities",
    "AceProviderInfo",
    "AceRowHandle",
    "AceRowPatch",
    "AceSnapshot",
    "SelectionGeneration",
    "make_snapshot",
    "trace_provider_snapshot",
]
