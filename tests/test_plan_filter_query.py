"""Coverage for parsing the plans filter query language."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.core.time import get_timezone
from sase.plan_search.filter_query import (
    PlanFilterQueryError,
    PlanFilterValues,
    parse_plan_filter_query,
    to_query_string,
)
from sase.vcs_log.dates import parse_time_bound
from tests._plan_filter_query_helpers import plan_record, query_matches_record


def test_parse_empty_query_uses_defaults() -> None:
    values = parse_plan_filter_query("  \t\n")

    assert values == PlanFilterValues()
    assert values.is_empty is True


def test_parse_every_token_kind_and_case_insensitive_keys() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 18, 12, 0, tzinfo=tz)
    values = parse_plan_filter_query(
        'KIND:epic,phase kind:"archive" '
        'STATUS:open,ready status:"Needs Review" '
        'tier:epic,plan project:sase project:"SASE Core" '
        "since:2026-07-01 until:2026-07-18T08:30 "
        'filter "live preview"',
        now=now,
    )

    assert values.kinds == ("epic", "phase", "archive")
    assert values.statuses == ("open", "ready", "Needs Review")
    assert values.tiers == ("epic", "plan")
    assert values.projects == ("sase", "SASE Core")
    assert values.since_text == "2026-07-01"
    assert values.since == parse_time_bound("2026-07-01").resolve(
        now=now,
        boundary="since",
    )
    assert values.until_text == "2026-07-18T08:30"
    assert values.until == parse_time_bound("2026-07-18T08:30").resolve(
        now=now,
        boundary="until",
    )
    assert values.text == ("filter", "live preview")
    assert values.is_empty is False


def test_quoted_commas_are_values_while_unquoted_commas_are_lists() -> None:
    values = parse_plan_filter_query(
        'status:open,ready status:"waiting,review" '
        'project:sase,core project:"docs,site"'
    )

    assert values.statuses == ("open", "ready", "waiting,review")
    assert values.projects == ("sase", "core", "docs,site")


def test_parse_mixed_positive_and_negative_terms() -> None:
    values = parse_plan_filter_query(
        "kind:epic -kind:archive status:open -status:blocked,closed "
        'tier:epic -tier:tale project:sase -project:"SASE Core" '
        'filter -generated -"rollout bot" "-status:literal"'
    )

    assert values.kinds == ("epic",)
    assert values.excluded_kinds == ("archive",)
    assert values.statuses == ("open",)
    assert values.excluded_statuses == ("blocked", "closed")
    assert values.tiers == ("epic",)
    assert values.excluded_tiers == ("tale",)
    assert values.projects == ("sase",)
    assert values.excluded_projects == ("SASE Core",)
    assert values.text == ("filter", "-status:literal")
    assert values.excluded_text == ("generated", "rollout bot")


def test_parse_accepts_dynamic_document_sidecar_kind() -> None:
    values = parse_plan_filter_query("kind:designs -kind:research")

    assert values.kinds == ("designs",)
    assert values.excluded_kinds == ("research",)


@pytest.mark.parametrize(
    ("query", "message", "token", "span"),
    (
        ("kind:", "requires a value", "kind:", (0, 5)),
        ("status:a,,b", "empty value", "status:a,,b", (0, 11)),
        ("since:not-a-date", "Invalid DATE", "since:not-a-date", (0, 16)),
        ("since:2026-07-18 since:7d", "only appear once", "since:7d", (17, 25)),
        ('project:"SASE Core', "Unterminated", 'project:"SASE Core', (0, 18)),
        ('""', "must not be empty", '""', (0, 2)),
        ("-", "must not be empty", "-", (0, 1)),
        ("-since:7d", "may not be negated", "-since:7d", (0, 9)),
        ("x -until:today", "may not be negated", "-until:today", (2, 14)),
    ),
)
def test_parse_errors_carry_bad_token_and_exact_span(
    query: str,
    message: str,
    token: str,
    span: tuple[int, int],
) -> None:
    with pytest.raises(PlanFilterQueryError, match=message) as exc_info:
        parse_plan_filter_query(query)

    error = exc_info.value
    assert error.token == token
    assert error.bad_token == token
    assert error.span == span
    assert (error.start, error.end) == span


def test_unknown_key_error_suggests_close_match() -> None:
    with pytest.raises(PlanFilterQueryError) as exc_info:
        parse_plan_filter_query("filter statsu:ready")

    assert exc_info.value.span == (7, 19)
    assert "did you mean 'status:'?" in str(exc_info.value)


def test_since_must_not_be_later_than_until() -> None:
    with pytest.raises(PlanFilterQueryError) as exc_info:
        parse_plan_filter_query("since:2026-07-18 until:2026-07-01")

    assert exc_info.value.token == "until:2026-07-01"
    assert exc_info.value.span == (17, 33)


def test_same_day_plan_window_is_valid_and_until_includes_full_day() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 18, 12, 0, tzinfo=tz)

    values = parse_plan_filter_query(
        "since:2026-07-18 until:2026-07-18",
        now=now,
    )

    assert values.since == int(datetime(2026, 7, 18, tzinfo=tz).timestamp())
    assert values.until == int(datetime(2026, 7, 19, tzinfo=tz).timestamp()) - 1
    late_record = plan_record(
        timestamp=int(datetime(2026, 7, 18, 23, 59, 59, tzinfo=tz).timestamp())
    )
    assert query_matches_record(to_query_string(values), late_record)


def test_quoted_key_shaped_term_remains_free_text() -> None:
    assert parse_plan_filter_query('"status:not-a-filter"').text == (
        "status:not-a-filter",
    )
