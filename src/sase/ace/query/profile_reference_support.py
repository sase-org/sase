"""Shared validation helpers for profile-driven reference parsing."""

from __future__ import annotations

import calendar
import re
from collections.abc import Sequence
from datetime import datetime, timedelta

from sase.ace.query.parser import QueryParseError
from sase.ace.query.types import AndExpr, OrExpr, QueryExpr
from sase.ace.query_profile import CompiledQueryProfile, QueryFieldSpec
from sase.vcs_log.dates import (
    TimeBoundary,
    VcsLogDateError,
    normalize_reference_time,
    parse_time_bound,
)

_INTEGER_RE = re.compile(r"^[+-]?\d+$")
_MONTH_RE = re.compile(r"^(?P<year>\d{4})-?(?P<month>\d{2})$")
_RELATIVE_MONTH_RE = re.compile(r"^(?P<amount>\d+)m$", re.IGNORECASE)
_BOOLEAN_VALUES = {"true": True, "false": False}


class ProfileQueryError(QueryParseError):
    """Profile-aware query parse failure with the standard query error shape."""


def require_filterable_field(
    profile: CompiledQueryProfile,
    key: str,
    position: int,
) -> QueryFieldSpec:
    """Return a filterable profile field or raise a positioned query error."""

    field = profile.field(key)
    if field is None or not field.filterable:
        valid = ", ".join(item.key for item in profile.fields if item.filterable)
        raise ProfileQueryError(
            f"Unknown filter key {key!r}"
            + (f" (valid keys: {valid})" if valid else ""),
            position,
        )
    return field


def normalize_query_value(
    field: QueryFieldSpec,
    value: str,
    *,
    position: int,
) -> str:
    """Normalize a query value according to its profile field specification."""

    if field.value_kind == "enum":
        allowed = {item.casefold(): item for item in field.static_values}
        normalized = allowed.get(value.casefold())
        if normalized is None:
            raise ProfileQueryError(
                f"{field.key}: value {value!r} must be one of "
                f"{', '.join(field.static_values)}",
                position,
            )
        return normalized
    if field.value_kind == "bool":
        normalized_bool = _BOOLEAN_VALUES.get(value.casefold())
        if normalized_bool is None:
            raise ProfileQueryError(f"{field.key}: must be 'true' or 'false'", position)
        return "true" if normalized_bool else "false"
    if field.value_kind == "int":
        if not _INTEGER_RE.fullmatch(value):
            raise ProfileQueryError(f"{field.key}: must be an integer", position)
        return str(int(value))
    if field.value_kind == "date":
        return str(_parse_date_bound_value(field.key, value, position=position))
    return value


def and_terms(terms: Sequence[QueryExpr]) -> QueryExpr:
    """Combine terms with AND while avoiding a redundant one-item node."""

    if not terms:
        raise ProfileQueryError("Empty query", 0)
    if len(terms) == 1:
        return terms[0]
    return AndExpr(list(terms))


def or_terms(terms: Sequence[QueryExpr]) -> QueryExpr:
    """Combine terms with OR while avoiding a redundant one-item node."""

    if len(terms) == 1:
        return terms[0]
    return OrExpr(list(terms))


def _parse_date_bound_value(key: str, value: str, *, position: int) -> int:
    boundary: TimeBoundary = "until" if key == "until" else "since"
    now = normalize_reference_time()
    relative_month = _RELATIVE_MONTH_RE.fullmatch(value)
    if relative_month is not None:
        return int(
            _subtract_months(now, int(relative_month.group("amount"))).timestamp()
        )
    month = _MONTH_RE.fullmatch(value)
    if month is not None:
        try:
            start = datetime(
                int(month.group("year")),
                int(month.group("month")),
                1,
                tzinfo=now.tzinfo,
            )
        except ValueError as exc:
            raise ProfileQueryError(f"Invalid DATE {value!r}", position) from exc
        if boundary == "since":
            return int(start.timestamp())
        days = calendar.monthrange(start.year, start.month)[1]
        return int((start + timedelta(days=days)).timestamp()) - 1
    try:
        return parse_time_bound(value).resolve(
            now=now,
            boundary=boundary,
        )
    except VcsLogDateError as exc:
        raise ProfileQueryError(str(exc), position) from exc


def _subtract_months(moment: datetime, months: int) -> datetime:
    index = moment.month - 1 - months
    year = moment.year + index // 12
    month = index % 12 + 1
    day = min(moment.day, calendar.monthrange(year, month)[1])
    return moment.replace(year=year, month=month, day=day)


__all__ = [
    "ProfileQueryError",
    "and_terms",
    "normalize_query_value",
    "or_terms",
    "require_filterable_field",
]
