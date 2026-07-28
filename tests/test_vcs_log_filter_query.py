"""Coverage for the commits filter query language and in-memory matcher."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from hypothesis import given, strategies as st

from sase.ace.tui.widgets.artifacts.commits_rendering import commit_filter_chips
from sase.core.time import get_timezone
from sase.core.vcs_log_wire import AggregatedCommitWire, VcsCommitWire
from sase.vcs_log.dates import parse_time_bound
from sase.vcs_log.filter_query import (
    CommitFilterQueryError,
    CommitLogFilterValues,
    UNLIMITED_COMMIT_LOG_LIMIT,
    compile_commit_matcher,
    completion_context,
    parse_commit_filter_query,
    to_query_string,
)
from sase.vcs_log.models import CommitFilterSpec, CommitFilters


def _entry(
    *,
    repo: str = "sase",
    author_name: str = "Ada Lovelace",
    author_email: str = "ada@example.com",
    timestamp: int = 200,
    subject: str = "Fix live commit timeline preview",
) -> AggregatedCommitWire:
    return AggregatedCommitWire(
        repo=repo,
        commit=VcsCommitWire(
            full_id="a" * 40,
            short_id="aaaaaaa",
            author_name=author_name,
            author_email=author_email,
            timestamp=timestamp,
            subject=subject,
            body="",
        ),
    )


def test_parse_empty_query_includes_sidecars() -> None:
    values = parse_commit_filter_query("  \t\n")

    assert values == CommitLogFilterValues()
    assert values.sidecar is True
    assert values.limit == UNLIMITED_COMMIT_LOG_LIMIT
    assert to_query_string(values) == "sidecar:true"


def test_bundled_query_is_unlimited_without_a_canonical_limit_token() -> None:
    values = parse_commit_filter_query("sidecar:false since:24h")

    assert values.limit == UNLIMITED_COMMIT_LOG_LIMIT
    assert to_query_string(values) == "sidecar:false since:24h"


def test_parse_every_token_kind_and_case_insensitive_keys() -> None:
    values = parse_commit_filter_query(
        'PROJECT:"SASE Org" REPO:sase,sase-core repo:"SASE docs" '
        'Author:Ada author:"Grace Hopper",@example.com '
        "since:2026-07-01 until:2026-07-18T08:30 SIDECAR:TrUe limit:all "
        'fix "live preview"'
    )

    assert values.project == "SASE Org"
    assert values.repos == ("sase", "sase-core", "SASE docs")
    assert values.authors == ("Ada", "Grace Hopper", "@example.com")
    assert values.since_text == "2026-07-01"
    assert values.since == parse_time_bound("2026-07-01")
    assert values.until_text == "2026-07-18T08:30"
    assert values.until == parse_time_bound("2026-07-18T08:30")
    assert values.sidecar is True
    assert values.limit == 0
    assert values.text == ("fix", "live preview")


def test_relative_query_values_are_stable_across_delayed_reparses() -> None:
    tz = get_timezone()
    first_now = datetime(2026, 7, 8, 15, 30, tzinfo=tz)
    later_now = first_now + timedelta(days=1, hours=2)
    query = "sidecar:false since:24h until:today"

    first = parse_commit_filter_query(query, now=first_now)
    reparsed = parse_commit_filter_query(query, now=later_now)

    assert reparsed == first
    assert hash(reparsed) == hash(first)
    assert to_query_string(reparsed) == query
    assert first.backend_filters(now=first_now) != reparsed.backend_filters(
        now=later_now
    )


def test_quoted_commas_are_values_while_unquoted_commas_are_lists() -> None:
    values = parse_commit_filter_query(
        'repo:one,two repo:"name,with,commas" author:Ada,Grace author:"Lovelace, Ada"'
    )

    assert values.repos == ("one", "two", "name,with,commas")
    assert values.authors == ("Ada", "Grace", "Lovelace, Ada")


def test_parse_mixed_positive_and_negative_terms() -> None:
    values = parse_commit_filter_query(
        "repo:sase -repo:plans,research author:Ada -author:bot "
        'fix -generated -"rollout bot" "-repo:literal"'
    )

    assert values.repos == ("sase",)
    assert values.excluded_repos == ("plans", "research")
    assert values.authors == ("Ada",)
    assert values.excluded_authors == ("bot",)
    assert values.text == ("fix", "-repo:literal")
    assert values.excluded_text == ("generated", "rollout bot")


@pytest.mark.parametrize(
    ("query", "message", "token", "span"),
    (
        ("repo:", "requires a value", "repo:", (0, 5)),
        ("project:", "requires a value", "project:", (0, 8)),
        (
            "project:sase,other",
            "does not accept comma-separated values",
            "project:sase,other",
            (0, 18),
        ),
        (
            "project:sase project:other",
            "only appear once",
            "project:other",
            (13, 26),
        ),
        (
            "-project:sase",
            "may not be negated",
            "-project:sase",
            (0, 13),
        ),
        ("repo:a,,b", "empty value", "repo:a,,b", (0, 9)),
        ("limit:-1", "non-negative integer", "limit:-1", (0, 8)),
        ("since:not-a-date", "Invalid DATE", "since:not-a-date", (0, 16)),
        ("since:2026-07-18 since:7d", "only appear once", "since:7d", (17, 25)),
        ('author:"Ada Lovelace', "Unterminated", 'author:"Ada Lovelace', (0, 20)),
        ('""', "must not be empty", '""', (0, 2)),
        ("-", "must not be empty", "-", (0, 1)),
        ("-since:7d", "may not be negated", "-since:7d", (0, 9)),
        ("fix -until:today", "may not be negated", "-until:today", (4, 16)),
        ("-limit:10", "may not be negated", "-limit:10", (0, 9)),
        ("sidecar:", "requires a value", "sidecar:", (0, 8)),
        ("sidecar:yes", "must be 'true' or 'false'", "sidecar:yes", (0, 11)),
        ("-sidecar:true", "may not be negated", "-sidecar:true", (0, 13)),
        (
            "sidecar:true sidecar:false",
            "only appear once",
            "sidecar:false",
            (13, 26),
        ),
    ),
)
def test_parse_errors_carry_bad_token_and_exact_span(
    query: str,
    message: str,
    token: str,
    span: tuple[int, int],
) -> None:
    with pytest.raises(CommitFilterQueryError, match=message) as exc_info:
        parse_commit_filter_query(query)

    error = exc_info.value
    assert error.token == token
    assert error.bad_token == token
    assert error.span == span
    assert (error.start, error.end) == span


def test_unknown_key_error_suggests_close_match() -> None:
    with pytest.raises(CommitFilterQueryError) as exc_info:
        parse_commit_filter_query("fix repoo:sase")

    assert exc_info.value.span == (4, 14)
    assert "did you mean 'repo:'?" in str(exc_info.value)


def test_unknown_project_key_error_suggests_project() -> None:
    with pytest.raises(CommitFilterQueryError) as exc_info:
        parse_commit_filter_query("projecct:sase")

    assert exc_info.value.span == (0, 13)
    assert "did you mean 'project:'?" in str(exc_info.value)


def test_since_must_not_be_later_than_until() -> None:
    with pytest.raises(CommitFilterQueryError) as exc_info:
        parse_commit_filter_query("since:2026-07-18 until:2026-07-01")

    assert exc_info.value.token == "until:2026-07-01"
    assert exc_info.value.span == (17, 33)


@pytest.mark.parametrize("value", ["2026-07-18", "today", "yesterday"])
def test_same_day_window_is_valid(value: str) -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 18, 12, 0, tzinfo=tz)

    values = parse_commit_filter_query(
        f"since:{value} until:{value}",
        now=now,
    )

    filters = values.backend_filters(now=now)
    assert filters.since is not None
    assert filters.until is not None
    assert filters.since < filters.until


def test_quoted_key_shaped_term_remains_free_text() -> None:
    assert parse_commit_filter_query('"repo:not-a-filter"').text == (
        "repo:not-a-filter",
    )


def test_canonical_query_has_stable_order_and_omits_unlimited_limit() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 18, 12, 0, tzinfo=tz)

    values = parse_commit_filter_query(
        'preview author:"Ada Lovelace" until:2026-07-18 repo:sase project:"SASE Org" '
        "since:7d sidecar:true timeline",
        now=now,
    )

    assert to_query_string(values) == (
        'project:"SASE Org" repo:sase author:"Ada Lovelace" sidecar:true since:7d '
        "until:2026-07-18 preview timeline"
    )
    assert to_query_string(CommitLogFilterValues()) == "sidecar:true"
    assert to_query_string(parse_commit_filter_query("sidecar:false")) == (
        "sidecar:false"
    )


@pytest.mark.parametrize("query", ["limit:all", "limit:ALL", "limit:0"])
def test_explicit_unlimited_limit_normalizes_to_omission(query: str) -> None:
    values = parse_commit_filter_query(query)

    assert values.limit == UNLIMITED_COMMIT_LOG_LIMIT
    assert to_query_string(values) == "sidecar:true"
    assert parse_commit_filter_query(to_query_string(values)) == values


@pytest.mark.parametrize("limit", [1, 40, 100, 999])
def test_positive_limit_serializes_and_round_trips(limit: int) -> None:
    values = parse_commit_filter_query(f"limit:{limit}")

    assert values.limit == limit
    assert to_query_string(values) == f"sidecar:true limit:{limit}"
    assert parse_commit_filter_query(to_query_string(values)) == values


def test_canonical_query_serializes_exclusions_and_literal_hyphens() -> None:
    values = parse_commit_filter_query(
        "repo:sase -repo:plans author:Ada -author:bot "
        '"-literal" -generated -"generated rollout"'
    )

    assert to_query_string(values) == (
        "repo:sase -repo:plans author:Ada -author:bot "
        'sidecar:true "-literal" -generated -"generated rollout"'
    )


_VALUE_TEXT = st.text(
    alphabet='abcXYZ 09,:\\"-@.',
    min_size=1,
    max_size=18,
)


@given(
    project=st.one_of(st.none(), _VALUE_TEXT),
    repos=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    authors=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_repos=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_authors=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    text_terms=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_text=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    sidecar=st.booleans(),
    limit=st.sampled_from((0, 1, 40, 100, 999)),
    bounds=st.sampled_from(
        (
            ("", ""),
            ("2026-07-01", ""),
            ("", "2026-07-18"),
            ("2026-07-01", "2026-07-18T08:30"),
        )
    ),
)
def test_canonical_query_round_trip_property(
    project: str | None,
    repos: tuple[str, ...],
    authors: tuple[str, ...],
    excluded_repos: tuple[str, ...],
    excluded_authors: tuple[str, ...],
    text_terms: tuple[str, ...],
    excluded_text: tuple[str, ...],
    sidecar: bool,
    limit: int,
    bounds: tuple[str, str],
) -> None:
    since_text, until_text = bounds
    values = CommitLogFilterValues(
        project=project,
        authors=authors,
        excluded_authors=excluded_authors,
        since_text=since_text,
        until_text=until_text,
        since=parse_time_bound(since_text) if since_text else None,
        until=parse_time_bound(until_text) if until_text else None,
        repos=repos,
        excluded_repos=excluded_repos,
        sidecar=sidecar,
        limit=limit,
        text=text_terms,
        excluded_text=excluded_text,
    )

    assert parse_commit_filter_query(to_query_string(values)) == values


def test_backend_filters_exclude_repo_text_and_limit() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 18, 12, 0, tzinfo=tz)
    values = CommitLogFilterValues(
        project="sase",
        authors=("Ada",),
        excluded_authors=("bot",),
        since=parse_time_bound("24h"),
        until=parse_time_bound("2026-07-18"),
        repos=("sase",),
        excluded_repos=("plans",),
        limit=5,
        text=("fix",),
        excluded_text=("generated",),
    )

    assert values.backend_filters(now=now) == CommitFilters(
        authors=("Ada",),
        since=int((now - timedelta(hours=24)).timestamp()),
        until=int(datetime(2026, 7, 19, tzinfo=tz).timestamp()) - 1,
    )
    assert values.backend_filter_spec() == CommitFilterSpec(
        authors=("Ada",),
        since=parse_time_bound("24h"),
        until=parse_time_bound("2026-07-18"),
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({}, True),
        ({"repo": "other"}, False),
        (
            {"author_name": "Linus Torvalds", "author_email": "linus@example.com"},
            False,
        ),
        ({"author_email": "ADA@EXAMPLE.COM"}, True),
        ({"subject": "fix timeline only"}, False),
        ({"subject": "LIVE preview needs a FIX"}, True),
    ),
)
def test_commit_matcher_ands_kinds_and_text_but_ors_authors(
    changes: dict[str, object], expected: bool
) -> None:
    entry_kwargs: dict[str, object] = {
        "repo": "SASE",
        "author_name": "Ada Lovelace",
        "author_email": "ada@example.com",
        "timestamp": 200,
        "subject": "Fix live commit timeline preview",
    }
    entry_kwargs.update(changes)
    values = CommitLogFilterValues(
        repos=("sase", "sase-core"),
        authors=("grace", "ADA@EXAMPLE"),
        text=("fix", "preview"),
    )

    matcher = compile_commit_matcher(values)
    assert matcher(_entry(**entry_kwargs)) is expected  # type: ignore[arg-type]


def test_commit_matcher_resolves_bounds_once_against_explicit_time() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 18, 16, 0, tzinfo=tz)
    values = CommitLogFilterValues(
        since=parse_time_bound("2h"),
        until=parse_time_bound("2026-07-18T15:00"),
    )

    matcher = compile_commit_matcher(values, now=now)

    assert matcher(
        _entry(timestamp=int(datetime(2026, 7, 18, 14, 0, tzinfo=tz).timestamp()))
    )
    assert matcher(
        _entry(timestamp=int(datetime(2026, 7, 18, 15, 0, tzinfo=tz).timestamp()))
    )
    assert not matcher(
        _entry(timestamp=int(datetime(2026, 7, 18, 13, 59, tzinfo=tz).timestamp()))
    )
    assert not matcher(
        _entry(timestamp=int(datetime(2026, 7, 18, 15, 1, tzinfo=tz).timestamp()))
    )


def test_compiled_matcher_accepts_repo_aliases_case_insensitively() -> None:
    matcher = compile_commit_matcher(
        CommitLogFilterValues(repos=("GH:SASE-ORG/SASE",)),
        repo_aliases={"sase": ("gh:sase-org/sase", "sase-org/sase")},
    )

    assert matcher(_entry(repo="SASE")) is True
    assert matcher(_entry(repo="sase-core")) is False


def test_commit_matcher_applies_negative_vetoes_after_positive_matches() -> None:
    matcher = compile_commit_matcher(
        CommitLogFilterValues(
            repos=("sase",),
            excluded_repos=("docs",),
            authors=("ada",),
            excluded_authors=("bot",),
            text=("fix",),
            excluded_text=("generated",),
        ),
        repo_aliases={"sase": ("docs",)},
    )

    assert matcher(_entry()) is False
    assert (
        compile_commit_matcher(
            CommitLogFilterValues(excluded_authors=("ADA@EXAMPLE",))
        )(_entry())
        is False
    )
    assert (
        compile_commit_matcher(CommitLogFilterValues(excluded_text=("LIVE",)))(_entry())
        is False
    )
    assert (
        compile_commit_matcher(
            CommitLogFilterValues(text=("fix",), excluded_text=("other",))
        )(_entry())
        is True
    )


def test_matcher_ignores_limit_for_caller_to_apply() -> None:
    matcher = compile_commit_matcher(CommitLogFilterValues(limit=1))

    assert all(matcher(_entry(timestamp=index)) for index in range(5))


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    (
        ("", 0, ("key", "")),
        ("repo:sase ", 10, ("key", "")),
        ("rep", 3, ("key", "rep")),
        ("project:", 8, ("project", "")),
        ("project:sa", 10, ("project", "sa")),
        ("repo:", 5, ("repo", "")),
        ("repo:sase-core", 9, ("repo", "sase")),
        ('author:"Ada Lo', 14, ("author", "Ada Lo")),
        ("repo:sase,co", 12, ("repo", "co")),
        ('repo:"name,wi', 13, ("repo", "name,wi")),
        ("since:7", 7, ("since", "7")),
        ("until:today", 10, ("until", "toda")),
        ("limit:al", 7, ("limit", "a")),
        ("sidecar:t", 9, ("sidecar", "t")),
        ("-repo:plans", 11, ("repo", "plans")),
        ("-author:bo", 10, ("author", "bo")),
        ("-since:7", 8, ("key", "since:7")),
        ('-"generated ro', 14, ("text", "generated ro")),
        ('"fix live', 9, ("text", "fix live")),
        ("unknown:value", 13, ("key", "unknown:value")),
    ),
)
def test_completion_context_classifies_cursor_prefix(
    text: str,
    cursor: int,
    expected: tuple[str, str],
) -> None:
    kind, prefix, _negated = completion_context(text, cursor)
    assert (kind, prefix) == expected


def test_completion_context_reports_negative_polarity() -> None:
    assert completion_context("-repo:pl", 8) == ("repo", "pl", True)


def test_filter_chips_use_canonical_query_tokens() -> None:
    filters = parse_commit_filter_query(
        'author:"Ada Lovelace" repo:sase project:alpha '
        'sidecar:true limit:all "fix live"'
    )

    assert commit_filter_chips(filters) == (
        "project:alpha",
        "repo:sase",
        'author:"Ada Lovelace"',
        "sidecar:true",
        '"fix live"',
    )

    default = parse_commit_filter_query("sidecar:false since:24h")
    assert commit_filter_chips(default) == (
        "sidecar:false",
        "since:24h",
    )
    assert commit_filter_chips(parse_commit_filter_query("limit:40")) == (
        "sidecar:true",
        "limit:40",
    )
