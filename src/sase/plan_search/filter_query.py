"""Pure query-language helpers for the Artifacts plans filter bar."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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
from sase.vcs_log.dates import VcsLogDateError, parse_time_bound

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
_ROW_KINDS = frozenset(("proposal", "epic", "phase", "archive"))


@dataclass(frozen=True)
class PlanFilterValues:
    """Validated values shared by the plans pane and query editor."""

    kinds: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()
    tiers: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    since_text: str = ""
    until_text: str = ""
    since: int | None = None
    until: int | None = None
    text: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        """Return whether this filter imposes no constraints."""
        return not any(
            (
                self.kinds,
                self.statuses,
                self.tiers,
                self.projects,
                self.since_text,
                self.until_text,
                self.since is not None,
                self.until is not None,
                self.text,
            )
        )


class PlanFilterQueryError(FilterQueryError):
    """A plan-filter parse failure tied to an exact token span."""


def parse_plan_filter_query(text: str) -> PlanFilterValues:
    """Parse a plans-filter query into validated filter values."""
    repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    singles: dict[str, tuple[str, FilterToken]] = {}
    text_terms: list[str] = []

    for token in tokenize(text, error_type=PlanFilterQueryError):
        colon = unquoted_index(token, ":")
        if token.wholly_quoted or colon < 0:
            if not token.value:
                raise _error("Free-text terms must not be empty", token)
            text_terms.append(token.value)
            continue

        key = token.value[:colon].casefold()
        if key not in _FILTER_KEYS:
            raise unknown_key_error(
                key,
                token,
                keys=_FILTER_KEYS,
                error_type=PlanFilterQueryError,
            )

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
            repeated[key].extend(parts)
            continue

        if key in singles:
            raise _error(f"{key}: may only appear once", token)
        singles[key] = (value, token)

    since_text, since, _since_token = _parse_date_value("since", singles)
    until_text, until, until_token = _parse_date_value("until", singles)
    if since is not None and until is not None and since > until:
        assert until_token is not None
        raise _error("since: value must not be later than until: value", until_token)

    return PlanFilterValues(
        kinds=tuple(repeated["kind"]),
        statuses=tuple(repeated["status"]),
        tiers=tuple(repeated["tier"]),
        projects=tuple(repeated["project"]),
        since_text=since_text,
        until_text=until_text,
        since=since,
        until=until,
        text=tuple(text_terms),
    )


def to_query_tokens(values: PlanFilterValues) -> tuple[str, ...]:
    """Render *values* as canonical tokens in stable filter order."""
    tokens: list[str] = []
    for key, entries in (
        ("kind", values.kinds),
        ("status", values.statuses),
        ("tier", values.tiers),
        ("project", values.projects),
    ):
        tokens.extend(f"{key}:{quote_value(value, keyed=True)}" for value in entries)
    if values.since_text:
        tokens.append(f"since:{quote_value(values.since_text, keyed=True)}")
    if values.until_text:
        tokens.append(f"until:{quote_value(values.until_text, keyed=True)}")
    tokens.extend(quote_value(term, keyed=False) for term in values.text)
    return tuple(tokens)


def to_query_string(values: PlanFilterValues) -> str:
    """Render *values* as a canonical query string."""
    return " ".join(to_query_tokens(values))


def plan_completion_context(
    text: str,
    cursor: int,
) -> tuple[PlanCompletionKind, str]:
    """Classify the token prefix immediately before *cursor*."""
    kind, prefix = completion_context(
        text,
        cursor,
        keys=_FILTER_KEYS,
        repeatable_keys=_REPEATABLE_KEYS,
    )
    return kind, prefix  # type: ignore[return-value]


def _parse_date_value(
    key: str,
    singles: Mapping[str, tuple[str, FilterToken]],
) -> tuple[str, int | None, FilterToken | None]:
    if key not in singles:
        return ("", None, None)
    value, token = singles[key]
    try:
        parsed = parse_time_bound(value)
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
