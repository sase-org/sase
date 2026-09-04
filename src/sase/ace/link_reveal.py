"""Reversible query-rewrite lens for artifact link-follow.

Following a link to a row outside a pane's current result set has one
host-owned mechanism: walk an ordered reveal ladder until the row is
visible. A :class:`LinkReveal` gives a rewriting rung an identity -- the
followed ref and the exact query it rewrote *from* -- so the host can
advertise a way back (``^``) and detect when that way back has gone stale.

The ladder prefers cheaper rungs first. Fold expansion mutates no query and
pushes no history entry, so it runs before any rewrite even though an
earlier epic sketch listed the ``limit:`` drop first. Identity reveal is a
documented gap (phase ``sase-w3.5``) that the rung cursor is shaped for,
not implemented here.

The lens is deliberately not a stored on/off flag. It is live for a pane
whenever that pane's current canonical query still equals the query the
reveal rewrote *to* and the origin dialect has not changed since; the
moment the user edits the query (their own edit, ``prev_query``/
``next_query`` history navigation, or a saved-query load), the live
canonical query moves away from ``revealed_canonical`` and the lens
reports itself inactive with no separate "clear" step required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.ace.query.limit_token import LimitTokenError, extract_limit
from sase.ace.query.profile_reference_support import ProfileQueryError
from sase.ace.query_record import QueryRecord, current_profile_digest
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.query_profile_corpus_facade import (
    ArtifactQueryIndex,
    compile_artifact_query_index,
    evaluate_artifact_query_many,
)
from sase.filter_tokens import FilterQueryError, tokenize

_BOOLEAN_WORDS = frozenset({"AND", "OR", "NOT"})


@dataclass(frozen=True, slots=True)
class LinkReveal:
    """One link-follow query rewrite, with everything needed to return."""

    pane_id: str
    ref: str
    origin: QueryRecord
    origin_target: ArtifactEntryTarget | None
    revealed_canonical: str


@dataclass(frozen=True, slots=True)
class HostQueryProbe:
    """A one-row matcher for a single unfiltered pane row.

    Built from a pane's compiled profile plus that row's query-entry so
    host-side widening can ask "would this query include the target?"
    without committing anything. The corpus is exactly one row, so both
    compile and evaluate stay bounded for the keystroke path.
    """

    index: ArtifactQueryIndex

    def matches(self, query: str) -> bool:
        """Whether *query* would include this probe's single row."""
        try:
            result = evaluate_artifact_query_many(query, self.index)
        except (ProfileQueryError, LimitTokenError, Exception):
            return False
        return bool(result.matched_row_ids)


def make_link_reveal(
    *,
    pane_id: str,
    ref: str,
    origin_source: str,
    origin_canonical: str,
    origin_target: ArtifactEntryTarget | None,
    revealed_canonical: str,
) -> LinkReveal:
    """Build one lens record, stamping the origin dialect's digest."""
    return LinkReveal(
        pane_id=pane_id,
        ref=ref,
        origin=QueryRecord(
            source=origin_source,
            canonical=origin_canonical,
            profile_digest=current_profile_digest(pane_id),
        ),
        origin_target=origin_target,
        revealed_canonical=revealed_canonical,
    )


def is_link_reveal_active(
    reveal: LinkReveal | None,
    *,
    pane_id: str,
    current_canonical: str,
) -> bool:
    """Return whether *reveal* is still the live lens for *pane_id*.

    ``False`` once the pane's live query has moved away from the rewrite
    (a user edit, a history navigation, or a fresh reveal) or once the
    pane's dialect has changed since the reveal was recorded.
    """
    if reveal is None or reveal.pane_id != pane_id:
        return False
    if reveal.revealed_canonical != current_canonical:
        return False
    return not reveal.origin.is_stale(pane_id)


def pane_canonical_query(pane: Any) -> str:
    """Return *pane*'s current canonical query string.

    Mirrors the resolution :func:`~sase.ace.tui.actions._link_follow_ladder.capture_query_origin`
    uses: a pane's own ``query_history_record().canonical`` when available,
    falling back to its raw ``host_limit_query()`` text. Patches has neither
    method on the pane object the Artifacts contract expects, so its info
    panel passes ``AceApp.canonical_query_string`` to
    :func:`active_pane_link_reveal` directly instead of calling this.
    """
    current = ""
    query_fn = getattr(pane, "host_limit_query", None)
    if callable(query_fn):
        current = str(query_fn())
    record_fn = getattr(pane, "query_history_record", None)
    if callable(record_fn):
        record = record_fn()
        canonical = getattr(record, "canonical", None)
        if isinstance(canonical, str):
            return canonical
    return current


def active_pane_link_reveal(
    app: Any, pane_id: str, *, current_canonical: str
) -> LinkReveal | None:
    """Return *pane_id*'s live :class:`LinkReveal`, or ``None`` if none is live.

    Shared by every pane's info/scope renderer so the lens chip (built with
    :func:`sase.ace.tui.widgets.artifacts.shell.build_reveal_chip`) reflects
    the same liveness rule the reveal ladder itself uses. Callers compute
    *current_canonical* with :func:`pane_canonical_query` (or, for Patches,
    ``AceApp.canonical_query_string``).
    """
    reveal = getattr(app, "_link_reveals", {}).get(pane_id)
    if not isinstance(reveal, LinkReveal):
        return None
    if not is_link_reveal_active(
        reveal, pane_id=pane_id, current_canonical=current_canonical
    ):
        return None
    return reveal


def build_host_query_probe(
    row: Any | None,
    profile: Any | None,
) -> HostQueryProbe | None:
    """Build a one-row matcher, or ``None`` when *row* or *profile* is missing.

    Binding and compile failures degrade to "no answer" rather than raising
    into an action handler.
    """
    if row is None or profile is None:
        return None
    pane_id = getattr(profile, "pane_id", None)
    if not isinstance(pane_id, str) or not pane_id:
        return None
    try:
        index = compile_artifact_query_index(
            pane_id=pane_id,
            generation=0,
            profile=profile,
            entries=(row,),
        )
    except (ProfileQueryError, Exception):
        return None
    return HostQueryProbe(index=index)


def _limit_all_query(remainder: str) -> str:
    stripped = remainder.strip()
    if not stripped:
        return "limit:all"
    return f"{stripped} limit:all"


def _has_boolean_syntax(raw: str, value: str) -> bool:
    if value.upper() in _BOOLEAN_WORDS:
        return True
    return "(" in raw or ")" in raw


def minimal_widening_query(query: str, probe: HostQueryProbe) -> str | None:
    """Drop only the terms that exclude *probe*'s row.

    Returns ``None`` when the filter is not what is hiding the row, when
    the query uses boolean-grammar syntax (token subtraction is not sound
    for ``boolean=True`` dialects such as patches and agents), or when
    verification of the rewritten query fails. Callers then fall through
    to the neutral ``limit:all`` rung.
    """
    try:
        remainder, _cap = extract_limit(query)
    except LimitTokenError:
        return None
    if probe.matches(remainder):
        return None
    try:
        tokens = tokenize(remainder, error_type=FilterQueryError)
    except FilterQueryError:
        return None
    if any(_has_boolean_syntax(token.raw, token.value) for token in tokens):
        return None
    kept = tuple(token.raw for token in tokens if probe.matches(token.raw))
    if len(kept) == len(tokens):
        return None
    rewritten = " ".join(kept)
    if not probe.matches(rewritten):
        return None
    return _limit_all_query(rewritten)


__all__ = [
    "HostQueryProbe",
    "LinkReveal",
    "active_pane_link_reveal",
    "build_host_query_probe",
    "is_link_reveal_active",
    "make_link_reveal",
    "minimal_widening_query",
    "pane_canonical_query",
]
