"""Pure query-language helpers for bead filtering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sase.bead.model import BeadTier
from sase.bead_status_presentation import bead_status_display_order
from sase.bead_type_presentation import BEAD_TYPE_VALUES
from sase.filter_tokens import (
    FilterQueryError,
    FilterToken,
    completion_context,
    error_for_token,
    quote_value,
    split_unquoted,
    tokenize,
    unknown_key_error,
    unquoted_index,
)
from sase.phase_size_presentation import PHASE_SIZE_VALUES
from sase.vcs_log.dates import (
    TimeBoundary,
    VcsLogDateError,
    normalize_reference_time,
    parse_time_bound,
)

BEAD_FILTER_TYPE_VALUES: tuple[str, ...] = (*BEAD_TYPE_VALUES, "flag")

BeadCompletionKind = Literal[
    "key",
    "type",
    "tier",
    "status",
    "size",
    "due",
    "project",
    "assignee",
    "owner",
    "model",
    "has",
    "bug",
    "label",
    "since",
    "until",
    "task_type",
    "text",
]

DERIVED_BEAD_STATUS_VALUES: tuple[str, ...] = ("blocked", "launched", "triage")
BEAD_FLAG_DUE_VALUES: tuple[str, ...] = ("live", "soon", "due")
BEAD_HAS_VALUES: tuple[str, ...] = (
    "+1",
    "reopened",
    "plan",
    "bug",
    "deps",
    "notes",
    "triage",
)
DEFAULT_BEAD_FILTER_QUERY = "-status:closed"

_FILTER_KEYS = (
    "type",
    "tier",
    "status",
    "size",
    "due",
    "project",
    "assignee",
    "owner",
    "model",
    "has",
    "bug",
    "label",
    "since",
    "until",
    "task_type",
)
_REPEATABLE_KEYS = frozenset(_FILTER_KEYS)
_NEGATABLE_KEYS = _REPEATABLE_KEYS
_DATE_KEYS = frozenset(("since", "until"))
_BEAD_TIER_VALUES = tuple(value.value for value in BeadTier)
_BEAD_STATUS_VALUES = bead_status_display_order()


@dataclass(frozen=True, slots=True)
class BeadFilterValues:
    """Validated values shared by bead query surfaces."""

    types: tuple[str, ...] = ()
    excluded_types: tuple[str, ...] = ()
    tiers: tuple[str, ...] = ()
    excluded_tiers: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    excluded_statuses: tuple[str, ...] = ()
    sizes: tuple[str, ...] = ()
    excluded_sizes: tuple[str, ...] = ()
    due: tuple[str, ...] = ()
    excluded_due: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    excluded_projects: tuple[str, ...] = ()
    assignees: tuple[str, ...] = ()
    excluded_assignees: tuple[str, ...] = ()
    owners: tuple[str, ...] = ()
    excluded_owners: tuple[str, ...] = ()
    models: tuple[str, ...] = ()
    excluded_models: tuple[str, ...] = ()
    has: tuple[str, ...] = ()
    excluded_has: tuple[str, ...] = ()
    bugs: tuple[str, ...] = ()
    excluded_bugs: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    excluded_labels: tuple[str, ...] = ()
    since_texts: tuple[str, ...] = ()
    excluded_since_texts: tuple[str, ...] = ()
    until_texts: tuple[str, ...] = ()
    excluded_until_texts: tuple[str, ...] = ()
    task_types: tuple[str, ...] = ()
    excluded_task_types: tuple[str, ...] = ()
    since: int | None = None
    until: int | None = None
    excluded_since: tuple[int, ...] = ()
    excluded_until: tuple[int, ...] = ()
    text: tuple[str, ...] = ()
    excluded_text: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Return whether this filter imposes no constraints."""

        return not any(
            (
                self.types,
                self.excluded_types,
                self.tiers,
                self.excluded_tiers,
                self.statuses,
                self.excluded_statuses,
                self.sizes,
                self.excluded_sizes,
                self.due,
                self.excluded_due,
                self.projects,
                self.excluded_projects,
                self.assignees,
                self.excluded_assignees,
                self.owners,
                self.excluded_owners,
                self.models,
                self.excluded_models,
                self.has,
                self.excluded_has,
                self.bugs,
                self.excluded_bugs,
                self.labels,
                self.excluded_labels,
                self.since_texts,
                self.excluded_since_texts,
                self.until_texts,
                self.excluded_until_texts,
                self.task_types,
                self.excluded_task_types,
                self.since is not None,
                self.until is not None,
                self.excluded_since,
                self.excluded_until,
                self.text,
                self.excluded_text,
            )
        )


class BeadFilterQueryError(FilterQueryError):
    """A bead-filter parse failure tied to an exact token span."""


def default_bead_filter_values() -> BeadFilterValues:
    """Return the committed startup filter for the Beads pane."""

    return BeadFilterValues(excluded_statuses=("closed",))


def parse_bead_filter_query(
    text: str,
    *,
    now: datetime | None = None,
) -> BeadFilterValues:
    """Parse a bead query into normalized, validated filter values."""

    repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    excluded_repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    date_terms: dict[str, list[tuple[str, FilterToken]]] = {
        key: [] for key in _DATE_KEYS
    }
    excluded_date_terms: dict[str, list[tuple[str, FilterToken]]] = {
        key: [] for key in _DATE_KEYS
    }
    text_terms: list[str] = []
    excluded_text_terms: list[str] = []

    for token in tokenize(text, error_type=BeadFilterQueryError):
        colon = unquoted_index(token, ":")
        if token.wholly_quoted or colon < 0:
            value = token.body
            if not value:
                raise _error("Free-text terms must not be empty", token)
            (excluded_text_terms if token.negated else text_terms).append(value)
            continue

        key_start = 1 if token.negated else 0
        key = token.value[key_start:colon].casefold()
        if key not in _FILTER_KEYS:
            raise unknown_key_error(
                key,
                token,
                keys=_FILTER_KEYS,
                error_type=BeadFilterQueryError,
            )

        value = token.value[colon + 1 :]
        value_quoted = token.quoted[colon + 1 :]
        if not value:
            raise _error(f"{key}: requires a value", token)
        parts = split_unquoted(value, value_quoted, ",")
        if any(not part for part in parts):
            raise _error(f"{key}: contains an empty value", token)
        _validate_static_values(key, parts, token)
        if key in _DATE_KEYS:
            if token.negated:
                excluded_date_terms[key].extend((part, token) for part in parts)
            else:
                date_terms[key].extend((part, token) for part in parts)
            continue
        if token.negated:
            excluded_repeated[key].extend(parts)
        else:
            repeated[key].extend(parts)

    reference = normalize_reference_time(now)
    since_texts, since, since_tokens = _parse_date_terms(
        date_terms["since"],
        now=reference,
        boundary="since",
    )
    until_texts, until, until_tokens = _parse_date_terms(
        date_terms["until"],
        now=reference,
        boundary="until",
    )
    if since is not None and until is not None and since > until:
        token = until_tokens[0] if until_tokens else since_tokens[0]
        raise _error("since: value must not be later than until: value", token)

    excluded_since_texts, _ignored_since, _ignored_since_tokens = _parse_date_terms(
        excluded_date_terms["since"],
        now=reference,
        boundary="since",
    )
    excluded_until_texts, _ignored_until, _ignored_until_tokens = _parse_date_terms(
        excluded_date_terms["until"],
        now=reference,
        boundary="until",
    )

    return BeadFilterValues(
        types=tuple(repeated["type"]),
        excluded_types=tuple(excluded_repeated["type"]),
        tiers=tuple(repeated["tier"]),
        excluded_tiers=tuple(excluded_repeated["tier"]),
        statuses=tuple(repeated["status"]),
        excluded_statuses=tuple(excluded_repeated["status"]),
        sizes=tuple(repeated["size"]),
        excluded_sizes=tuple(excluded_repeated["size"]),
        due=tuple(repeated["due"]),
        excluded_due=tuple(excluded_repeated["due"]),
        projects=tuple(repeated["project"]),
        excluded_projects=tuple(excluded_repeated["project"]),
        assignees=tuple(repeated["assignee"]),
        excluded_assignees=tuple(excluded_repeated["assignee"]),
        owners=tuple(repeated["owner"]),
        excluded_owners=tuple(excluded_repeated["owner"]),
        models=tuple(repeated["model"]),
        excluded_models=tuple(excluded_repeated["model"]),
        has=tuple(repeated["has"]),
        excluded_has=tuple(excluded_repeated["has"]),
        bugs=tuple(repeated["bug"]),
        excluded_bugs=tuple(excluded_repeated["bug"]),
        labels=tuple(repeated["label"]),
        excluded_labels=tuple(excluded_repeated["label"]),
        since_texts=since_texts,
        excluded_since_texts=excluded_since_texts,
        until_texts=until_texts,
        excluded_until_texts=excluded_until_texts,
        task_types=tuple(repeated["task_type"]),
        excluded_task_types=tuple(excluded_repeated["task_type"]),
        since=since,
        until=until,
        excluded_since=tuple(
            bound
            for _text, bound in _parse_date_bounds(
                excluded_date_terms["since"],
                now=reference,
                boundary="since",
            )
        ),
        excluded_until=tuple(
            bound
            for _text, bound in _parse_date_bounds(
                excluded_date_terms["until"],
                now=reference,
                boundary="until",
            )
        ),
        text=tuple(text_terms),
        excluded_text=tuple(excluded_text_terms),
    )


def to_query_tokens(values: BeadFilterValues) -> tuple[str, ...]:
    """Render values as canonical tokens in stable filter order."""

    tokens: list[str] = []
    for key, entries, excluded_entries in (
        ("type", values.types, values.excluded_types),
        ("tier", values.tiers, values.excluded_tiers),
        ("status", values.statuses, values.excluded_statuses),
        ("size", values.sizes, values.excluded_sizes),
        ("due", values.due, values.excluded_due),
        ("project", values.projects, values.excluded_projects),
        ("assignee", values.assignees, values.excluded_assignees),
        ("owner", values.owners, values.excluded_owners),
        ("model", values.models, values.excluded_models),
        ("has", values.has, values.excluded_has),
        ("bug", values.bugs, values.excluded_bugs),
        ("label", values.labels, values.excluded_labels),
        ("since", values.since_texts, values.excluded_since_texts),
        ("until", values.until_texts, values.excluded_until_texts),
        ("task_type", values.task_types, values.excluded_task_types),
    ):
        tokens.extend(f"{key}:{quote_value(value, keyed=True)}" for value in entries)
        tokens.extend(
            f"-{key}:{quote_value(value, keyed=True)}" for value in excluded_entries
        )
    tokens.extend(quote_value(term, keyed=False) for term in values.text)
    tokens.extend(f"-{quote_value(term, keyed=False)}" for term in values.excluded_text)
    return tuple(tokens)


def to_query_string(values: BeadFilterValues) -> str:
    """Render values as a canonical query string."""

    return " ".join(to_query_tokens(values))


def bead_completion_context(
    text: str,
    cursor: int,
) -> tuple[BeadCompletionKind, str, bool]:
    """Classify a bead-filter completion prefix."""

    kind, prefix, negated = completion_context(
        text,
        cursor,
        keys=_FILTER_KEYS,
        repeatable_keys=_REPEATABLE_KEYS,
        negatable_keys=_NEGATABLE_KEYS,
    )
    return kind, prefix, negated  # type: ignore[return-value]


def _validate_static_values(
    key: str,
    parts: tuple[str, ...],
    token: FilterToken,
) -> None:
    allowed: tuple[str, ...] | None = None
    if key == "type":
        allowed = BEAD_FILTER_TYPE_VALUES
    elif key == "tier":
        allowed = _BEAD_TIER_VALUES
    elif key == "status":
        allowed = (*_BEAD_STATUS_VALUES, *DERIVED_BEAD_STATUS_VALUES)
    elif key == "size":
        allowed = PHASE_SIZE_VALUES
    elif key == "due":
        allowed = BEAD_FLAG_DUE_VALUES
    elif key == "has":
        allowed = BEAD_HAS_VALUES
    if allowed is None:
        return
    allowed_folded = {value.casefold() for value in allowed}
    invalid = next(
        (part for part in parts if part.casefold() not in allowed_folded),
        None,
    )
    if invalid is not None:
        raise _error(
            f"{key}: value {invalid!r} must be one of {', '.join(allowed)}",
            token,
        )


def _parse_date_terms(
    terms: list[tuple[str, FilterToken]],
    *,
    now: datetime,
    boundary: TimeBoundary,
) -> tuple[tuple[str, ...], int | None, tuple[FilterToken, ...]]:
    parsed = _parse_date_bounds(terms, now=now, boundary=boundary)
    if not parsed:
        return ((), None, ())
    texts = tuple(text for text, _bound in parsed)
    bounds = tuple(bound for _text, bound in parsed)
    selected = max(bounds) if boundary == "since" else min(bounds)
    return (texts, selected, tuple(token for _text, token in terms))


def _parse_date_bounds(
    terms: list[tuple[str, FilterToken]],
    *,
    now: datetime,
    boundary: TimeBoundary,
) -> tuple[tuple[str, int], ...]:
    parsed: list[tuple[str, int]] = []
    for value, token in terms:
        try:
            bound = parse_time_bound(value).resolve(now=now, boundary=boundary)
        except VcsLogDateError as exc:
            raise _error(str(exc), token) from exc
        parsed.append((value, bound))
    return tuple(parsed)


def _error(message: str, token: FilterToken) -> BeadFilterQueryError:
    return error_for_token(
        message,
        token,
        error_type=BeadFilterQueryError,
    )  # type: ignore[return-value]


__all__ = [
    "BEAD_HAS_VALUES",
    "BEAD_FLAG_DUE_VALUES",
    "DERIVED_BEAD_STATUS_VALUES",
    "DEFAULT_BEAD_FILTER_QUERY",
    "BeadCompletionKind",
    "BeadFilterQueryError",
    "BeadFilterValues",
    "bead_completion_context",
    "default_bead_filter_values",
    "parse_bead_filter_query",
    "to_query_string",
    "to_query_tokens",
]
