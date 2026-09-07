"""Coverage for canonical plans filter query serialization and round-tripping."""

from __future__ import annotations

from datetime import datetime

from hypothesis import HealthCheck, given, settings, strategies as st

from sase.core.time import get_timezone
from sase.plan_search.filter_query import (
    PlanFilterValues,
    parse_plan_filter_query,
    to_query_string,
    to_query_tokens,
)
from sase.vcs_log.dates import parse_time_bound


def test_canonical_query_has_stable_order() -> None:
    tz = get_timezone()
    now = datetime(2026, 7, 18, 12, 0, tzinfo=tz)

    values = parse_plan_filter_query(
        'preview project:"SASE Core" until:2026-07-18 status:ready '
        'kind:phase since:7d tier:epic "filter bar"',
        now=now,
    )

    assert to_query_tokens(values) == (
        "kind:phase",
        "status:ready",
        "tier:epic",
        'project:"SASE Core"',
        "since:7d",
        "until:2026-07-18",
        "preview",
        '"filter bar"',
    )
    assert to_query_string(values) == " ".join(to_query_tokens(values))
    assert to_query_string(PlanFilterValues()) == ""


def test_canonical_query_serializes_exclusions_in_facet_order() -> None:
    values = parse_plan_filter_query(
        "project:sase -status:blocked kind:phase -kind:archive "
        '-project:"SASE Core" "-literal" -generated'
    )

    assert to_query_tokens(values) == (
        "kind:phase",
        "-kind:archive",
        "-status:blocked",
        "project:sase",
        '-project:"SASE Core"',
        '"-literal"',
        "-generated",
    )


_VALUE_TEXT = st.text(
    alphabet='abcXYZ 09,:\\"-@.',
    min_size=1,
    max_size=18,
)


@settings(suppress_health_check=[HealthCheck.too_slow])
@given(
    kinds=st.lists(
        st.sampled_from(("proposal", "task", "epic", "phase", "archive")),
        max_size=4,
    ).map(tuple),
    statuses=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_kinds=st.lists(
        st.sampled_from(("proposal", "task", "epic", "phase", "archive")),
        max_size=4,
    ).map(tuple),
    excluded_statuses=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    tiers=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_tiers=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    projects=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_projects=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    text_terms=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
    excluded_text=st.lists(_VALUE_TEXT, max_size=3).map(tuple),
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
    kinds: tuple[str, ...],
    statuses: tuple[str, ...],
    excluded_kinds: tuple[str, ...],
    excluded_statuses: tuple[str, ...],
    tiers: tuple[str, ...],
    excluded_tiers: tuple[str, ...],
    projects: tuple[str, ...],
    excluded_projects: tuple[str, ...],
    text_terms: tuple[str, ...],
    excluded_text: tuple[str, ...],
    bounds: tuple[str, str],
) -> None:
    since_text, until_text = bounds
    tz = get_timezone()
    now = datetime(2026, 7, 18, 12, 0, tzinfo=tz)
    values = PlanFilterValues(
        kinds=kinds,
        excluded_kinds=excluded_kinds,
        statuses=statuses,
        excluded_statuses=excluded_statuses,
        tiers=tiers,
        excluded_tiers=excluded_tiers,
        projects=projects,
        excluded_projects=excluded_projects,
        since_text=since_text,
        until_text=until_text,
        since=(
            parse_time_bound(since_text).resolve(now=now, boundary="since")
            if since_text
            else None
        ),
        until=(
            parse_time_bound(until_text).resolve(now=now, boundary="until")
            if until_text
            else None
        ),
        text=text_terms,
        excluded_text=excluded_text,
    )

    assert parse_plan_filter_query(to_query_string(values), now=now) == values
