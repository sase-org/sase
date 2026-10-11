"""Typed Agents-tab Archive view state, selection, and detail ownership.

View-foundation seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
Presentation state lives here in Python; outcome classification, timestamps,
root/container identity, membership, order, matching, counts, and exact lookup
stay in the existing Rust-backed corpus. Only grouping persists across launches;
every other field is per-process parked state. Startup is always Inbox.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

AGENTS_VIEW_INBOX = "inbox"
AGENTS_VIEW_ARCHIVE = "archive"

ARCHIVE_DEFAULT_QUERY = "in:archive"
ARCHIVE_DEFAULT_GROUPING = "day"

ARCHIVE_ROW_AGENT = "agent"
ARCHIVE_ROW_NONE = "none"

ARCHIVE_STATUS_OPENED = "opened"
ARCHIVE_STATUS_ALREADY_OPEN = "already_open"
ARCHIVE_STATUS_DISABLED = "disabled"
ARCHIVE_STATUS_RETURNED = "returned"
ARCHIVE_STATUS_ALREADY_INBOX = "already_inbox"


@dataclass
class ArchiveViewState:
    """Committed Archive presentation state. Only ``grouping`` persists."""

    committed_query: str = ARCHIVE_DEFAULT_QUERY
    grouping: str = ARCHIVE_DEFAULT_GROUPING
    expanded_banners: tuple[str, ...] = ()
    expanded_containers: tuple[str, ...] = ()
    loaded_pages: dict[str, int] = field(default_factory=dict)
    selected_key: str | None = None
    pending_exact_name: str | None = None
    scroll: int = 0
    focused_section: str = "list"
    deck_choices: dict[str, str] = field(default_factory=dict)
    marks: frozenset[str] = frozenset()


@dataclass
class ParkedInboxState:
    """Inbox state parked while the Archive owns the Agents tab."""

    committed_query: str = ""
    selected_identity: Any = None
    scroll: int = 0
    agent_tab: str | None = None
    panel_focus: str | None = None
    deck_choices: dict[str, str] = field(default_factory=dict)
    folds: tuple[str, ...] = ()


@dataclass
class AgentsArchiveViewState:
    """Lifecycle state for the Agents tab's Inbox/Archive views."""

    active_view: str = AGENTS_VIEW_INBOX
    generation: int = 0
    archive: ArchiveViewState = field(default_factory=ArchiveViewState)
    parked_inbox: ParkedInboxState | None = None


@dataclass(frozen=True)
class DetailOwnership:
    """View-owned render token guarding the shared detail panel."""

    view: str
    generation: int
    selection_key: str | None = None


@dataclass(frozen=True)
class AgentsTabSelection:
    """Typed Agents-tab selection.

    A banner, pulse, loading row, or page tail is not an agent: those resolve
    to ``row_kind`` ``"none"`` with no agent and no archive key.
    """

    view: str
    row_kind: str
    agent: Any = None
    read_only: bool = False
    archive_key: str | None = None
    provenance: str | None = None


@dataclass(frozen=True)
class ReadOnlyArchiveContext:
    """Read-only detail context carried outside serialized bundle state."""

    archive_key: str
    detail_generation: int = 0
    provenance: str | None = None
    read_only: bool = True


@dataclass(frozen=True)
class ArchiveViewOutcome:
    """Typed outcome for Archive entry and return seams."""

    status: str
    view: str
    generation: int
    committed_query: str | None = None
    exact_agent_name: str | None = None


def startup_agents_archive_view_state() -> AgentsArchiveViewState:
    """Return the startup view state: always Inbox with a fresh Archive."""
    return AgentsArchiveViewState()


def agents_archive_view_enabled() -> bool:
    """Return whether the ``agents_archive_view`` beta flag is enabled."""
    from sase.feature_flags.registry import FeatureFlag
    from sase.feature_flags.snapshot import current_flags

    return current_flags().enabled(FeatureFlag.agents_archive_view)


def capture_detail_owner(
    *,
    view: str,
    generation: int,
    selection_key: str | None = None,
) -> DetailOwnership:
    """Build the render token identifying who currently owns the detail panel."""
    return DetailOwnership(
        view=view, generation=generation, selection_key=selection_key
    )


def detail_owner_is_current(
    owner: DetailOwnership | None,
    *,
    view: str,
    generation: int,
) -> bool:
    """Return whether a scheduled token still owns the detail panel.

    A missing token is legacy (pre-view) work: it stays subject to the view
    gate but is never rejected as stale on its own.
    """
    if owner is None:
        return True
    return owner.view == view and owner.generation == generation


__all__ = [
    "AGENTS_VIEW_ARCHIVE",
    "AGENTS_VIEW_INBOX",
    "ARCHIVE_DEFAULT_GROUPING",
    "ARCHIVE_DEFAULT_QUERY",
    "ARCHIVE_ROW_AGENT",
    "ARCHIVE_ROW_NONE",
    "ARCHIVE_STATUS_ALREADY_INBOX",
    "ARCHIVE_STATUS_ALREADY_OPEN",
    "ARCHIVE_STATUS_DISABLED",
    "ARCHIVE_STATUS_OPENED",
    "ARCHIVE_STATUS_RETURNED",
    "AgentsArchiveViewState",
    "AgentsTabSelection",
    "ArchiveViewOutcome",
    "ArchiveViewState",
    "DetailOwnership",
    "ParkedInboxState",
    "ReadOnlyArchiveContext",
    "agents_archive_view_enabled",
    "capture_detail_owner",
    "detail_owner_is_current",
    "startup_agents_archive_view_state",
]
