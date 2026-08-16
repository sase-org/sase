"""Coverage for plans filter query completion-context classification."""

from __future__ import annotations

import pytest

from sase.plan_search.filter_query import plan_completion_context


@pytest.mark.parametrize(
    ("text", "cursor", "expected"),
    (
        ("", 0, ("key", "")),
        ("kind:epic ", 10, ("key", "")),
        ("sta", 3, ("key", "sta")),
        ("kind:", 5, ("kind", "")),
        ("status:in_progress", 12, ("status", "in_pr")),
        ('project:"SASE Co', 16, ("project", "SASE Co")),
        ("kind:epic,ph", 12, ("kind", "ph")),
        ('status:"needs,re', 16, ("status", "needs,re")),
        ("since:7", 7, ("since", "7")),
        ("until:today", 10, ("until", "toda")),
        ("-kind:archive", 13, ("kind", "archive")),
        ("-status:bl", 10, ("status", "bl")),
        ("-since:7", 8, ("key", "since:7")),
        ('-"generated ro', 14, ("text", "generated ro")),
        ('"filter li', 10, ("text", "filter li")),
        ("unknown:value", 13, ("key", "unknown:value")),
    ),
)
def test_completion_context_classifies_cursor_prefix(
    text: str,
    cursor: int,
    expected: tuple[str, str],
) -> None:
    kind, prefix, _negated = plan_completion_context(text, cursor)
    assert (kind, prefix) == expected


def test_plan_completion_context_reports_negative_polarity() -> None:
    assert plan_completion_context("-status:bl", 10) == ("status", "bl", True)
