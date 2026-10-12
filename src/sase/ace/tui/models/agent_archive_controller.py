"""Off-thread Archive corpus controller types for the Agents tab.

Corpus-controller seam for the Agents Archive epic (child epic
``sase-1jm.3.1``). Presentation state lives here; compile, matching,
counts, and lookup stay on the shared Rust-backed corpus handle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from collections.abc import Mapping

from .agent_archive_view import ARCHIVE_DEFAULT_GROUPING, ARCHIVE_DEFAULT_QUERY

ARCHIVE_CORPUS_COLD = "cold"
ARCHIVE_CORPUS_LOADING = "loading"
ARCHIVE_CORPUS_WARM = "warm"
ARCHIVE_CORPUS_MISSING = "missing"
ARCHIVE_CORPUS_UNREADABLE = "unreadable"
ARCHIVE_CORPUS_REBUILDING = "rebuilding"

ARCHIVE_REQUEST_PREWARM = "prewarm"
ARCHIVE_REQUEST_VIEW = "view"
ARCHIVE_REQUEST_QUERY = "query"
ARCHIVE_REQUEST_IDLE = "idle"

ARCHIVE_INDEX_UNAVAILABLE_MESSAGE = (
    "Archive index unavailable — sase agent archive rebuild-index"
)


@dataclass(frozen=True)
class ArchiveRevalidationTokens:
    """Cheap signatures compared on idle ticks. No bundle or catalog scan."""

    index_exists: bool
    index_stat: tuple[int, int] | None
    link_signature: tuple[tuple[str, int | None, int | None], ...]
    profile_digest: str
    rebuilding: bool
    indexed_rows: int


@dataclass(frozen=True)
class ArchivePageWindow:
    """One banner-local page request against the warm corpus handle."""

    group_key: str
    offset: int
    limit: int


@dataclass(frozen=True)
class ArchiveLoadedWindow:
    """One queried page currently published to Archive consumers."""

    group_key: str
    offset: int
    limit: int
    rows: tuple[Mapping[str, Any], ...]
    total: int


@dataclass(frozen=True)
class ArchiveInboxPulse:
    """Live Inbox counts for the Archive pulse. Never loads extra agents."""

    total: int = 0
    running: int = 0
    waiting: int = 0
    unread: int = 0
    attention: int = 0


@dataclass(frozen=True)
class ArchiveRequestSnapshot:
    """Immutable last-request-wins work item. UI callbacks never mutate it."""

    generation: int
    kind: str
    query: str
    grouping: str
    windows: tuple[ArchivePageWindow, ...]
    expanded_containers: tuple[str, ...]
    selected_key: str | None
    view: str
    previous_identities: tuple[str, ...]
    link_facets: Mapping[str, Any] | None
    tokens: ArchiveRevalidationTokens | None
    corpus: Any = None
    profile: Any = None
    pending_exact_name: str | None = None


@dataclass(frozen=True)
class ArchiveCorpusSnapshot:
    """Published controller snapshot for later Archive and parent consumers."""

    status: str
    generation: int
    error_message: str | None
    indexed_rows: int
    refreshing: bool
    summary: Mapping[str, Any] | None
    windows: tuple[ArchiveLoadedWindow, ...]
    identities: tuple[str, ...]
    count: int
    query: str
    grouping: str
    tokens: ArchiveRevalidationTokens | None
    warm: bool
    applied_query: str | None = None
    applied_grouping: str | None = None
    applied_expanded: tuple[str, ...] = ()
    timezone: str = ""
    requested_windows: tuple[ArchivePageWindow, ...] = ()
    display_snapshot: Any = None


@dataclass
class AgentsArchiveControllerState:
    """Mutable controller state owned by the TUI app."""

    generation: int = 0
    inbox_complete_applied: bool = False
    prewarm_started: bool = False
    prewarm_pending: bool = False
    explicit_open_queued: bool = False
    inbox_load_scheduled: bool = False
    idle_in_flight: bool = False
    idle_coalesced: bool = False
    status: str = ARCHIVE_CORPUS_COLD
    error_message: str | None = None
    indexed_rows: int = 0
    refreshing: bool = False
    corpus: Any = None
    profile: Any = None
    link_facets: Mapping[str, Any] | None = None
    tokens: ArchiveRevalidationTokens | None = None
    summary: Mapping[str, Any] | None = None
    windows: tuple[ArchiveLoadedWindow, ...] = ()
    identities: tuple[str, ...] = ()
    count: int = 0
    pulse: ArchiveInboxPulse = field(default_factory=ArchiveInboxPulse)
    last_windows: tuple[ArchivePageWindow, ...] = ()
    last_query: str = ARCHIVE_DEFAULT_QUERY
    last_grouping: str = ARCHIVE_DEFAULT_GROUPING
    last_expanded: tuple[str, ...] = ()
    applied_query: str | None = None
    applied_grouping: str | None = None
    applied_expanded: tuple[str, ...] = ()
    display_snapshot: Any = None


def startup_agents_archive_controller_state() -> AgentsArchiveControllerState:
    """Return a cold controller. Nothing is probed until the Inbox gate opens."""
    return AgentsArchiveControllerState()


def preserve_archive_selected_key(
    previous_identities: tuple[str, ...],
    selected_key: str | None,
    new_identities: tuple[str, ...],
) -> str | None:
    """Keep a stable identity, else the nearest still-valid neighbor."""
    if selected_key is not None and selected_key in new_identities:
        return selected_key
    if not new_identities:
        return None
    if selected_key is None or selected_key not in previous_identities:
        return new_identities[0]
    new_set = set(new_identities)
    idx = previous_identities.index(selected_key)
    for candidate in previous_identities[idx + 1 :]:
        if candidate in new_set:
            return candidate
    for candidate in reversed(previous_identities[:idx]):
        if candidate in new_set:
            return candidate
    return new_identities[0]


__all__ = [
    "ARCHIVE_CORPUS_COLD",
    "ARCHIVE_CORPUS_LOADING",
    "ARCHIVE_CORPUS_MISSING",
    "ARCHIVE_CORPUS_REBUILDING",
    "ARCHIVE_CORPUS_UNREADABLE",
    "ARCHIVE_CORPUS_WARM",
    "ARCHIVE_INDEX_UNAVAILABLE_MESSAGE",
    "ARCHIVE_REQUEST_IDLE",
    "ARCHIVE_REQUEST_PREWARM",
    "ARCHIVE_REQUEST_QUERY",
    "ARCHIVE_REQUEST_VIEW",
    "AgentsArchiveControllerState",
    "ArchiveCorpusSnapshot",
    "ArchiveInboxPulse",
    "ArchiveLoadedWindow",
    "ArchivePageWindow",
    "ArchiveRequestSnapshot",
    "ArchiveRevalidationTokens",
    "preserve_archive_selected_key",
    "startup_agents_archive_controller_state",
]
