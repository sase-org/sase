"""Pure per-root agent-tab index model (no I/O, no Textual)."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, TYPE_CHECKING

from sase.core.agent_tab import (
    DEFAULT_AGENT_TAB_KEY,
    AgentTabCatalogEntry,
    AgentTabKey,
    agent_tab_key_token,
    build_agent_tab_catalog,
)

from ._agent_tree_anchor import presentation_anchor_lookup
from .agent import Agent

if TYPE_CHECKING:
    from ..agent_tabs_settings import AgentTabsViewConfig


class _AllAgentTabs:
    """Sentinel scope spanning every agent tab (the later All-tabs level)."""

    __slots__ = ()

    _instance: _AllAgentTabs | None = None

    def __new__(cls) -> _AllAgentTabs:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ALL_AGENT_TABS"

    def __copy__(self) -> _AllAgentTabs:
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> _AllAgentTabs:
        return self


#: Scope value that disables tab filtering (consumed by ``layout-ladder``).
ALL_AGENT_TABS = _AllAgentTabs()

#: The active-tab scope: one tab key, or the all-tabs sentinel.
AgentTabScope = AgentTabKey | _AllAgentTabs

#: Fold/persistence token for the all-tabs scope.
ALL_AGENT_TABS_SCOPE_TOKEN = "all"

#: Prefix for in-memory scope tokens of unresolved-machine keys, which have
#: no persistence token and whose folds are never written to disk.
UNRESOLVED_TAB_SCOPE_PREFIX = "unresolved:"


def agent_tab_scope_token(scope: AgentTabScope) -> str:
    """Return the hashable fold/persistence token for *scope*."""
    if scope is ALL_AGENT_TABS:
        return ALL_AGENT_TABS_SCOPE_TOKEN
    if isinstance(scope, AgentTabKey):
        token = agent_tab_key_token(scope)
        if token is not None:
            return token
        return f"{UNRESOLVED_TAB_SCOPE_PREFIX}{scope.value}"
    return agent_tab_scope_token(DEFAULT_AGENT_TAB_KEY)


def scope_agents_to_tab(
    rows: list[Agent],
    index: AgentTabIndex | None,
    scope: AgentTabScope,
    *,
    enabled: bool = True,
) -> list[Agent]:
    """Return the rows visible under *scope* (pure, no I/O).

    With the flag off (``enabled=False``) or at the all-tabs scope this
    returns *rows* unchanged, so the flag-off roster is identical to today's.
    Otherwise a row (child rows included) is kept iff its presentation
    anchor's root key matches *scope*.
    """
    if not enabled or scope is ALL_AGENT_TABS or index is None:
        return rows
    if not isinstance(scope, AgentTabKey):
        return rows
    return [row for row in rows if index.key_for(row) == scope]


class AgentTabIndex:
    """Ordered tab catalog plus per-row tab resolution for one roster."""

    __slots__ = ("_entries", "_entry_by_key", "_key_by_id", "_key_by_identity")

    def __init__(
        self,
        entries: tuple[AgentTabCatalogEntry, ...],
        key_by_id: dict[int, AgentTabKey],
        key_by_identity: dict[tuple[Any, ...], AgentTabKey],
    ) -> None:
        self._entries = entries
        self._entry_by_key = {entry.key: entry for entry in entries}
        self._key_by_id = key_by_id
        self._key_by_identity = key_by_identity

    @property
    def catalog(self) -> tuple[AgentTabCatalogEntry, ...]:
        """The ordered catalog entries."""
        return self._entries

    def key_for(self, row: Agent) -> AgentTabKey:
        """Return the tab key for *row* via its presentation anchor.

        Rows rebuilt by the query or status overrides resolve through the
        identity fallback. Rows unknown to this index (added after it was
        built) fall back to the default key; the index is rebuilt whenever
        the roster changes, so that staleness is transient.
        """
        key = self._key_by_id.get(id(row))
        if key is not None:
            return key
        try:
            identity = row.identity
        except Exception:  # noqa: BLE001 - fall back to the default key.
            return DEFAULT_AGENT_TAB_KEY
        return self._key_by_identity.get(identity, DEFAULT_AGENT_TAB_KEY)

    def has(self, key: AgentTabKey) -> bool:
        """Return True when *key* holds at least one root."""
        return key in self._entry_by_key

    def root_count(self, key: AgentTabKey) -> int:
        """Return the root count for *key*, or 0 when absent."""
        entry = self._entry_by_key.get(key)
        return entry.root_count if entry is not None else 0

    @property
    def signature(self) -> tuple[tuple[AgentTabKey, str, int], ...]:
        """Ordered ``(key, label, root_count)`` tuple for repaint gating."""
        return tuple(
            (entry.key, entry.label, entry.root_count) for entry in self._entries
        )


def _root_wire(
    root: Agent,
    pinned_by_alias: dict[str, str],
) -> dict[str, Any]:
    """Derive one catalog root wire dict from a top-level anchor row."""
    alias = root.fleet_origin_alias or ""
    installation_id = root.fleet_origin_installation_id or pinned_by_alias.get(alias)
    if root.fleet_origin_alias:
        owner: dict[str, Any] = {
            "kind": "remote",
            "installation_id": installation_id,
            "alias": alias,
        }
    else:
        owner = {"kind": "local"}
    return {"agent_tab": root.agent_tab, "owner": owner}


def build_agent_tab_index(
    roster: list[Agent],
    view_config: AgentTabsViewConfig,
) -> AgentTabIndex:
    """Build the tab index for *roster* with a single batched catalog call.

    Every distinct top-level presentation anchor contributes one root,
    ``STARTING`` roots included. Children, session follow-ups, and clan
    members resolve to their root's tab. A row counts as remote iff
    ``fleet_origin_alias`` is set; its installation id comes from
    ``fleet_origin_installation_id`` with a ``pinned_by_alias`` fallback so a
    provisional dispatch row lands on the same key as its authoritative
    remote row.
    """
    anchors = presentation_anchor_lookup(roster)
    roots: list[Agent] = []
    seen: set[int] = set()
    for row in roster:
        anchor = anchors.get(id(row), row)
        anchor_id = id(anchor)
        if anchor_id not in seen:
            seen.add(anchor_id)
            roots.append(anchor)
    pinned_by_alias = (
        dict(view_config.pinned_by_alias) if view_config.pinned_by_alias else {}
    )
    catalog = build_agent_tab_catalog(
        [_root_wire(root, pinned_by_alias) for root in roots],
        machine_mode=view_config.machine_mode,
        machine_order=view_config.machine_order,
        named_order=dict(view_config.named_order) if view_config.named_order else {},
    )
    key_by_root_id = {
        id(root): key for root, key in zip(roots, catalog.keys, strict=True)
    }
    key_by_id: dict[int, AgentTabKey] = {}
    key_by_identity: dict[tuple[Any, ...], AgentTabKey] = {}
    for row in roster:
        anchor = anchors.get(id(row), row)
        key = key_by_root_id.get(id(anchor), DEFAULT_AGENT_TAB_KEY)
        key_by_id[id(row)] = key
        try:
            key_by_identity[row.identity] = key
        except Exception:  # noqa: BLE001 - unhashable identity; id map suffices.
            pass
    return AgentTabIndex(
        entries=catalog.entries,
        key_by_id=key_by_id,
        key_by_identity=key_by_identity,
    )


_INDEX_CACHE_SIZE = 2
_index_cache: OrderedDict[
    tuple[int, int, tuple[Any, ...]],
    tuple[list[Agent], tuple[Agent, ...], AgentTabIndex],
] = OrderedDict()


def _membership_is(snapshot: tuple[Agent, ...], roster: list[Agent]) -> bool:
    """Return True when *snapshot* is the same objects as *roster*, in order."""
    if len(snapshot) != len(roster):
        return False
    return all(left is right for left, right in zip(snapshot, roster, strict=True))


def cached_agent_tab_index(
    roster: list[Agent],
    view_config: AgentTabsViewConfig,
) -> AgentTabIndex:
    """Return the cached index for *roster* on a memo hit, else build it.

    The memo key is ``(id(roster), len(roster), view_config.token)`` plus a
    snapshot of its member objects compared element-wise with ``is``. The
    snapshot catches in-place append, remove, reorder, and recycled-id
    replacements. The cache holds strong references to at most two rosters
    and to the row objects in each snapshot, so a cached list id cannot be
    reused while its entry lives, a recycled row id cannot match a live
    snapshot, and old rosters do not accumulate across refreshes.
    """
    cache_key = (id(roster), len(roster), view_config.token)
    membership = tuple(roster)
    hit = _index_cache.get(cache_key)
    if hit is not None and hit[0] is roster and _membership_is(hit[1], roster):
        _index_cache.move_to_end(cache_key)
        return hit[2]
    index = build_agent_tab_index(roster, view_config)
    _index_cache[cache_key] = (roster, membership, index)
    _index_cache.move_to_end(cache_key)
    while len(_index_cache) > _INDEX_CACHE_SIZE:
        _index_cache.popitem(last=False)
    return index


__all__ = [
    "ALL_AGENT_TABS",
    "ALL_AGENT_TABS_SCOPE_TOKEN",
    "UNRESOLVED_TAB_SCOPE_PREFIX",
    "AgentTabIndex",
    "AgentTabScope",
    "agent_tab_scope_token",
    "build_agent_tab_index",
    "cached_agent_tab_index",
    "scope_agents_to_tab",
]
