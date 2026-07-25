"""Pure query-language helpers for chat transcript filtering."""

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

ChatCompletionKind = Literal[
    "key",
    "provenance",
    "machine",
    "project",
    "agent",
    "workflow",
    "since",
    "until",
    "text",
]

_FILTER_KEYS = (
    "provenance",
    "machine",
    "project",
    "agent",
    "workflow",
    "since",
    "until",
)
_REPEATABLE_KEYS = frozenset(("provenance", "machine", "project", "agent", "workflow"))
_PROVENANCE_VALUES = frozenset(("local", "shared", "remote", "unknown"))


@dataclass(frozen=True, slots=True)
class ChatFilterValues:
    """Validated values shared by the Chats pane and query editor."""

    provenances: tuple[str, ...] = ()
    machines: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    workflows: tuple[str, ...] = ()
    since_text: str = ""
    until_text: str = ""
    since: int | None = None
    until: int | None = None
    text: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.provenances,
                self.machines,
                self.projects,
                self.agents,
                self.workflows,
                self.since_text,
                self.until_text,
                self.since is not None,
                self.until is not None,
                self.text,
            )
        )


class ChatFilterQueryError(FilterQueryError):
    """A chat-filter parse failure tied to an exact token span."""


def parse_chat_filter_query(
    text: str,
    *,
    now: datetime | None = None,
) -> ChatFilterValues:
    """Parse a Chats query into normalized, validated filter values."""

    repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    singles: dict[str, tuple[str, FilterToken]] = {}
    text_terms: list[str] = []

    for token in tokenize(text, error_type=ChatFilterQueryError):
        colon = unquoted_index(token, ":")
        if token.wholly_quoted or colon < 0:
            if token.negated:
                raise _error("Chat filters do not support negation", token)
            value = token.body
            if not value:
                raise _error("Free-text terms must not be empty", token)
            text_terms.append(value)
            continue

        if token.negated:
            raise _error("Chat filters do not support negation", token)
        key = token.value[:colon].casefold()
        if key not in _FILTER_KEYS:
            raise unknown_key_error(
                key,
                token,
                keys=_FILTER_KEYS,
                error_type=ChatFilterQueryError,
            )
        value = token.value[colon + 1 :]
        value_quoted = token.quoted[colon + 1 :]
        if not value:
            raise _error(f"{key}: requires a value", token)

        if key in _REPEATABLE_KEYS:
            parts = split_unquoted(value, value_quoted, ",")
            if any(not part for part in parts):
                raise _error(f"{key}: contains an empty value", token)
            if key == "provenance":
                invalid = next(
                    (
                        part
                        for part in parts
                        if part.casefold() not in _PROVENANCE_VALUES
                    ),
                    None,
                )
                if invalid is not None:
                    allowed = ", ".join(sorted(_PROVENANCE_VALUES))
                    raise _error(
                        f"provenance: value {invalid!r} must be one of {allowed}",
                        token,
                    )
            repeated[key].extend(parts)
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

    return ChatFilterValues(
        provenances=tuple(value.casefold() for value in repeated["provenance"]),
        machines=tuple(repeated["machine"]),
        projects=tuple(repeated["project"]),
        agents=tuple(repeated["agent"]),
        workflows=tuple(repeated["workflow"]),
        since_text=since_text,
        until_text=until_text,
        since=since,
        until=until,
        text=tuple(text_terms),
    )


def to_query_tokens(values: ChatFilterValues) -> tuple[str, ...]:
    """Render values as canonical tokens in stable filter order."""

    tokens: list[str] = []
    for key, entries in (
        ("provenance", values.provenances),
        ("machine", values.machines),
        ("project", values.projects),
        ("agent", values.agents),
        ("workflow", values.workflows),
    ):
        tokens.extend(f"{key}:{quote_value(value, keyed=True)}" for value in entries)
    if values.since_text:
        tokens.append(f"since:{quote_value(values.since_text, keyed=True)}")
    if values.until_text:
        tokens.append(f"until:{quote_value(values.until_text, keyed=True)}")
    tokens.extend(quote_value(term, keyed=False) for term in values.text)
    return tuple(tokens)


def to_query_string(values: ChatFilterValues) -> str:
    return " ".join(to_query_tokens(values))


def chat_completion_context(
    text: str,
    cursor: int,
) -> tuple[ChatCompletionKind, str, bool]:
    kind, prefix, negated = completion_context(
        text,
        cursor,
        keys=_FILTER_KEYS,
        repeatable_keys=_REPEATABLE_KEYS,
        negatable_keys=frozenset(),
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


def _error(message: str, token: FilterToken) -> ChatFilterQueryError:
    return error_for_token(
        message,
        token,
        error_type=ChatFilterQueryError,
    )  # type: ignore[return-value]


__all__ = [
    "ChatCompletionKind",
    "ChatFilterQueryError",
    "ChatFilterValues",
    "chat_completion_context",
    "parse_chat_filter_query",
    "to_query_string",
    "to_query_tokens",
]
