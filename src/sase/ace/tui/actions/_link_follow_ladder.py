"""Reveal-ladder rungs for host-owned ``$`` link-follow."""

from __future__ import annotations

from typing import Any

from sase.ace.link_reveal import (
    HostQueryProbe,
    LinkReveal,
    build_identity_reveal_query,
    is_link_reveal_active,
    make_link_reveal,
    minimal_widening_query,
)
from sase.ace.query.limit_token import LimitTokenError, extract_limit
from sase.ace.query_record import QueryRecord, current_profile_digest
from sase.core.artifact_entry_target import ArtifactEntryTarget

RUNG_FOLD = 3
RUNG_LIMIT = 4
RUNG_IDENTITY = 5
RUNG_WIDEN = 6
RUNG_NEUTRAL = 7
RUNG_TOAST = 8

_SUCCESS_OUTCOMES = {
    RUNG_LIMIT: "fold",
    RUNG_IDENTITY: "limit",
    RUNG_WIDEN: "identity",
    RUNG_NEUTRAL: "widen",
    RUNG_TOAST: "neutral",
}


def selected_follow_outcome(rung: int) -> str:
    """Return the outcome label for a SELECTED follow that advanced to *rung*.

    *rung* is the next ladder step the transaction would try, so a follow
    that never rewrote still sits at :data:`RUNG_FOLD` and counts as
    ``select``.
    """
    return _SUCCESS_OUTCOMES.get(rung, "select")


def pane_limit_query(pane: Any) -> str | None:
    getter = getattr(pane, "host_limit_query", None)
    if not callable(getter):
        return None
    return str(getter())


def _limit_all_query(remainder: str) -> str:
    stripped = remainder.strip()
    if not stripped:
        return "limit:all"
    return f"{stripped} limit:all"


def capture_query_origin(
    app: Any,
    pane: Any,
    pane_id: str,
) -> tuple[QueryRecord | None, ArtifactEntryTarget | None]:
    current = pane_limit_query(pane) or ""
    if pane is not None:
        record_fn = getattr(pane, "query_history_record", None)
        if callable(record_fn):
            record = record_fn()
            canonical = getattr(record, "canonical", None)
            if isinstance(canonical, str):
                current = canonical
    live = getattr(app, "_link_reveals", {}).get(pane_id)
    if isinstance(live, LinkReveal) and is_link_reveal_active(
        live, pane_id=pane_id, current_canonical=current
    ):
        return live.origin, live.origin_target
    if pane_id == "patches":
        source = str(getattr(app, "query_string", "") or "")
        canonical = str(getattr(app, "canonical_query_string", source) or source)
        return (
            QueryRecord(
                source=source,
                canonical=canonical,
                profile_digest=current_profile_digest(pane_id),
            ),
            pane.selected_entry_target() if pane is not None else None,
        )
    if pane is None:
        return None, None
    record_fn = getattr(pane, "query_history_record", None)
    record = record_fn() if callable(record_fn) else None
    if not isinstance(record, QueryRecord):
        query = pane_limit_query(pane) or ""
        record = QueryRecord(
            source=query,
            canonical=query,
            profile_digest=current_profile_digest(pane_id),
        )
    selected = pane.selected_entry_target() if pane is not None else None
    return record, selected


def end_link_follow_pinning(app: Any) -> None:
    ender = getattr(app, "_end_collapsed_query_transitions", None)
    if callable(ender):
        ender()


def try_reveal_rung(app: Any, pane: Any, transaction: Any, rung: int) -> bool:
    if rung == RUNG_FOLD:
        expander = getattr(pane, "expand_fold_for_entry_target", None)
        return bool(callable(expander) and expander(transaction.target))
    if rung == RUNG_LIMIT:
        return _reveal_drop_head_slice_limit(app, pane, transaction)
    if rung == RUNG_IDENTITY:
        return _reveal_identity_query(app, pane, transaction)
    if rung == RUNG_WIDEN:
        return _reveal_minimal_widening(app, pane, transaction)
    if rung == RUNG_NEUTRAL:
        return _reveal_neutral_query(app, pane, transaction)
    return False


def _reveal_drop_head_slice_limit(app: Any, pane: Any, transaction: Any) -> bool:
    query = pane_limit_query(pane)
    if query is None:
        return False
    try:
        remainder, cap = extract_limit(query)
    except LimitTokenError:
        return False
    if cap is None:
        return False
    return _commit_reveal_query(app, pane, transaction, _limit_all_query(remainder))


def _reveal_identity_query(app: Any, pane: Any, transaction: Any) -> bool:
    profile = getattr(pane, "_query_profile", None)
    row_fn = getattr(pane, "host_query_row_for_target", None)
    row = row_fn(transaction.target) if callable(row_fn) else None
    if profile is None or row is None:
        return False
    rewritten = build_identity_reveal_query(profile, row)
    if rewritten is None:
        return False
    return _commit_reveal_query(app, pane, transaction, rewritten)


def _reveal_minimal_widening(app: Any, pane: Any, transaction: Any) -> bool:
    probe_fn = getattr(pane, "host_query_probe", None)
    probe: HostQueryProbe | Any = (
        probe_fn(transaction.target) if callable(probe_fn) else None
    )
    if probe is None or not callable(getattr(probe, "matches", None)):
        return False
    query = pane_limit_query(pane)
    if query is None:
        return False
    rewritten = minimal_widening_query(query, probe)
    if rewritten is None:
        return False
    return _commit_reveal_query(app, pane, transaction, rewritten)


def _reveal_neutral_query(app: Any, pane: Any, transaction: Any) -> bool:
    query = pane_limit_query(pane)
    if query is None:
        return False
    stripped = query.strip()
    if stripped in {"", "limit:all"}:
        return False
    return _commit_reveal_query(app, pane, transaction, "limit:all")


def _commit_reveal_query(
    app: Any,
    pane: Any,
    transaction: Any,
    query: str,
) -> bool:
    apply = getattr(pane, "apply_host_limit_query", None)
    if not callable(apply):
        return False
    before = pane_limit_query(pane)
    _ensure_reveal_session(app, pane, transaction)
    apply(query, grow=True)
    after = pane_limit_query(pane)
    if after == before:
        return False
    _refresh_link_reveal(app, pane, transaction, after or query)
    return True


def _ensure_reveal_session(app: Any, pane: Any, transaction: Any) -> None:
    begin = getattr(app, "_begin_collapsed_query_transitions", None)
    if getattr(app, "_collapsed_query_transitions", None) is not None:
        return
    closer = getattr(pane, "close_host_filter_session", None)
    if callable(closer):
        closer()
    pane_id = transaction.target.pane_id
    live = getattr(app, "_link_reveals", {}).get(pane_id)
    current = pane_limit_query(pane) or ""
    skip = is_link_reveal_active(live, pane_id=pane_id, current_canonical=current)
    if callable(begin):
        begin(pane_id)
    if skip:
        app._collapsed_query_transition_recorded = True


def _refresh_link_reveal(
    app: Any,
    pane: Any,
    transaction: Any,
    revealed: str,
) -> None:
    del pane
    origin = transaction.origin_query
    reveal = make_link_reveal(
        pane_id=transaction.target.pane_id,
        ref=transaction.ref,
        origin_source="" if origin is None else origin.source,
        origin_canonical="" if origin is None else origin.canonical,
        origin_target=transaction.origin_target,
        revealed_canonical=revealed,
    )
    reveals = getattr(app, "_link_reveals", None)
    if not isinstance(reveals, dict):
        reveals = {}
        app._link_reveals = reveals
    reveals[transaction.target.pane_id] = reveal
