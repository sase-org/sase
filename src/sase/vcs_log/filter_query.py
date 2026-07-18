"""Pure query-language helpers for the Artifacts commits filter bar."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from sase.core.vcs_log_wire import AggregatedCommitWire
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
from sase.vcs_log.dates import VcsLogDateError, parse_time_bound
from sase.vcs_log.models import CommitFilters

DEFAULT_COMMIT_LOG_LIMIT = 40

CompletionKind = Literal[
    "key",
    "repo",
    "author",
    "since",
    "until",
    "limit",
    "text",
]
RepoAliases = Mapping[str, Iterable[str]]

_FILTER_KEYS = ("repo", "author", "since", "until", "limit")
_REPEATABLE_KEYS = frozenset(("repo", "author"))
_NON_NEGATIVE_INTEGER_RE = re.compile(r"^\d+$")


class CommitFilterQueryError(FilterQueryError):
    """A commit-filter parse failure tied to an exact token span."""


@dataclass(frozen=True)
class CommitLogFilterValues:
    """Validated values shared by the commits pane and query editor."""

    authors: tuple[str, ...] = ()
    since_text: str = ""
    until_text: str = ""
    since: int | None = None
    until: int | None = None
    repos: tuple[str, ...] = ()
    limit: int = DEFAULT_COMMIT_LOG_LIMIT
    text: tuple[str, ...] = ()

    def backend_filters(self) -> CommitFilters:
        """Return the provider-neutral filters pushed into ``run_vcs_log``."""
        return CommitFilters(
            since=self.since,
            until=self.until,
            authors=self.authors,
        )


def parse_commit_filter_query(text: str) -> CommitLogFilterValues:
    """Parse a commit-filter query into validated filter values."""
    repos: list[str] = []
    authors: list[str] = []
    text_terms: list[str] = []
    singles: dict[str, tuple[str, FilterToken]] = {}

    for token in tokenize(text, error_type=CommitFilterQueryError):
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
                error_type=CommitFilterQueryError,
            )

        value = token.value[colon + 1 :]
        value_quoted = token.quoted[colon + 1 :]
        if not value:
            raise _error(f"{key}: requires a value", token)

        if key in _REPEATABLE_KEYS:
            parts = split_unquoted(value, value_quoted, ",")
            if any(not part for part in parts):
                raise _error(f"{key}: contains an empty value", token)
            (repos if key == "repo" else authors).extend(parts)
            continue

        if key in singles:
            raise _error(f"{key}: may only appear once", token)
        singles[key] = (value, token)

    since_text, since, _since_token = _parse_date_value("since", singles)
    until_text, until, until_token = _parse_date_value("until", singles)
    if since is not None and until is not None and since > until:
        assert until_token is not None
        raise _error("since: value must not be later than until: value", until_token)

    limit = DEFAULT_COMMIT_LOG_LIMIT
    if "limit" in singles:
        limit_text, limit_token = singles["limit"]
        if limit_text.casefold() == "all":
            limit = 0
        elif _NON_NEGATIVE_INTEGER_RE.fullmatch(limit_text):
            limit = int(limit_text)
        else:
            raise _error("limit: must be a non-negative integer or 'all'", limit_token)

    return CommitLogFilterValues(
        authors=tuple(authors),
        since_text=since_text,
        until_text=until_text,
        since=since,
        until=until,
        repos=tuple(repos),
        limit=limit,
        text=tuple(text_terms),
    )


def to_query_tokens(values: CommitLogFilterValues) -> tuple[str, ...]:
    """Render *values* as canonical tokens in stable filter order."""
    tokens = [f"repo:{quote_value(value, keyed=True)}" for value in values.repos]
    tokens.extend(
        f"author:{quote_value(value, keyed=True)}" for value in values.authors
    )
    if values.since_text:
        tokens.append(f"since:{quote_value(values.since_text, keyed=True)}")
    if values.until_text:
        tokens.append(f"until:{quote_value(values.until_text, keyed=True)}")
    if values.limit != DEFAULT_COMMIT_LOG_LIMIT:
        tokens.append(f"limit:{values.limit or 'all'}")
    tokens.extend(quote_value(term, keyed=False) for term in values.text)
    return tuple(tokens)


def to_query_string(values: CommitLogFilterValues) -> str:
    """Render *values* as a canonical query string."""
    return " ".join(to_query_tokens(values))


def compile_commit_matcher(
    values: CommitLogFilterValues,
    *,
    repo_aliases: RepoAliases | None = None,
) -> Callable[[AggregatedCommitWire], bool]:
    """Compile *values* into a cheap, reusable in-memory predicate."""
    wanted_repos = frozenset(value.casefold() for value in values.repos)
    wanted_authors = tuple(value.casefold() for value in values.authors)
    wanted_text = tuple(value.casefold() for value in values.text)
    aliases_by_repo = {
        name.casefold(): frozenset(alias.casefold() for alias in aliases)
        for name, aliases in (repo_aliases or {}).items()
    }
    since = values.since
    until = values.until

    def matches(entry: AggregatedCommitWire) -> bool:
        commit = entry.commit
        repo_name = entry.repo.casefold()
        if wanted_repos and not wanted_repos.intersection(
            (repo_name, *aliases_by_repo.get(repo_name, ()))
        ):
            return False
        if wanted_authors:
            author_name = commit.author_name.casefold()
            author_email = commit.author_email.casefold()
            if not any(
                needle in author_name or needle in author_email
                for needle in wanted_authors
            ):
                return False
        if since is not None and commit.timestamp < since:
            return False
        if until is not None and commit.timestamp > until:
            return False
        subject = commit.subject.casefold()
        return all(term in subject for term in wanted_text)

    return matches


def completion_context(text: str, cursor: int) -> tuple[CompletionKind, str]:
    """Classify the token prefix immediately before *cursor*."""
    kind, prefix = token_completion_context(
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


def _error(message: str, token: FilterToken) -> CommitFilterQueryError:
    return error_for_token(
        message,
        token,
        error_type=CommitFilterQueryError,
    )  # type: ignore[return-value]


__all__ = [
    "DEFAULT_COMMIT_LOG_LIMIT",
    "CommitFilterQueryError",
    "CommitLogFilterValues",
    "CompletionKind",
    "compile_commit_matcher",
    "completion_context",
    "parse_commit_filter_query",
    "to_query_string",
    "to_query_tokens",
]
