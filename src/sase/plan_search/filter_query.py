"""Pure query-language helpers for the Artifacts plans filter bar."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

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
from sase.vcs_log.dates import (
    TimeBoundary,
    VcsLogDateError,
    normalize_reference_time,
    parse_time_bound,
)

PlanCompletionKind = Literal[
    "key",
    "kind",
    "status",
    "tier",
    "project",
    "since",
    "until",
    "text",
]

_FILTER_KEYS = ("kind", "status", "tier", "project", "since", "until")
_REPEATABLE_KEYS = frozenset(("kind", "status", "tier", "project"))
_NEGATABLE_KEYS = _REPEATABLE_KEYS
_ROW_KINDS = frozenset(("proposal", "epic", "phase", "archive"))


@dataclass(frozen=True)
class PlanFilterValues:
    """Validated values shared by the plans pane and query editor."""

    kinds: tuple[str, ...] = ()
    excluded_kinds: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    excluded_statuses: tuple[str, ...] = ()
    tiers: tuple[str, ...] = ()
    excluded_tiers: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    excluded_projects: tuple[str, ...] = ()
    since_text: str = ""
    until_text: str = ""
    since: int | None = None
    until: int | None = None
    text: tuple[str, ...] = ()
    excluded_text: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Return whether this filter imposes no constraints."""
        return not any(
            (
                self.kinds,
                self.excluded_kinds,
                self.statuses,
                self.excluded_statuses,
                self.tiers,
                self.excluded_tiers,
                self.projects,
                self.excluded_projects,
                self.since_text,
                self.until_text,
                self.since is not None,
                self.until is not None,
                self.text,
                self.excluded_text,
            )
        )


class PlanFilterQueryError(FilterQueryError):
    """A plan-filter parse failure tied to an exact token span."""


def parse_plan_filter_query(
    text: str,
    *,
    now: datetime | None = None,
) -> PlanFilterValues:
    """Parse a plans-filter query into validated filter values."""
    repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    excluded_repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    singles: dict[str, tuple[str, FilterToken]] = {}
    text_terms: list[str] = []
    excluded_text_terms: list[str] = []

    for token in tokenize(text, error_type=PlanFilterQueryError):
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
                error_type=PlanFilterQueryError,
            )
        if token.negated and key not in _NEGATABLE_KEYS:
            raise _error(f"{key}: may not be negated", token)

        value = token.value[colon + 1 :]
        value_quoted = token.quoted[colon + 1 :]
        if not value:
            raise _error(f"{key}: requires a value", token)

        if key in _REPEATABLE_KEYS:
            parts = split_unquoted(value, value_quoted, ",")
            if any(not part for part in parts):
                raise _error(f"{key}: contains an empty value", token)
            if key == "kind":
                invalid = next(
                    (part for part in parts if part.casefold() not in _ROW_KINDS),
                    None,
                )
                if invalid is not None:
                    allowed = ", ".join(sorted(_ROW_KINDS))
                    raise _error(
                        f"kind: value {invalid!r} must be one of {allowed}",
                        token,
                    )
            (excluded_repeated if token.negated else repeated)[key].extend(parts)
            continue

        if key in singles:
            raise _error(f"{key}: may only appear once", token)
        singles[key] = (value, token)

    reference = normalize_reference_time(now)
    since_text, since, _since_token = _parse_date_value(
        "since",
        singles,
        now=reference,
        boundary="since",
    )
    until_text, until, until_token = _parse_date_value(
        "until",
        singles,
        now=reference,
        boundary="until",
    )
    if since is not None and until is not None and since > until:
        assert until_token is not None
        raise _error("since: value must not be later than until: value", until_token)

    return PlanFilterValues(
        kinds=tuple(repeated["kind"]),
        excluded_kinds=tuple(excluded_repeated["kind"]),
        statuses=tuple(repeated["status"]),
        excluded_statuses=tuple(excluded_repeated["status"]),
        tiers=tuple(repeated["tier"]),
        excluded_tiers=tuple(excluded_repeated["tier"]),
        projects=tuple(repeated["project"]),
        excluded_projects=tuple(excluded_repeated["project"]),
        since_text=since_text,
        until_text=until_text,
        since=since,
        until=until,
        text=tuple(text_terms),
        excluded_text=tuple(excluded_text_terms),
    )


def to_query_tokens(values: PlanFilterValues) -> tuple[str, ...]:
    """Render *values* as canonical tokens in stable filter order."""
    tokens: list[str] = []
    for key, entries, excluded_entries in (
        ("kind", values.kinds, values.excluded_kinds),
        ("status", values.statuses, values.excluded_statuses),
        ("tier", values.tiers, values.excluded_tiers),
        ("project", values.projects, values.excluded_projects),
    ):
        tokens.extend(f"{key}:{quote_value(value, keyed=True)}" for value in entries)
        tokens.extend(
            f"-{key}:{quote_value(value, keyed=True)}" for value in excluded_entries
        )
    if values.since_text:
        tokens.append(f"since:{quote_value(values.since_text, keyed=True)}")
    if values.until_text:
        tokens.append(f"until:{quote_value(values.until_text, keyed=True)}")
    tokens.extend(quote_value(term, keyed=False) for term in values.text)
    tokens.extend(f"-{quote_value(term, keyed=False)}" for term in values.excluded_text)
    return tuple(tokens)


def to_query_string(values: PlanFilterValues) -> str:
    """Render *values* as a canonical query string."""
    return " ".join(to_query_tokens(values))


def plan_completion_context(
    text: str,
    cursor: int,
) -> tuple[PlanCompletionKind, str, bool]:
    """Classify a completion prefix and preserve unary exclusion state."""
    kind, prefix, negated = completion_context(
        text,
        cursor,
        keys=_FILTER_KEYS,
        repeatable_keys=_REPEATABLE_KEYS,
        negatable_keys=_NEGATABLE_KEYS,
    )
    return kind, prefix, negated  # type: ignore[return-value]


def _parse_date_value(
    key: str,
    singles: Mapping[str, tuple[str, FilterToken]],
    *,
    now: datetime,
    boundary: TimeBoundary,
) -> tuple[str, int | None, FilterToken | None]:
    if key not in singles:
        return ("", None, None)
    value, token = singles[key]
    try:
        parsed = parse_time_bound(value).resolve(now=now, boundary=boundary)
    except VcsLogDateError as exc:
        raise _error(str(exc), token) from exc
    return (value, parsed, token)


def _error(message: str, token: FilterToken) -> PlanFilterQueryError:
    return error_for_token(
        message,
        token,
        error_type=PlanFilterQueryError,
    )  # type: ignore[return-value]


__all__ = [
    "PlanCompletionKind",
    "PlanFilterQueryError",
    "PlanFilterValues",
    "parse_plan_filter_query",
    "plan_completion_context",
    "to_query_string",
    "to_query_tokens",
]
