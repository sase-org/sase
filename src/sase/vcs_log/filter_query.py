"""Pure query-language helpers for the Artifacts commits filter bar."""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from sase.core.vcs_log_wire import AggregatedCommitWire
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


class CommitFilterQueryError(ValueError):
    """A parse failure tied to an exact token span in the source query."""

    def __init__(self, message: str, *, token: str, start: int, end: int) -> None:
        super().__init__(message)
        self.message = message
        self.token = token
        self.bad_token = token
        self.start = start
        self.end = end
        self.span = (start, end)


@dataclass(frozen=True)
class _Token:
    value: str
    raw: str
    start: int
    end: int
    quoted: tuple[bool, ...]
    wholly_quoted: bool


def parse_commit_filter_query(text: str) -> CommitLogFilterValues:
    """Parse a commit-filter query into validated filter values.

    Tokens are whitespace-separated, while double quotes preserve whitespace.
    ``repo`` and ``author`` may be repeated or contain unquoted comma lists.
    Unknown ``key:`` prefixes are errors; other tokens are subject substrings.
    """
    repos: list[str] = []
    authors: list[str] = []
    text_terms: list[str] = []
    singles: dict[str, tuple[str, _Token]] = {}

    for token in _tokenize(text):
        colon = _unquoted_index(token, ":")
        if token.wholly_quoted or colon < 0:
            if not token.value:
                raise _error("Free-text terms must not be empty", token)
            text_terms.append(token.value)
            continue

        key = token.value[:colon].casefold()
        if key not in _FILTER_KEYS:
            raise _unknown_key_error(key, token)

        value = token.value[colon + 1 :]
        value_quoted = token.quoted[colon + 1 :]
        if not value:
            raise _error(f"{key}: requires a value", token)

        if key in _REPEATABLE_KEYS:
            parts = _split_unquoted(value, value_quoted, ",")
            if any(not part for part in parts):
                raise _error(f"{key}: contains an empty value", token)
            (repos if key == "repo" else authors).extend(parts)
            continue

        if key in singles:
            raise _error(f"{key}: may only appear once", token)
        singles[key] = (value, token)

    since_text, since, since_token = _parse_date_value("since", singles)
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
    tokens = [f"repo:{_quote_value(value, keyed=True)}" for value in values.repos]
    tokens.extend(
        f"author:{_quote_value(value, keyed=True)}" for value in values.authors
    )
    if values.since_text:
        tokens.append(f"since:{_quote_value(values.since_text, keyed=True)}")
    if values.until_text:
        tokens.append(f"until:{_quote_value(values.until_text, keyed=True)}")
    if values.limit != DEFAULT_COMMIT_LOG_LIMIT:
        tokens.append(f"limit:{values.limit or 'all'}")
    tokens.extend(_quote_value(term, keyed=False) for term in values.text)
    return tuple(tokens)


def to_query_string(values: CommitLogFilterValues) -> str:
    """Render *values* as a canonical query string."""
    return " ".join(to_query_tokens(values))


def compile_commit_matcher(
    values: CommitLogFilterValues,
    *,
    repo_aliases: RepoAliases | None = None,
) -> Callable[[AggregatedCommitWire], bool]:
    """Compile *values* into a cheap, reusable in-memory predicate.

    ``repo_aliases`` maps canonical repo names to the aliases accepted for that
    repo. The limit is deliberately not applied: callers cap rows after
    filtering.
    """
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
    """Classify the token prefix immediately before *cursor*.

    The returned prefix is decoded (without quotes). For repeatable comma-list
    values, it is the portion after the last unquoted comma.
    """
    cursor = min(max(cursor, 0), len(text))
    prefix_text = text[:cursor]
    if not prefix_text or prefix_text[-1].isspace():
        return ("key", "")
    tokens = _tokenize(prefix_text, strict=False)
    if not tokens:
        return ("key", "")
    token = tokens[-1]
    if token.wholly_quoted:
        return ("text", token.value)
    colon = _unquoted_index(token, ":")
    if colon < 0:
        return ("key", token.value)
    key = token.value[:colon].casefold()
    if key not in _FILTER_KEYS:
        return ("key", token.value)
    value = token.value[colon + 1 :]
    quoted = token.quoted[colon + 1 :]
    if key in _REPEATABLE_KEYS:
        comma = _last_unquoted_index(value, quoted, ",")
        if comma >= 0:
            value = value[comma + 1 :]
    return (key, value)  # type: ignore[return-value]


def _tokenize(text: str, *, strict: bool = True) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        start = index
        value: list[str] = []
        quoted: list[bool] = []
        in_quotes = False
        saw_quote = False
        saw_unquoted = False
        while index < len(text):
            char = text[index]
            if not in_quotes and char.isspace():
                break
            if char == '"':
                saw_quote = True
                in_quotes = not in_quotes
                index += 1
                continue
            if in_quotes and char == "\\" and index + 1 < len(text):
                escaped = text[index + 1]
                if escaped in {'"', "\\"}:
                    value.append(escaped)
                    quoted.append(True)
                    index += 2
                    continue
            value.append(char)
            quoted.append(in_quotes)
            if not in_quotes:
                saw_unquoted = True
            index += 1
        end = index
        raw = text[start:end]
        if in_quotes and strict:
            raise CommitFilterQueryError(
                "Unterminated double quote",
                token=raw,
                start=start,
                end=end,
            )
        tokens.append(
            _Token(
                value="".join(value),
                raw=raw,
                start=start,
                end=end,
                quoted=tuple(quoted),
                wholly_quoted=saw_quote and not saw_unquoted,
            )
        )
    return tuple(tokens)


def _parse_date_value(
    key: str,
    singles: Mapping[str, tuple[str, _Token]],
) -> tuple[str, int | None, _Token | None]:
    if key not in singles:
        return ("", None, None)
    value, token = singles[key]
    try:
        parsed = parse_time_bound(value)
    except VcsLogDateError as exc:
        raise _error(str(exc), token) from exc
    return (value, parsed, token)


def _unknown_key_error(key: str, token: _Token) -> CommitFilterQueryError:
    suggestion = difflib.get_close_matches(key, _FILTER_KEYS, n=1, cutoff=0.55)
    message = f"Unknown filter key {key!r}"
    if suggestion:
        message += f"; did you mean '{suggestion[0]}:'?"
    return _error(message, token)


def _error(message: str, token: _Token) -> CommitFilterQueryError:
    return CommitFilterQueryError(
        message,
        token=token.raw,
        start=token.start,
        end=token.end,
    )


def _unquoted_index(token: _Token, character: str) -> int:
    return next(
        (
            index
            for index, value in enumerate(token.value)
            if value == character and not token.quoted[index]
        ),
        -1,
    )


def _last_unquoted_index(
    value: str,
    quoted: tuple[bool, ...],
    character: str,
) -> int:
    return next(
        (
            index
            for index in range(len(value) - 1, -1, -1)
            if value[index] == character and not quoted[index]
        ),
        -1,
    )


def _split_unquoted(
    value: str,
    quoted: tuple[bool, ...],
    separator: str,
) -> tuple[str, ...]:
    parts: list[str] = []
    start = 0
    for index, char in enumerate(value):
        if char == separator and not quoted[index]:
            parts.append(value[start:index])
            start = index + 1
    parts.append(value[start:])
    return tuple(parts)


def _quote_value(value: str, *, keyed: bool) -> str:
    needs_quotes = (
        not value
        or any(char.isspace() or char == '"' for char in value)
        or (keyed and "," in value)
        or (not keyed and ":" in value)
    )
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
