"""Typed Agents-tab Archive view state, selection, and detail ownership.

View-foundation seam for the Agents Archive epic (child epic ``sase-1jm.3.1``).
Presentation state lives here in Python; outcome classification, timestamps,
root/container identity, membership, order, matching, counts, and exact lookup
stay in the existing Rust-backed corpus. Only grouping persists across launches;
every other field is per-process parked state. Startup is always Inbox.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

AGENTS_VIEW_INBOX = "inbox"
AGENTS_VIEW_ARCHIVE = "archive"

ARCHIVE_DEFAULT_QUERY = "in:archive"
ARCHIVE_DEFAULT_GROUPING = "day"

ARCHIVE_ROW_AGENT = "agent"
ARCHIVE_ROW_CONTAINER = "container"
ARCHIVE_ROW_NONE = "none"

ARCHIVE_SECTION_PULSE = "pulse"
ARCHIVE_SECTION_LIST = "list"

# Archive list keys: a run is its ``user.machine@run`` index identity; the
# prefixes below name the other list items. Banners and page tails are
# navigable but never agents (see ``is_archive_row_key``).
_BANNER_PREFIX = "banner:"
_TAIL_PREFIX = "tail:"
_CONTAINER_PREFIX = "container:"

# Agents-tab list-key intents the active Archive consumes (see
# ``route_archive_key``); the key actions pass these, never raw key names.
INTENT_DOWN = "down"
INTENT_UP = "up"
INTENT_FIRST = "first"
INTENT_LAST = "last"
INTENT_EXPAND = "expand"
INTENT_COLLAPSE = "collapse"
INTENT_ACTIVATE = "activate"
INTENT_SWITCH_SECTION = "switch_section"

ARCHIVE_STATUS_OPENED = "opened"
ARCHIVE_STATUS_ALREADY_OPEN = "already_open"
ARCHIVE_STATUS_DISABLED = "disabled"
ARCHIVE_STATUS_RETURNED = "returned"
ARCHIVE_STATUS_ALREADY_INBOX = "already_inbox"

ARCHIVE_ARRIVAL_FOUND = "found"
ARCHIVE_ARRIVAL_OWNER = "owner"
ARCHIVE_ARRIVAL_MISSING = "missing"

ARCHIVE_IDENTITY_KIND = "◷ ARCHIVED · read-only"
ARCHIVE_IDENTITY_ACCENT = "#d7af5f"


@dataclass
class ArchiveViewState:
    """Committed Archive presentation state. Only ``grouping`` persists.

    ``selected_key`` is the stable key of the highlighted Archive list item:
    a run's ``user.machine@run`` identity, ``container:<key>``, or the
    ``banner:``/``tail:`` key of a nav item that is never an agent (see
    :mod:`.agent_archive_list`). ``expanded_banners``/``folded_banners`` hold
    only the user's explicit fold overrides of the computed defaults.
    """

    committed_query: str = ARCHIVE_DEFAULT_QUERY
    grouping: str = ARCHIVE_DEFAULT_GROUPING
    expanded_banners: tuple[str, ...] = ()
    folded_banners: tuple[str, ...] = ()
    expanded_containers: tuple[str, ...] = ()
    loaded_pages: dict[str, int] = field(default_factory=dict)
    selected_key: str | None = None
    pending_exact_name: str | None = None
    arrival_outcome: ArchiveArrivalOutcome | None = None
    reveal_row: Mapping[str, Any] | None = None
    scroll: int = 0
    focused_section: str = ARCHIVE_SECTION_LIST
    deck_choices: dict[str, str] = field(default_factory=dict)
    marks: frozenset[str] = frozenset()
    restored_keys: frozenset[str] = frozenset()


@dataclass
class ParkedInboxState:
    """Inbox state parked while the Archive owns the Agents tab."""

    committed_query: str = ""
    selected_identity: Any = None
    scroll: int = 0
    scroll_y: float = 0.0
    agent_tab: Any = None
    panel_focus: str | None = None
    panel_layout: Any = None
    focused_panel: str | None = None
    group_focus: tuple[str, ...] | None = None
    deck_state: Any = None
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
    light_row: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ReadOnlyArchiveContext:
    """Read-only detail context carried outside serialized bundle state.

    Provenance, the light row, and retained/missing facts are the seam the
    parent Record phase consumes. Hydration never rewrites stored status.
    """

    archive_key: str
    detail_generation: int = 0
    provenance: str | None = None
    read_only: bool = True
    light_row: Mapping[str, Any] | None = None
    hydrated_agent: Any = None
    unreadable: bool = False
    retained: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArchiveViewOutcome:
    """Typed outcome for Archive entry and return seams."""

    status: str
    view: str
    generation: int
    committed_query: str | None = None
    exact_agent_name: str | None = None


@dataclass(frozen=True)
class ArchiveArrivalOutcome:
    """Typed exact-name lookup: the row itself, its workflow owner, or a miss."""

    status: str
    requested_name: str
    selected_key: str | None = None
    row_name: str | None = None


def banner_item_key(banner_key: str) -> str:
    """Return the list key of a banner's header item."""
    return f"{_BANNER_PREFIX}{banner_key}"


def tail_item_key(banner_key: str) -> str:
    """Return the list key of a banner's ``⋮ N more`` page tail."""
    return f"{_TAIL_PREFIX}{banner_key}"


def container_item_key(container_key: str) -> str:
    """Return the list key of a container's summary row."""
    return f"{_CONTAINER_PREFIX}{container_key}"


def is_archive_row_key(key: str | None) -> bool:
    """Return whether ``key`` names a run or container, not a banner or tail."""
    if not key:
        return False
    return not key.startswith((_BANNER_PREFIX, _TAIL_PREFIX))


def is_archive_container_key(key: str | None) -> bool:
    """Return whether ``key`` names a container summary row."""
    return bool(key) and str(key).startswith(_CONTAINER_PREFIX)


def container_key_of(key: str | None) -> str | None:
    """Return the core container key for a ``container:<key>`` item key."""
    if is_archive_container_key(key):
        return str(key)[len(_CONTAINER_PREFIX) :]
    return None


def startup_agents_archive_view_state() -> AgentsArchiveViewState:
    """Return the startup view state: always Inbox with a fresh Archive."""
    return AgentsArchiveViewState()


def agents_archive_view_enabled() -> bool:
    """Return whether the ``agents_archive_view`` beta flag is enabled."""
    from sase.feature_flags.registry import FeatureFlag
    from sase.feature_flags.snapshot import current_flags

    return current_flags().enabled(FeatureFlag.agents_archive_view)


def agent_is_archive_read_only(agent: Any) -> bool:
    """Return whether ``agent`` is a hydrated Archive row (live-path guard)."""
    return bool(getattr(agent, "_archive_read_only", False))


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
    "INTENT_ACTIVATE",
    "INTENT_COLLAPSE",
    "INTENT_DOWN",
    "INTENT_EXPAND",
    "INTENT_FIRST",
    "INTENT_LAST",
    "INTENT_SWITCH_SECTION",
    "INTENT_UP",
    "banner_item_key",
    "container_item_key",
    "container_key_of",
    "is_archive_container_key",
    "is_archive_row_key",
    "tail_item_key",
    "AGENTS_VIEW_ARCHIVE",
    "AGENTS_VIEW_INBOX",
    "ARCHIVE_DEFAULT_GROUPING",
    "ARCHIVE_DEFAULT_QUERY",
    "ARCHIVE_IDENTITY_ACCENT",
    "ARCHIVE_IDENTITY_KIND",
    "ARCHIVE_ROW_AGENT",
    "ARCHIVE_ROW_CONTAINER",
    "ARCHIVE_ROW_NONE",
    "ARCHIVE_SECTION_LIST",
    "ARCHIVE_SECTION_PULSE",
    "ARCHIVE_ARRIVAL_FOUND",
    "ARCHIVE_ARRIVAL_MISSING",
    "ARCHIVE_ARRIVAL_OWNER",
    "ARCHIVE_STATUS_ALREADY_INBOX",
    "ARCHIVE_STATUS_ALREADY_OPEN",
    "ARCHIVE_STATUS_DISABLED",
    "ARCHIVE_STATUS_OPENED",
    "ARCHIVE_STATUS_RETURNED",
    "AgentsArchiveViewState",
    "AgentsTabSelection",
    "ArchiveArrivalOutcome",
    "ArchiveViewOutcome",
    "ArchiveViewState",
    "DetailOwnership",
    "ParkedInboxState",
    "ReadOnlyArchiveContext",
    "agent_is_archive_read_only",
    "agents_archive_view_enabled",
    "capture_detail_owner",
    "detail_owner_is_current",
    "startup_agents_archive_view_state",
]
