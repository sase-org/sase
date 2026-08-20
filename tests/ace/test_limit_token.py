"""Unit coverage for host-owned ``limit:`` token helpers."""

from __future__ import annotations

import pytest

from sase.ace.query.limit_token import (
    LimitTokenError,
    adjust_limit,
    apply_limit,
    ensure_limit,
    extract_limit,
    extract_limit_as,
    limit_query_token,
    replace_limit,
)
from sase.filter_tokens import FilterQueryError


def test_extract_limit_absent_returns_original_query_unlimited() -> None:
    query = "  sidecar:false  since:24h  "

    remainder, cap = extract_limit(query)

    assert remainder == query
    assert cap is None


@pytest.mark.parametrize(
    ("query", "remainder", "cap"),
    [
        ("limit:100", "", 100),
        ("LIMIT:40", "", 40),
        ("sidecar:false limit:40 since:24h", "sidecar:false since:24h", 40),
        ("limit:all", "", None),
        ("limit:ALL", "", None),
        ("limit:0", "", None),
        ("limit:00", "", None),
        ('status:open limit:"100"', "status:open", 100),
        ("-status:closed limit:100", "-status:closed", 100),
        ('"limit:100" sidecar:false', '"limit:100" sidecar:false', None),
        ('"quoted:text" limit:25 extra', '"quoted:text" extra', 25),
    ],
)
def test_extract_limit_strips_token_and_parses_cap(
    query: str,
    remainder: str,
    cap: int | None,
) -> None:
    assert extract_limit(query) == (remainder, cap)


@pytest.mark.parametrize(
    ("query", "message", "token", "span"),
    [
        ("-limit:40", "may not be negated", "-limit:40", (0, 9)),
        ("limit:", "requires a value", "limit:", (0, 6)),
        ("limit:foo", "non-negative integer or 'all'", "limit:foo", (0, 9)),
        ("limit:-1", "non-negative integer or 'all'", "limit:-1", (0, 8)),
        ("limit:1.5", "non-negative integer or 'all'", "limit:1.5", (0, 9)),
        ("limit:10,20", "non-negative integer or 'all'", "limit:10,20", (0, 11)),
        (
            "limit:40 limit:80",
            "only appear once",
            "limit:80",
            (9, 17),
        ),
    ],
)
def test_extract_limit_rejects_invalid_tokens(
    query: str,
    message: str,
    token: str,
    span: tuple[int, int],
) -> None:
    with pytest.raises(LimitTokenError, match=message) as exc_info:
        extract_limit(query)

    error = exc_info.value
    assert error.token == token
    assert error.span == span
    assert (error.start, error.end) == span


def test_extract_limit_rejects_unterminated_quote() -> None:
    with pytest.raises(LimitTokenError, match="Unterminated double quote"):
        extract_limit('"limit:100')


def test_ensure_limit_appends_when_absent() -> None:
    assert ensure_limit("", 100) == "limit:100"
    assert ensure_limit("   ", 100) == "limit:100"
    assert ensure_limit("-status:closed", 100) == "-status:closed limit:100"
    assert ensure_limit("sidecar:false since:24h", 25) == (
        "sidecar:false since:24h limit:25"
    )


@pytest.mark.parametrize(
    "query",
    [
        "limit:40",
        "limit:all",
        "limit:0",
        "-status:closed limit:20",
        "sidecar:false limit:all since:24h",
    ],
)
def test_ensure_limit_leaves_explicit_token_alone(query: str) -> None:
    assert ensure_limit(query, 100) == query


def test_ensure_limit_still_rejects_invalid_existing_token() -> None:
    with pytest.raises(LimitTokenError, match="non-negative integer or 'all'"):
        ensure_limit("limit:foo", 100)


def test_replace_limit_appends_when_absent() -> None:
    assert replace_limit("", 100) == "limit:100"
    assert replace_limit("-status:closed", 100) == "-status:closed limit:100"


def test_replace_limit_overwrites_existing_token_in_place() -> None:
    assert replace_limit("limit:all", 100) == "limit:100"
    assert replace_limit("sidecar:false  limit:40  since:24h", 100) == (
        "sidecar:false  limit:100  since:24h"
    )
    assert replace_limit('-status:closed limit:"20"', 25) == ("-status:closed limit:25")


@pytest.mark.parametrize(
    ("current", "page_size", "direction", "expected"),
    [
        (100, 100, "load_more", 200),
        (20, 100, "load_more", 120),
        (None, 100, "load_more", None),
        (200, 100, "unload", 100),
        (150, 100, "unload", 100),
        (100, 100, "unload", 100),
        (20, 100, "unload", 20),
        (None, 100, "unload", 100),
        (None, 25, "unload", 25),
        (50, 25, "unload", 25),
        (24, 25, "unload", 24),
    ],
)
def test_adjust_limit_floor_and_plus_minus_rules(
    current: int | None,
    page_size: int,
    direction: str,
    expected: int | None,
) -> None:
    assert adjust_limit(current, page_size, direction) == expected  # type: ignore[arg-type]


def test_adjust_limit_rejects_invalid_page_size_and_direction() -> None:
    with pytest.raises(ValueError, match="page_size"):
        adjust_limit(100, 0, "load_more")
    with pytest.raises(ValueError, match="unknown limit direction"):
        adjust_limit(100, 100, "sideways")  # type: ignore[arg-type]


def test_apply_limit_slices_and_reports_truncation() -> None:
    rows = ("a", "b", "c")
    assert apply_limit(rows, None) == (("a", "b", "c"), False)
    assert apply_limit(rows, 3) == (("a", "b", "c"), False)
    assert apply_limit(rows, 2) == (("a", "b"), True)
    assert apply_limit((), 100) == ((), False)


def test_limit_query_token_omits_unlimited() -> None:
    assert limit_query_token(None) is None
    assert limit_query_token(100) == "limit:100"


def test_extract_limit_as_rewrites_error_type() -> None:
    class _DialectError(FilterQueryError):
        pass

    with pytest.raises(_DialectError, match="may not be negated") as exc_info:
        extract_limit_as("-limit:10", _DialectError)
    assert exc_info.value.span == (0, 9)


def test_ensure_and_replace_reject_non_positive_n() -> None:
    with pytest.raises(ValueError, match="n must be an integer >= 1"):
        ensure_limit("foo", 0)
    with pytest.raises(ValueError, match="n must be an integer >= 1"):
        replace_limit("foo", -1)
