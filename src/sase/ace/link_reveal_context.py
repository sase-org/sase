"""Verified context rewrites for artifact link jumps.

One engine, plan-then-commit: each jump makes at most one query rewrite,
verified against the target's own row before it is committed. This module
holds the pure pieces — the context description, the dialect-aware
renderer, the limit policy, and hidden-reason analysis — so panes and the
link-follow transaction stay thin.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sase.ace.query.limit_token import LimitTokenError, extract_limit
from sase.filter_tokens import FilterQueryError, quote_value, tokenize


@dataclass(frozen=True, slots=True)
class RevealContext:
    """One verified context query a pane offers for a target."""

    alternatives: tuple[tuple[str, str], ...]
    constraints: tuple[str, ...] = ()
    label: str = ""
    member_count: int | None = None
    expand_target_fold: bool = False


HiddenReasonKind = Literal[
    "filtered", "filtered_boolean", "limited", "unloaded", "scoped"
]


@dataclass(frozen=True, slots=True)
class HiddenReason:
    """Why a target was not visible before its reveal."""

    kind: HiddenReasonKind
    terms: tuple[str, ...] = ()
    cap: int | None = None
    hint: str = ""


@dataclass(frozen=True, slots=True)
class RevealOutcome:
    """Data the toast formatter consumes for one successful reveal."""

    pane_label: str
    ref: str
    old_canonical: str
    new_canonical: str
    hidden: HiddenReason
    scope_change: tuple[str | None, str | None] | None
    context_label: str | None
    hydrated: bool = False
    agents_tab_fallback: bool = False
    outcome: str = "context"


def _resolve_reveal_limit(
    current_query: str,
    member_count: int | None,
    page_size: int,
) -> int | None:
    """Return the cap the context query should keep.

    *C* is the current ``limit:`` cap (``None`` means unlimited). The
    context keeps ``limit:C``; when the family would not fit
    (``member_count > C``) it rises to the smallest multiple of
    *page_size* that fits, matching the Ctrl+J paging convention. The
    context step never writes ``limit:all`` (``None`` here means the
    caller should emit no numeric token).
    """
    if type(page_size) is not int or page_size < 1:
        raise ValueError("page_size must be an integer >= 1")
    try:
        _remainder, current = extract_limit(current_query)
    except LimitTokenError:
        current = None
    if current is None:
        return None
    if member_count is None or member_count <= current:
        return current
    steps = (member_count + page_size - 1) // page_size
    return steps * page_size


def render_reveal_query(
    context: RevealContext,
    profile: Any,
    *,
    current_query: str,
    page_size: int,
) -> str:
    """Render *context* as query text for *profile*'s dialect.

    Flat dialects repeat the key token (``id:a id:a.*``); boolean
    dialects join alternatives with ``OR`` inside one parenthesized
    group. Values go through :func:`quote_value` with ``keyed=True``,
    which keeps ``*`` bare. Constraints are extra ANDed tokens.
    """
    tokens: list[str] = []
    boolean = bool(getattr(profile, "boolean", False))
    if context.alternatives:
        if boolean:
            parts = [
                f"{field}:{quote_value(value, keyed=True)}"
                for field, value in context.alternatives
            ]
            if len(parts) == 1:
                tokens.append(parts[0])
            else:
                tokens.append(f"({' OR '.join(parts)})")
        else:
            for field, value in context.alternatives:
                tokens.append(f"{field}:{quote_value(value, keyed=True)}")
    tokens.extend(context.constraints)
    base = " ".join(tokens)
    cap = _resolve_reveal_limit(current_query, context.member_count, page_size)
    if cap is None:
        return base
    if not base:
        return f"limit:{cap}"
    return f"{base} limit:{cap}"


def explain_hidden(
    probe: Any | None,
    current_query: str,
    profile: Any | None,
) -> HiddenReason:
    """Explain why *probe*'s row was hidden under *current_query*."""
    boolean = bool(getattr(profile, "boolean", False))
    if probe is None or not callable(getattr(probe, "matches", None)):
        return HiddenReason(kind="unloaded", hint="row is not loaded")
    try:
        remainder, cap = extract_limit(current_query)
    except LimitTokenError:
        if boolean:
            return HiddenReason(kind="filtered_boolean")
        return HiddenReason(kind="filtered", terms=(current_query.strip(),))
    try:
        matches_filter = bool(probe.matches(remainder))
    except Exception:  # noqa: BLE001 - a probe failure is not absence
        return HiddenReason(kind="unloaded", hint="row is not loaded")
    if matches_filter:
        if cap is not None:
            return HiddenReason(kind="limited", cap=cap)
        return HiddenReason(kind="unloaded", hint="row is not loaded")
    if boolean:
        return HiddenReason(kind="filtered_boolean")
    try:
        tokens = tokenize(remainder, error_type=FilterQueryError)
    except FilterQueryError:
        stripped = remainder.strip()
        return HiddenReason(kind="filtered", terms=(stripped,) if stripped else ())
    excluding: list[str] = []
    for token in tokens:
        try:
            if not probe.matches(token.raw):
                excluding.append(token.raw)
        except Exception:  # noqa: BLE001 - treat probe errors as excluding
            excluding.append(token.raw)
    if not excluding:
        stripped = remainder.strip()
        return HiddenReason(kind="filtered", terms=(stripped,) if stripped else ())
    return HiddenReason(kind="filtered", terms=tuple(excluding))


__all__ = [
    "HiddenReason",
    "RevealContext",
    "RevealOutcome",
    "explain_hidden",
    "render_reveal_query",
]
