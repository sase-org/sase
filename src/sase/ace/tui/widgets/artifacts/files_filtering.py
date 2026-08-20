"""Pure query parsing and in-memory filtering for Artifacts Files."""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal

from sase.ace.query.limit_token import extract_limit_as, limit_query_token
from sase.core.artifact_file_types import ARTIFACT_FILE_KINDS
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
from sase.vcs_log.dates import normalize_reference_time

FileCompletionKind = Literal[
    "key",
    "kind",
    "project",
    "agent",
    "workflow",
    "origin",
    "since",
    "until",
    "limit",
    "text",
]

FILE_ORIGIN_VALUES = ("ref", "created", "capture")
_FILTER_KEYS = (
    "kind",
    "project",
    "agent",
    "workflow",
    "origin",
    "since",
    "until",
)
_REPEATABLE_KEYS = frozenset(("kind", "project", "agent", "workflow", "origin"))
_DATE_PATTERNS = (
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
    re.compile(r"^\d{4}-\d{2}$"),
    re.compile(r"^\d{6}$"),
    re.compile(r"^\d+[dwm]$"),
)
_DATE_HELP = "YYYY-MM-DD, YYYY-MM, YYYYMM, or a relative Nd / Nw / Nm offset"


@dataclass(frozen=True, slots=True)
class FilesFilterValues:
    """Validated values shared by the Files pane and its query editor."""

    kinds: tuple[str, ...] = ()
    excluded_kinds: tuple[str, ...] = ()
    projects: tuple[str, ...] = ()
    excluded_projects: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    excluded_agents: tuple[str, ...] = ()
    workflows: tuple[str, ...] = ()
    excluded_workflows: tuple[str, ...] = ()
    origins: tuple[str, ...] = ()
    excluded_origins: tuple[str, ...] = ()
    since_text: str = ""
    excluded_since_text: str = ""
    until_text: str = ""
    excluded_until_text: str = ""
    since: int | None = None
    excluded_since: int | None = None
    until: int | None = None
    excluded_until: int | None = None
    text: tuple[str, ...] = ()
    excluded_text: tuple[str, ...] = ()
    limit: int | None = None

    @property
    def is_empty(self) -> bool:
        """Return whether this filter imposes no constraints."""

        return not any(
            (
                self.kinds,
                self.excluded_kinds,
                self.projects,
                self.excluded_projects,
                self.agents,
                self.excluded_agents,
                self.workflows,
                self.excluded_workflows,
                self.origins,
                self.excluded_origins,
                self.since_text,
                self.excluded_since_text,
                self.until_text,
                self.excluded_until_text,
                self.since is not None,
                self.excluded_since is not None,
                self.until is not None,
                self.excluded_until is not None,
                self.text,
                self.excluded_text,
            )
        )


class FilesFilterQueryError(FilterQueryError):
    """A Files-filter parse failure tied to an exact token span."""


def parse_files_filter_query(
    text: str,
    *,
    now: datetime | None = None,
) -> FilesFilterValues:
    """Parse a Files query into normalized, validated filter values."""

    remainder, cap = extract_limit_as(text, FilesFilterQueryError)
    repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    excluded_repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    singles: dict[str, tuple[str, FilterToken]] = {}
    excluded_singles: dict[str, tuple[str, FilterToken]] = {}
    seen_singles: dict[str, FilterToken] = {}
    text_terms: list[str] = []
    excluded_text_terms: list[str] = []

    for token in tokenize(remainder, error_type=FilesFilterQueryError):
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
                error_type=FilesFilterQueryError,
            )
        value = token.value[colon + 1 :]
        value_quoted = token.quoted[colon + 1 :]
        if not value:
            raise _error(f"{key}: requires a value", token)

        if key in _REPEATABLE_KEYS:
            parts = split_unquoted(value, value_quoted, ",")
            if any(not part for part in parts):
                raise _error(f"{key}: contains an empty value", token)
            _validate_static_values(key, parts, token)
            (excluded_repeated if token.negated else repeated)[key].extend(parts)
            continue

        if key in seen_singles:
            raise _error(f"{key}: may only appear once", token)
        seen_singles[key] = token
        (excluded_singles if token.negated else singles)[key] = (value, token)

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
    excluded_since_text, excluded_since, _excluded_since_token = _parse_date_value(
        "since",
        excluded_singles,
        now=reference,
        boundary="since",
    )
    excluded_until_text, excluded_until, _excluded_until_token = _parse_date_value(
        "until",
        excluded_singles,
        now=reference,
        boundary="until",
    )
    if since is not None and until is not None and since > until:
        assert until_token is not None
        raise _error("since: value must not be later than until: value", until_token)

    return FilesFilterValues(
        kinds=tuple(value.casefold() for value in repeated["kind"]),
        excluded_kinds=tuple(value.casefold() for value in excluded_repeated["kind"]),
        projects=tuple(repeated["project"]),
        excluded_projects=tuple(excluded_repeated["project"]),
        agents=tuple(repeated["agent"]),
        excluded_agents=tuple(excluded_repeated["agent"]),
        workflows=tuple(repeated["workflow"]),
        excluded_workflows=tuple(excluded_repeated["workflow"]),
        origins=tuple(value.casefold() for value in repeated["origin"]),
        excluded_origins=tuple(
            value.casefold() for value in excluded_repeated["origin"]
        ),
        since_text=since_text,
        excluded_since_text=excluded_since_text,
        until_text=until_text,
        excluded_until_text=excluded_until_text,
        since=since,
        excluded_since=excluded_since,
        until=until,
        excluded_until=excluded_until,
        text=tuple(text_terms),
        excluded_text=tuple(excluded_text_terms),
        limit=cap,
    )


def to_query_tokens(values: FilesFilterValues) -> tuple[str, ...]:
    """Render values as canonical tokens in stable filter order."""

    tokens: list[str] = []
    for key, entries in (
        ("kind", values.kinds),
        ("project", values.projects),
        ("agent", values.agents),
        ("workflow", values.workflows),
        ("origin", values.origins),
    ):
        tokens.extend(f"{key}:{quote_value(value, keyed=True)}" for value in entries)
        excluded_entries = getattr(values, f"excluded_{key}s")
        tokens.extend(
            f"-{key}:{quote_value(value, keyed=True)}" for value in excluded_entries
        )
    if values.since_text:
        tokens.append(f"since:{quote_value(values.since_text, keyed=True)}")
    if values.excluded_since_text:
        tokens.append(f"-since:{quote_value(values.excluded_since_text, keyed=True)}")
    if values.until_text:
        tokens.append(f"until:{quote_value(values.until_text, keyed=True)}")
    if values.excluded_until_text:
        tokens.append(f"-until:{quote_value(values.excluded_until_text, keyed=True)}")
    if token := limit_query_token(values.limit):
        tokens.append(token)
    tokens.extend(quote_value(term, keyed=False) for term in values.text)
    tokens.extend(f"-{quote_value(term, keyed=False)}" for term in values.excluded_text)
    return tuple(tokens)


def to_query_string(values: FilesFilterValues) -> str:
    """Render values as a canonical query string."""

    return " ".join(to_query_tokens(values))


def files_completion_context(
    text: str,
    cursor: int,
) -> tuple[FileCompletionKind, str, bool]:
    """Classify a Files-filter completion prefix."""

    kind, prefix, negated = completion_context(
        text,
        cursor,
        keys=(*_FILTER_KEYS, "limit"),
        repeatable_keys=_REPEATABLE_KEYS,
        negatable_keys=frozenset(_FILTER_KEYS),
    )
    return kind, prefix, negated  # type: ignore[return-value]


def _validate_static_values(
    key: str,
    parts: tuple[str, ...],
    token: FilterToken,
) -> None:
    allowed: tuple[str, ...] | None = None
    if key == "kind":
        allowed = ARTIFACT_FILE_KINDS
    elif key == "origin":
        allowed = FILE_ORIGIN_VALUES
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


def _parse_date_value(
    key: str,
    singles: Mapping[str, tuple[str, FilterToken]],
    *,
    now: datetime,
    boundary: Literal["since", "until"],
) -> tuple[str, int | None, FilterToken | None]:
    if key not in singles:
        return ("", None, None)
    value, token = singles[key]
    if not any(pattern.fullmatch(value) for pattern in _DATE_PATTERNS):
        raise _error(f"Invalid DATE {value!r}; expected {_DATE_HELP}", token)
    try:
        parsed = _resolve_date_bound(value, now=now, boundary=boundary)
    except ValueError as exc:
        raise _error(f"Invalid DATE {value!r}; expected {_DATE_HELP}", token) from exc
    return (value, parsed, token)


def _resolve_date_bound(
    value: str,
    *,
    now: datetime,
    boundary: Literal["since", "until"],
) -> int:
    relative = re.fullmatch(r"(\d+)([dwm])", value.casefold())
    if relative:
        amount = int(relative.group(1))
        unit = relative.group(2)
        if unit == "d":
            target = now - timedelta(days=amount)
        elif unit == "w":
            target = now - timedelta(weeks=amount)
        else:
            target = _subtract_months(now, amount)
        return int(target.timestamp())

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        day = datetime.strptime(value, "%Y-%m-%d").date()
        start = datetime.combine(day, time.min, tzinfo=now.tzinfo)
        if boundary == "since":
            return int(start.timestamp())
        return int((start + timedelta(days=1)).timestamp()) - 1

    compact = value.replace("-", "")
    if not re.fullmatch(r"\d{6}", compact):
        raise ValueError(value)
    year, month = int(compact[:4]), int(compact[4:])
    start = datetime(year, month, 1, tzinfo=now.tzinfo)
    if boundary == "since":
        return int(start.timestamp())
    days = calendar.monthrange(year, month)[1]
    return int((start + timedelta(days=days)).timestamp()) - 1


def _subtract_months(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 - months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


def _error(message: str, token: FilterToken) -> FilesFilterQueryError:
    return error_for_token(
        message,
        token,
        error_type=FilesFilterQueryError,
    )  # type: ignore[return-value]


__all__ = [
    "FILE_ORIGIN_VALUES",
    "FileCompletionKind",
    "FilesFilterQueryError",
    "FilesFilterValues",
    "files_completion_context",
    "parse_files_filter_query",
    "to_query_string",
    "to_query_tokens",
]
