"""One-time migration of Artifacts Agent pane saved queries to ``agents-live``.

When the ``artifacts_agent_pane_retired`` sunset flag is on, the Agent
pane's ``agents``-namespace saved slots and history entries move to the
Agents tab's ``agents-live`` namespace with ``in:archive`` prepended, so
pane-era ``#N`` slots keep working from either Agents view. The rewrite
drops pane-only terms (``limit:``, ``state:dismissed``, ``dismissed:true``)
and renames ``tribe:`` to ``clan_tribe:``, then validates the result
against the agents-archive profile: only the canonical text validation
returns is stored, and anything validation rejects stays behind.

The migration runs once per machine (a marker file under :func:`sase_home`),
is idempotent, and never overwrites an existing ``agents-live`` slot.
Entries that cannot be converted safely (boolean structure, a negated
dismissed marker whose drop would reverse its meaning, a term the archive
profile rejects, or a full ``agents-live`` slot map) stay in the old
``agents`` namespace.
"""

from __future__ import annotations

import logging
from pathlib import Path

from sase.core.paths import sase_home

log = logging.getLogger(__name__)

PANE_NAMESPACE = "agents"
LIVE_NAMESPACE = "agents-live"

_MARKER_FILENAME = "agents_pane_queries_migrated"

#: Test override for the migration marker path (mirrors the stores'
#: ``_SAVED_QUERIES_FILE`` / ``_QUERY_HISTORY_FILE`` patch points).
_MARKER_FILE: Path | None = None

_DROPPED_FIELDS = frozenset({"limit"})
_DROPPED_TERMS = frozenset({"state:dismissed", "dismissed:true"})
_RENAMED_FIELDS = {"tribe": "clan_tribe"}

_migration_done_this_process = False


def _marker_path() -> Path:
    return _MARKER_FILE or sase_home() / _MARKER_FILENAME


def _split_terms(source: str) -> list[str]:
    """Split *source* on whitespace, keeping quoted spans intact."""
    terms: list[str] = []
    buf: list[str] = []
    in_quotes = False
    for char in source:
        if char == '"':
            in_quotes = not in_quotes
            buf.append(char)
        elif char.isspace() and not in_quotes:
            if buf:
                terms.append("".join(buf))
                buf = []
        else:
            buf.append(char)
    if buf:
        terms.append("".join(buf))
    return terms


def _convert_agents_pane_query(source: str) -> str | None:
    """Rewrite one pane-era query for the ``agents-live`` Archive scope.

    Returns the canonical agents-archive text, or ``None`` when the entry
    must stay in the old namespace (boolean operators or grouping the term
    rewrite cannot preserve, a negated dismissed marker whose drop would
    reverse its meaning, or a term the archive profile rejects).
    """
    from sase.ace.query.profile_reference_support import ProfileQueryError
    from sase.ace.query.scope_token import ScopeTokenError
    from sase.ace.tui.models.agent_live_query_engine import canonical_agents_tab_query

    terms = _split_terms(source.strip())
    kept: list[str] = []
    for term in terms:
        lowered = term.lower()
        if lowered in {"and", "or", "not"} or "(" in term or ")" in term:
            return None
        negated = lowered.startswith("-")
        field, sep, _ = (lowered[1:] if negated else lowered).partition(":")
        if not sep:
            kept.append(f"NOT {term[1:]}" if negated else term)
            continue
        unnegated = lowered[1:] if negated else lowered
        if field in _DROPPED_FIELDS or unnegated in _DROPPED_TERMS:
            if negated:
                # Dropping a negation reverses its meaning.
                return None
            continue
        renamed = _RENAMED_FIELDS.get(field)
        if renamed is not None:
            _, _, rest = term.partition(":")
            rewritten = f"{renamed}:{rest}"
            kept.append(f"NOT {rewritten}" if negated else rewritten)
        elif negated:
            kept.append(f"NOT {term[1:]}")
        else:
            kept.append(term)
    raw = "in:archive " + " ".join(kept) if kept else "in:archive"
    try:
        return canonical_agents_tab_query(raw)
    except (ProfileQueryError, ScopeTokenError):
        return None


def ensure_agents_pane_queries_migrated() -> bool:
    """Migrate pane saved queries/history once; return whether it ran."""
    global _migration_done_this_process
    if _migration_done_this_process:
        return False
    _migration_done_this_process = True
    try:
        from sase.ace.tui._artifact_tab_model import artifacts_agent_pane_retired

        if not artifacts_agent_pane_retired():
            return False
        if _marker_path().exists():
            return False
        _migrate_saved_slots()
        _migrate_history()
        try:
            path = _marker_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
        except OSError:
            log.debug("Failed to persist agents pane migration marker", exc_info=True)
            return False
        return True
    except Exception:
        log.debug("Agents pane query migration failed", exc_info=True)
        return False


def _migrate_saved_slots() -> None:
    from sase.ace.saved_queries import (
        delete_query,
        get_next_available_slot,
        load_saved_queries,
        save_query,
    )

    panes_live = load_saved_queries(LIVE_NAMESPACE)
    live_canonicals = {record.canonical for record in panes_live.values()}
    for slot, record in list(load_saved_queries(PANE_NAMESPACE).items()):
        converted = _convert_agents_pane_query(record.source)
        if converted is None or converted in live_canonicals:
            continue
        free = get_next_available_slot(load_saved_queries(LIVE_NAMESPACE))
        if free is None:
            continue
        if save_query(LIVE_NAMESPACE, free, converted, converted):
            live_canonicals.add(converted)
            delete_query(PANE_NAMESPACE, slot)


def _migrate_history() -> None:
    from sase.ace.query_history import (
        MAX_STACK_SIZE,
        QueryHistoryStacks,
        load_all_query_history,
        save_all_query_history,
    )
    from sase.ace.query_record import QueryRecord

    panes = load_all_query_history()
    live = panes.get(LIVE_NAMESPACE)
    if live is None:
        live = QueryHistoryStacks(prev=[], next=[])
        panes[LIVE_NAMESPACE] = live
    old = panes.get(PANE_NAMESPACE)
    if old is None:
        return
    live_canonicals = {record.canonical for record in (*live.prev, *live.next)}
    moved_sources: set[str] = set()
    for record in (*old.prev, *old.next):
        converted = _convert_agents_pane_query(record.source)
        if converted is None or converted in live_canonicals:
            continue
        live.prev.append(
            QueryRecord(source=converted, canonical=converted, profile_digest=None)
        )
        live_canonicals.add(converted)
        moved_sources.add(record.source)
    if not moved_sources:
        return
    live.prev = live.prev[-MAX_STACK_SIZE:]
    panes[LIVE_NAMESPACE] = live
    panes[PANE_NAMESPACE] = QueryHistoryStacks(
        prev=[record for record in old.prev if record.source not in moved_sources],
        next=[record for record in old.next if record.source not in moved_sources],
    )
    save_all_query_history(panes)


__all__ = [
    "LIVE_NAMESPACE",
    "PANE_NAMESPACE",
    "_convert_agents_pane_query",
    "ensure_agents_pane_queries_migrated",
]
