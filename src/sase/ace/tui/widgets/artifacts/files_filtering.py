"""Pure query parsing and in-memory filtering for Artifacts Files."""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta, tzinfo
from typing import Literal

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
from sase.project_display_names import ProjectRefDisplaySnapshot
from sase.vcs_log.dates import normalize_reference_time

from .files_data import FilesSnapshot, LogicalFile

FileCompletionKind = Literal[
    "key",
    "kind",
    "project",
    "agent",
    "workflow",
    "origin",
    "since",
    "until",
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
    projects: tuple[str, ...] = ()
    agents: tuple[str, ...] = ()
    workflows: tuple[str, ...] = ()
    origins: tuple[str, ...] = ()
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
                self.projects,
                self.agents,
                self.workflows,
                self.origins,
                self.since_text,
                self.until_text,
                self.since is not None,
                self.until is not None,
                self.text,
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

    repeated: dict[str, list[str]] = {key: [] for key in _REPEATABLE_KEYS}
    singles: dict[str, tuple[str, FilterToken]] = {}
    text_terms: list[str] = []

    for token in tokenize(text, error_type=FilesFilterQueryError):
        colon = unquoted_index(token, ":")
        if token.wholly_quoted or colon < 0:
            if token.negated:
                raise _error("Files filters do not support negation", token)
            value = token.body
            if not value:
                raise _error("Free-text terms must not be empty", token)
            text_terms.append(value)
            continue

        if token.negated:
            raise _error("Files filters do not support negation", token)
        key = token.value[:colon].casefold()
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

    return FilesFilterValues(
        kinds=tuple(value.casefold() for value in repeated["kind"]),
        projects=tuple(repeated["project"]),
        agents=tuple(repeated["agent"]),
        workflows=tuple(repeated["workflow"]),
        origins=tuple(value.casefold() for value in repeated["origin"]),
        since_text=since_text,
        until_text=until_text,
        since=since,
        until=until,
        text=tuple(text_terms),
    )


def filter_files_snapshot(
    snapshot: FilesSnapshot | None,
    values: FilesFilterValues,
    project_ref_display: ProjectRefDisplaySnapshot | None = None,
) -> FilesSnapshot | None:
    """Return matching rows while preserving the full snapshot's summary totals."""

    if snapshot is None or values.is_empty:
        return snapshot
    naive_timezone = (
        normalize_reference_time().tzinfo
        if values.since is not None or values.until is not None
        else None
    )
    project_values = tuple(
        (
            None
            if project_ref_display is None
            else project_ref_display.project_key_for_ref(value)
        )
        or value
        for value in values.projects
    )
    rows = tuple(
        row
        for row in snapshot.rows
        if _file_matches(
            row,
            values,
            project_values=project_values,
            naive_timezone=naive_timezone,
        )
    )
    return replace(snapshot, rows=rows)


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
    if values.since_text:
        tokens.append(f"since:{quote_value(values.since_text, keyed=True)}")
    if values.until_text:
        tokens.append(f"until:{quote_value(values.until_text, keyed=True)}")
    tokens.extend(quote_value(term, keyed=False) for term in values.text)
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
        keys=_FILTER_KEYS,
        repeatable_keys=_REPEATABLE_KEYS,
        negatable_keys=frozenset(),
    )
    return kind, prefix, negated  # type: ignore[return-value]


def _file_matches(
    row: LogicalFile,
    values: FilesFilterValues,
    *,
    project_values: tuple[str, ...],
    naive_timezone: tzinfo | None,
) -> bool:
    if values.kinds and row.kind.casefold() not in values.kinds:
        return False
    if project_values and not _matches_any(row.projects, project_values):
        return False
    if values.agents and not _matches_any(row.agents, values.agents):
        return False
    workflows = tuple(version.workflow for version in row.versions if version.workflow)
    if values.workflows and not _matches_any(workflows, values.workflows):
        return False
    if values.origins and row.origins.isdisjoint(values.origins):
        return False

    if values.since is not None or values.until is not None:
        timestamp = _entry_epoch(row.latest.created_at, naive_timezone=naive_timezone)
        if values.since is not None and (timestamp is None or timestamp < values.since):
            return False
        if values.until is not None and (timestamp is None or timestamp > values.until):
            return False

    haystack = " ".join(
        value
        for value in (
            row.label,
            row.logical_id,
            *row.projects,
            *row.agents,
            *(
                value
                for version in row.versions
                for value in (
                    version.label,
                    version.path,
                    version.source_path,
                    version.vcs_relpath,
                    version.object_relpath,
                    version.sha256,
                    version.artifact_id,
                )
                if value
            ),
        )
        if value
    ).casefold()
    return all(term.casefold() in haystack for term in values.text)


def _matches_any(values: tuple[str, ...], needles: tuple[str, ...]) -> bool:
    folded = {value.casefold() for value in values}
    return any(needle.casefold() in folded for needle in needles)


def _entry_epoch(
    created_at: str | None,
    *,
    naive_timezone: tzinfo | None,
) -> int | None:
    if not created_at:
        return None
    try:
        timestamp = datetime.fromisoformat(created_at)
    except ValueError:
        return None
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=naive_timezone)
    return int(timestamp.timestamp())


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
    "filter_files_snapshot",
    "parse_files_filter_query",
    "to_query_string",
    "to_query_tokens",
]
