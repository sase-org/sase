"""Coverage for how the plans query index matches individual filter records."""

from __future__ import annotations

import pytest

from sase.plan_search.filter_query import PlanFilterValues, to_query_string
from tests._plan_filter_query_helpers import epoch, plan_record, query_matches_record


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({}, True),
        ({"kind": "archive"}, False),
        ({"status_labels": frozenset(("closed",))}, False),
        ({"tier_labels": frozenset(("plan",))}, False),
        ({"project": "other", "project_display_name": "Other"}, False),
        ({"timestamp": epoch(2026, 6, 30, 23, 59)}, False),
        ({"timestamp": epoch(2026, 7, 1, 0, 11)}, False),
        ({"timestamp": None}, False),
        ({"haystack": ("plans filter bar",)}, False),
        ({"haystack": ("search index", "plans filter bar")}, True),
    ),
)
def test_plan_query_index_ors_within_keys_and_ands_across_keys_and_text(
    changes: dict[str, object],
    expected: bool,
) -> None:
    window_start = epoch(2026, 7, 1, 0, 0)
    matching_timestamp = epoch(2026, 7, 1, 0, 5)
    window_end = epoch(2026, 7, 1, 0, 10)
    query = to_query_string(
        PlanFilterValues(
            kinds=("EPIC", "phase"),
            statuses=("blocked", "READY"),
            tiers=("EPIC", "tale"),
            projects=("SASE", "sase-core"),
            since_text="2026-07-01T00:00",
            since=window_start,
            until_text="2026-07-01T00:10",
            until=window_end,
            text=("FILTER", "index"),
        )
    )

    record_changes = {"timestamp": matching_timestamp, **changes}
    assert query_matches_record(query, plan_record(**record_changes)) is expected


def test_plan_query_index_negative_facets_and_text_veto_multi_label_records() -> None:
    base = plan_record()
    assert (
        query_matches_record(
            to_query_string(
                PlanFilterValues(statuses=("open",), excluded_statuses=("ready",))
            ),
            base,
        )
        is False
    )
    assert (
        query_matches_record(
            to_query_string(
                PlanFilterValues(tiers=("epic",), excluded_tiers=("plan",))
            ),
            base,
        )
        is True
    )
    assert (
        query_matches_record(
            to_query_string(
                PlanFilterValues(projects=("SASE",), excluded_projects=("other",))
            ),
            base,
        )
        is True
    )
    assert (
        query_matches_record(
            to_query_string(
                PlanFilterValues(kinds=("epic",), excluded_kinds=("EPIC",))
            ),
            base,
        )
        is False
    )
    assert (
        query_matches_record(
            to_query_string(
                PlanFilterValues(text=("filter",), excluded_text=("INDEX",))
            ),
            base,
        )
        is False
    )


def test_timestamp_bounds_include_endpoints_and_ignore_missing_without_bounds() -> None:
    assert query_matches_record(
        to_query_string(
            PlanFilterValues(
                since_text="2026-07-01T00:00",
                since=epoch(2026, 7, 1, 0, 0),
            )
        ),
        plan_record(timestamp=epoch(2026, 7, 1, 0, 0)),
    )
    assert query_matches_record(
        to_query_string(
            PlanFilterValues(
                until_text="2026-07-01T00:00",
                until=epoch(2026, 7, 1, 0, 0),
            )
        ),
        plan_record(timestamp=epoch(2026, 7, 1, 0, 0)),
    )
    assert query_matches_record(
        to_query_string(PlanFilterValues(text=("search",))),
        plan_record(timestamp=None),
    )
