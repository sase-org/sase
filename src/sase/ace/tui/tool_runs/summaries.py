"""Selection-scoped ToolRun node summaries (plan §§3.3, 3.5.2, 3.7).

Builds one core selector per Agents-tab node, loads its history through
``tool_run_node_summaries`` on a worker thread, and keeps the result in a
small LRU keyed by ``(selector key, store token)``. The compact header chip,
the expanded ``Tool runs`` field, and (later) the Runs card availability all
read the same entry.

Render paths stay pure: they receive an in-memory
:class:`~sase.core.tool_run.ToolRunNodeSummary` plus ``now`` and never stat,
open SQLite, or read a log. Only :func:`resolve_tool_run_summary` touches
the store, and it runs on the detail-header enrichment worker, behind the
existing ``DetailPanelDebouncer`` selection flow. Stale generations are
rejected by the enrichment publish path (``is_current`` per batch, copied
from ``FinalDeckView``); the blocking load additionally re-checks the
caller's ``is_current`` predicate after the await so a j/k sprint never
publishes a superseded node.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from sase.ace.tui.tool_runs.attribution import row_identity_from_agent

if TYPE_CHECKING:
    from sase.core.tool_run import ToolRunNodeSummary

log = logging.getLogger(__name__)

#: Node-summary LRU capacity: one entry per recently selected node.
NODE_SUMMARY_LRU_CAPACITY = 64

#: Runs returned per node (core ``per_node_limit`` bound).
NODE_SUMMARY_PER_NODE_LIMIT = 20

_summary_lock = threading.Lock()
_summary_lru: OrderedDict[tuple[str, str], ToolRunNodeSummary] = OrderedDict()


@dataclass(frozen=True)
class ToolRunSelector:
    """The core query key for one Agents-tab node (plan §3.3)."""

    key: str
    agents: tuple[str, ...] = ()
    owners: tuple[tuple[str, str], ...] = ()
    since_ts: int | None = None

    def to_request(self) -> dict[str, Any]:
        """Return the core ``ToolRunNodeSelectorWire`` request dict."""

        request: dict[str, Any] = {
            "key": self.key,
            "agents": list(self.agents),
            "owners": [
                {"kind": kind, "id": owner_id} for kind, owner_id in self.owners
            ],
        }
        if self.since_ts is not None:
            request["since_ts"] = self.since_ts
        return request


def selector_for_agent(agent: object) -> ToolRunSelector | None:
    """Return the node selector for *agent*, or None when it has no history.

    Remote rows (``fleet_origin_alias``) and clan containers never match
    (D15): the ledger is machine-local, so absence must never read as
    "no runs". Attribution is by node kind, never by name-prefix guessing.
    """

    row = row_identity_from_agent(agent)
    if row.is_remote or row.is_clan:
        return None
    since_ts = _node_since_ts(agent)
    if row.is_monitor_row and row.monitor_id:
        return ToolRunSelector(
            key=f"monitor:{row.monitor_id}",
            owners=(("monitor", row.monitor_id),),
            since_ts=since_ts,
        )
    if row.is_proc_row and row.proc_id:
        return ToolRunSelector(
            key=f"proc:{row.proc_id}",
            owners=(("proc", row.proc_id),),
            since_ts=since_ts,
        )
    if row.is_session_container:
        names = {*row.session_member_names}
        if row.container_name:
            names.add(row.container_name)
        if row.agent_name:
            names.add(row.agent_name)
        ordered = tuple(sorted(names))
        if not ordered:
            return None
        return ToolRunSelector(
            key=f"session:{'|'.join(ordered)}",
            agents=ordered,
            since_ts=since_ts,
        )
    if row.agent_name:
        return ToolRunSelector(
            key=f"agent:{row.agent_name}",
            agents=(row.agent_name,),
            since_ts=since_ts,
        )
    return None


def _node_since_ts(agent: object) -> int | None:
    """Return the node's start time minus 60 s, guarding reused names (§3.3)."""

    start_time = getattr(agent, "start_time", None)
    if start_time is None:
        return None
    try:
        return int(start_time.timestamp()) - 60
    except (AttributeError, OSError, OverflowError, TypeError, ValueError):
        return None


def _lru_key(selector: ToolRunSelector, store_token: Any | None) -> tuple[str, str]:
    """Return a hashable LRU key for (*selector*, *store_token*)."""

    try:
        hash(store_token)
        token_part: Any = store_token
    except TypeError:
        token_part = repr(store_token)
    return (selector.key, str(token_part))


def _cached_node_summary(
    selector: ToolRunSelector,
    store_token: Any | None,
) -> ToolRunNodeSummary | None:
    """Return the LRU entry for (*selector*, *store_token*), if any."""

    key = _lru_key(selector, store_token)
    with _summary_lock:
        entry = _summary_lru.get(key)
        if entry is not None:
            _summary_lru.move_to_end(key)
        return entry


def cached_node_summary_for_selector(
    selector: ToolRunSelector,
) -> ToolRunNodeSummary | None:
    """Return the newest LRU entry for *selector* across store tokens.

    A pure memory read: no stat, no SQLite open. Used by no-I/O
    availability probes that cannot afford even the stat-only token.
    """

    with _summary_lock:
        best_key: tuple[str, str] | None = None
        best: ToolRunNodeSummary | None = None
        for full_key, entry in _summary_lru.items():
            if full_key[0] != selector.key:
                continue
            best_key, best = full_key, entry
        if best_key is not None:
            _summary_lru.move_to_end(best_key)
        return best


def _store_node_summary(
    selector: ToolRunSelector,
    store_token: Any | None,
    summary: ToolRunNodeSummary,
) -> None:
    """Store *summary* in the bounded LRU."""

    key = _lru_key(selector, store_token)
    with _summary_lock:
        _summary_lru[key] = summary
        _summary_lru.move_to_end(key)
        while len(_summary_lru) > NODE_SUMMARY_LRU_CAPACITY:
            _summary_lru.popitem(last=False)


def _load_node_summary_blocking(
    selector: ToolRunSelector,
    *,
    store_path: str | None = None,
    busy_timeout_ms: int = 250,
) -> ToolRunNodeSummary | None:
    """Load one node summary on a worker thread; never raise.

    A busy or locked store, a newer schema, or a thread error keeps the
    last state (returns None). A missing binding (stale wheel) disables
    ToolRun surfaces for the session with one log line, no toast storm,
    and no crash.
    """

    try:
        from sase.core.tool_run import tool_run_node_summaries
    except Exception as exc:
        from sase.ace.tui.tool_runs.snapshot import note_tool_runs_disabled

        note_tool_runs_disabled(f"missing tool_run binding: {exc}")
        return None
    try:
        result = tool_run_node_summaries(
            {
                "nodes": [selector.to_request()],
                "per_node_limit": NODE_SUMMARY_PER_NODE_LIMIT,
            },
            store_path=store_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    except AttributeError as exc:
        from sase.ace.tui.tool_runs.snapshot import note_tool_runs_disabled

        note_tool_runs_disabled(f"missing tool_run_node_summaries binding: {exc}")
        return None
    except Exception as exc:
        log.debug("ToolRun node summary load failed, keeping last state: %s", exc)
        return None
    try:
        nodes = tuple(getattr(result, "nodes", ()) or ())
    except Exception as exc:
        log.debug("ToolRun node summary decode failed, keeping last state: %s", exc)
        return None
    if not nodes:
        return None
    return nodes[0]


def resolve_tool_run_summary(
    agent: object,
    *,
    store_token: Any | None = None,
    is_current: Callable[[], bool] | None = None,
) -> ToolRunNodeSummary | None:
    """Resolve the ``tool-runs`` lane for *agent* on a worker thread.

    Reads the LRU first (no SQLite open on a hit); on a miss runs one
    blocking ``tool_run_node_summaries`` call and caches under
    ``(selector key, store token)``. Returns None when the node has no
    selector, the load failed, or *is_current* reports the selection
    moved on while the load was in flight.
    """

    selector = selector_for_agent(agent)
    if selector is None:
        return None
    if store_token is None:
        store_token = _probe_store_token()
    cached = _cached_node_summary(selector, store_token)
    if cached is not None:
        return cached
    loaded = _load_node_summary_blocking(selector)
    if loaded is None:
        return None
    _store_node_summary(selector, store_token, loaded)
    if is_current is not None:
        try:
            if not is_current():
                return None
        except Exception:
            return None
    return loaded


def node_live_runs(
    snapshot_runs: tuple[Any, ...] | list[Any],
    selector: ToolRunSelector,
) -> tuple[Any, ...]:
    """Return snapshot live runs scoped to *selector* (inclusive history).

    Unlike the exclusive row-chip match, header history shows both
    relationships: a run matches when its ``agent`` is in the selector's
    agents **or** its ``(owner_kind, owner_id)`` is in the selector's
    owners, and its ``created_ts`` is at or after ``since_ts``. Results
    dedupe by ``run_id`` with a live child folded into its live parent.
    """

    agents = set(selector.agents or ())
    owners = {tuple(item) for item in (selector.owners or ())}
    matched: list[Any] = []
    for run in snapshot_runs or ():
        if str(getattr(run, "state", "")) not in {"created", "running"}:
            continue
        if selector.since_ts is not None:
            try:
                created = int(getattr(run, "created_ts", 0) or 0)
            except (TypeError, ValueError):
                created = 0
            if created < int(selector.since_ts):
                continue
        owner = (getattr(run, "owner_kind", None), getattr(run, "owner_id", None))
        if getattr(run, "agent", None) not in agents and tuple(owner) not in owners:
            continue
        matched.append(run)
    ids = {str(getattr(run, "run_id", "")) for run in matched}
    folded = [
        run
        for run in matched
        if not (
            getattr(run, "parent_run_id", None)
            and str(getattr(run, "parent_run_id", "")) in ids
        )
    ]
    seen: set[str] = set()
    unique: list[Any] = []
    for run in folded:
        run_id = str(getattr(run, "run_id", ""))
        if run_id in seen:
            continue
        seen.add(run_id)
        unique.append(run)
    return tuple(unique)


def _probe_store_token() -> Any | None:
    """Stat-only probe of the ToolRun store files (never opens SQLite)."""

    try:
        from sase.ace.tui.actions.event_refresh._surface_tokens import (
            probe_tool_runs_token,
        )
    except Exception:
        return None
    try:
        return probe_tool_runs_token()
    except Exception:
        return None


__all__ = [
    "NODE_SUMMARY_LRU_CAPACITY",
    "NODE_SUMMARY_PER_NODE_LIMIT",
    "ToolRunSelector",
    "cached_node_summary_for_selector",
    "node_live_runs",
    "resolve_tool_run_summary",
    "selector_for_agent",
]
