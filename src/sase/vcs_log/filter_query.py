"""Pure query-language helpers for the Artifacts commits filter bar."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sase.core.vcs_log_wire import CommitOrigin
from sase.filter_tokens import (
    FilterQueryError,
    FilterToken,
    completion_context as token_completion_context,
    error_for_token,
    quote_value,
    split_unquoted,
    tokenize,
    unknown_key_error,
    unquoted_index,
)
from sase.vcs_log.dates import (
    TimeBound,
    VcsLogDateError,
    normalize_reference_time,
    parse_time_bound,
)
from sase.vcs_provider._types import MergeVisibility
from sase.vcs_log.models import CommitFilterSpec, CommitFilters

#: Query-level sentinel meaning "do not apply a final row cap". The collection
#: adapter passes this through as ``0`` and the VCS-log backend translates it to
#: its internal unlimited sentinel.
UNLIMITED_COMMIT_LOG_LIMIT = 0

CompletionKind = Literal[
    "key",
    "project",
    "repo",
    "author",
    "origin",
    "type",
    "sha",
    "since",
    "until",
    "sidecar",
    "merges",
    "limit",
    "text",
]
_FILTER_KEYS = (
    "project",
    "repo",
    "author",
    "origin",
    "type",
    "sha",
    "since",
    "until",
    "sidecar",
    "merges",
    "limit",
)
_REPEATABLE_KEYS = frozenset(("repo", "author", "origin", "type", "sha"))
_NEGATABLE_KEYS = frozenset(("repo", "author", "origin", "type", "sha"))
_NON_NEGATIVE_INTEGER_RE = re.compile(r"^\d+$")
#: Canonical commit-origin values accepted by the ``origin:`` filter key.
#: Mirrors ``sase.core.vcs_log_wire.CommitOrigin``.
_ORIGIN_VALUES: frozenset[str] = frozenset(("stitch", "auto", "manual"))


class CommitFilterQueryError(FilterQueryError):
    """A commit-filter parse failure tied to an exact token span."""


@dataclass(frozen=True)
class CommitLogFilterValues:
    """Validated values shared by the commits pane and query editor."""

    project: str | None = None
    authors: tuple[str, ...] = ()
    excluded_authors: tuple[str, ...] = ()
    origins: tuple[CommitOrigin, ...] = ()
    excluded_origins: tuple[CommitOrigin, ...] = ()
    types: tuple[str, ...] = ()
    excluded_types: tuple[str, ...] = ()
    since_text: str = ""
    until_text: str = ""
    since: TimeBound | None = None
    until: TimeBound | None = None
    repos: tuple[str, ...] = ()
    excluded_repos: tuple[str, ...] = ()
    shas: tuple[str, ...] = ()
    excluded_shas: tuple[str, ...] = ()
    sidecar: bool = True
    merges: MergeVisibility = "hide"
    limit: int = UNLIMITED_COMMIT_LOG_LIMIT
    text: tuple[str, ...] = ()
    excluded_text: tuple[str, ...] = ()

    def backend_filters(self, *, now: datetime | None = None) -> CommitFilters:
        """Return the provider-neutral filters pushed into ``run_vcs_log``."""
        since, until = _resolve_bounds(self, now=now)
        return CommitFilters(
            since=since,
            until=until,
            authors=self.authors,
            merges=self.merges,
        )

    def backend_filter_spec(self) -> CommitFilterSpec:
        """Return stable filters for collection-time date resolution."""
        return CommitFilterSpec(
            since=self.since,
            until=self.until,
            authors=self.authors,
            merges=self.merges,
        )


def parse_commit_filter_query(
    text: str,
    *,
    now: datetime | None = None,
) -> CommitLogFilterValues:
    """Parse a commit-filter query into validated filter values."""
    repos: list[str] = []
    excluded_repos: list[str] = []
    shas: list[str] = []
    excluded_shas: list[str] = []
    authors: list[str] = []
    excluded_authors: list[str] = []
    origins: list[CommitOrigin] = []
    excluded_origins: list[CommitOrigin] = []
    types: list[str] = []
    excluded_types: list[str] = []
    text_terms: list[str] = []
    excluded_text_terms: list[str] = []
    singles: dict[str, tuple[str, FilterToken]] = {}

    for token in tokenize(text, error_type=CommitFilterQueryError):
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
                error_type=CommitFilterQueryError,
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
            if key == "repo":
                (excluded_repos if token.negated else repos).extend(parts)
            elif key == "author":
                (excluded_authors if token.negated else authors).extend(parts)
            elif key == "origin":
                origin_parts = [_parse_origin_value(part, token) for part in parts]
                (excluded_origins if token.negated else origins).extend(origin_parts)
            elif key == "sha":
                (excluded_shas if token.negated else shas).extend(parts)
            else:
                type_parts = [_parse_type_value(part, token) for part in parts]
                (excluded_types if token.negated else types).extend(type_parts)
            continue

        if key in singles:
            raise _error(f"{key}: may only appear once", token)
        if key == "project" and len(split_unquoted(value, value_quoted, ",")) > 1:
            raise _error("project: does not accept comma-separated values", token)
        singles[key] = (value, token)

    since_text, since, _since_token = _parse_date_value("since", singles)
    until_text, until, until_token = _parse_date_value("until", singles)
    if since is not None and until is not None:
        reference = normalize_reference_time(now)
        if since.resolve(now=reference, boundary="since") > until.resolve(
            now=reference,
            boundary="until",
        ):
            assert until_token is not None
            raise _error(
                "since: value must not be later than until: value",
                until_token,
            )

    limit = UNLIMITED_COMMIT_LOG_LIMIT
    if "limit" in singles:
        limit_text, limit_token = singles["limit"]
        if limit_text.casefold() == "all":
            limit = 0
        elif _NON_NEGATIVE_INTEGER_RE.fullmatch(limit_text):
            limit = int(limit_text)
        else:
            raise _error("limit: must be a non-negative integer or 'all'", limit_token)

    sidecar = True
    if "sidecar" in singles:
        sidecar_text, sidecar_token = singles["sidecar"]
        folded = sidecar_text.casefold()
        if folded not in {"true", "false"}:
            raise _error("sidecar: must be 'true' or 'false'", sidecar_token)
        sidecar = folded == "true"

    merges: MergeVisibility = "hide"
    if "merges" in singles:
        merges_text, merges_token = singles["merges"]
        merges = _parse_merges_value(merges_text, merges_token)

    project = singles["project"][0] if "project" in singles else None

    return CommitLogFilterValues(
        project=project,
        authors=tuple(authors),
        excluded_authors=tuple(excluded_authors),
        origins=tuple(origins),
        excluded_origins=tuple(excluded_origins),
        types=tuple(types),
        excluded_types=tuple(excluded_types),
        since_text=since_text,
        until_text=until_text,
        since=since,
        until=until,
        repos=tuple(repos),
        excluded_repos=tuple(excluded_repos),
        shas=tuple(shas),
        excluded_shas=tuple(excluded_shas),
        sidecar=sidecar,
        merges=merges,
        limit=limit,
        text=tuple(text_terms),
        excluded_text=tuple(excluded_text_terms),
    )


def to_query_tokens(
    values: CommitLogFilterValues,
) -> tuple[str, ...]:
    """Render *values* as canonical tokens in stable filter order."""
    tokens = (
        [f"project:{quote_value(values.project, keyed=True)}"] if values.project else []
    )
    tokens.extend(f"repo:{quote_value(value, keyed=True)}" for value in values.repos)
    tokens.extend(
        f"-repo:{quote_value(value, keyed=True)}" for value in values.excluded_repos
    )
    tokens.extend(f"sha:{quote_value(value, keyed=True)}" for value in values.shas)
    tokens.extend(
        f"-sha:{quote_value(value, keyed=True)}" for value in values.excluded_shas
    )
    tokens.extend(
        f"author:{quote_value(value, keyed=True)}" for value in values.authors
    )
    tokens.extend(
        f"-author:{quote_value(value, keyed=True)}" for value in values.excluded_authors
    )
    tokens.extend(
        f"origin:{quote_value(value, keyed=True)}" for value in values.origins
    )
    tokens.extend(
        f"-origin:{quote_value(value, keyed=True)}" for value in values.excluded_origins
    )
    tokens.extend(f"type:{quote_value(value, keyed=True)}" for value in values.types)
    tokens.extend(
        f"-type:{quote_value(value, keyed=True)}" for value in values.excluded_types
    )
    tokens.append(f"sidecar:{str(values.sidecar).lower()}")
    tokens.append(f"merges:{values.merges}")
    if values.since_text:
        tokens.append(f"since:{quote_value(values.since_text, keyed=True)}")
    if values.until_text:
        tokens.append(f"until:{quote_value(values.until_text, keyed=True)}")
    if values.limit > 0:
        tokens.append(f"limit:{values.limit}")
    tokens.extend(quote_value(term, keyed=False) for term in values.text)
    tokens.extend(f"-{quote_value(term, keyed=False)}" for term in values.excluded_text)
    return tuple(tokens)


def to_query_string(values: CommitLogFilterValues) -> str:
    """Render *values* as a canonical query string."""
    return " ".join(to_query_tokens(values))


def commit_repo_matches(
    values: CommitLogFilterValues,
    repo: str,
    aliases: Iterable[str] = (),
) -> bool:
    """Return whether one canonical repository survives repo constraints."""
    labels = frozenset(value.casefold() for value in (repo, *aliases))
    wanted = frozenset(value.casefold() for value in values.repos)
    excluded = frozenset(value.casefold() for value in values.excluded_repos)
    return (not wanted or not wanted.isdisjoint(labels)) and excluded.isdisjoint(labels)


def completion_context(
    text: str,
    cursor: int,
) -> tuple[CompletionKind, str, bool]:
    """Classify a completion prefix and preserve unary exclusion state."""
    kind, prefix, negated = token_completion_context(
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
) -> tuple[str, TimeBound | None, FilterToken | None]:
    if key not in singles:
        return ("", None, None)
    value, token = singles[key]
    try:
        parsed = parse_time_bound(value)
    except VcsLogDateError as exc:
        raise _error(str(exc), token) from exc
    return (value, parsed, token)


def _resolve_bounds(
    values: CommitLogFilterValues,
    *,
    now: datetime | None,
) -> tuple[int | None, int | None]:
    if values.since is None and values.until is None:
        return (None, None)
    reference = normalize_reference_time(now)
    since = (
        values.since.resolve(now=reference, boundary="since")
        if values.since is not None
        else None
    )
    until = (
        values.until.resolve(now=reference, boundary="until")
        if values.until is not None
        else None
    )
    return (since, until)


def _parse_merges_value(
    value: str,
    token: FilterToken,
) -> MergeVisibility:
    folded = value.casefold()
    if folded == "hide":
        return "hide"
    if folded == "show":
        return "show"
    if folded == "only":
        return "only"
    raise _error("merges: must be 'hide', 'show', or 'only'", token)


def _parse_origin_value(value: str, token: FilterToken) -> CommitOrigin:
    folded = value.casefold()
    if folded in _ORIGIN_VALUES:
        return folded  # type: ignore[return-value]
    raise _error("origin: must be 'stitch', 'auto', or 'manual'", token)


def _parse_type_value(value: str, token: FilterToken) -> str:
    folded = " ".join(value.split()).casefold()
    if not folded:
        raise _error("type: contains an empty value", token)
    return "automatic" if folded == "auto" else folded


def _error(message: str, token: FilterToken) -> CommitFilterQueryError:
    return error_for_token(
        message,
        token,
        error_type=CommitFilterQueryError,
    )  # type: ignore[return-value]


__all__ = [
    "UNLIMITED_COMMIT_LOG_LIMIT",
    "CommitFilterQueryError",
    "CommitLogFilterValues",
    "CompletionKind",
    "commit_repo_matches",
    "completion_context",
    "parse_commit_filter_query",
    "to_query_string",
    "to_query_tokens",
]
