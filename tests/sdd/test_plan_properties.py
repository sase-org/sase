from __future__ import annotations

from datetime import date

import pytest

from sase.sdd.plan_properties import (
    ordered_plan_property_items,
    plan_property_label,
    render_plan_value_lines,
)


def test_ordered_plan_property_items_puts_known_keys_before_alphabetical_tail():
    frontmatter = {
        "zeta": "last",
        "goal": "Ship it",
        "Title": "Example",
        "alpha": "first unknown",
        "tier": "tale",
    }

    assert [key for key, _value in ordered_plan_property_items(frontmatter)] == [
        "Title",
        "tier",
        "goal",
        "alpha",
        "zeta",
    ]


def test_ordered_plan_property_items_uses_declared_detail_fields_first():
    frontmatter = {
        "zeta": "last",
        "title": "Example",
        "status": "draft",
        "create_time": "2026-08-14",
        "tags": ["alpha"],
    }

    assert [
        key
        for key, _value in ordered_plan_property_items(
            frontmatter,
            detail_fields=("status", "create_time", "tags"),
        )
    ] == [
        "status",
        "create_time",
        "tags",
        "title",
        "zeta",
    ]


def test_ordered_plan_property_items_empty_detail_fields_fall_back_to_plan_order():
    frontmatter = {
        "zeta": "last",
        "goal": "Ship it",
        "title": "Example",
        "tier": "tale",
    }

    assert [
        key
        for key, _value in ordered_plan_property_items(
            frontmatter,
            detail_fields=("", "   "),
        )
    ] == [
        "title",
        "tier",
        "goal",
        "zeta",
    ]


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("create_time", "Create time"),
        ("  mixed_CASE  ", "Mixed case"),
        ("title", "Title"),
        ("", ""),
    ],
)
def test_plan_property_label_humanizes_keys(key: str, expected: str):
    assert plan_property_label(key) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ["—"]),
        (True, ["true"]),
        (False, ["false"]),
        (date(2026, 7, 23), ["2026-07-23"]),
        ("", ["—"]),
        ("first\nsecond", ["first", "second"]),
        ([], ["[]"]),
        ({}, ["{}"]),
    ],
)
def test_render_plan_value_lines_handles_scalars_and_empties(value, expected):
    assert render_plan_value_lines(value) == expected


def test_render_plan_value_lines_handles_lists_and_nested_epic_phases():
    phases = [
        {
            "id": "research",
            "depends_on": [],
            "details": {"enabled": True, "models": ["fast", "deep"]},
        },
        {"id": "implementation", "depends_on": ["research"]},
    ]

    assert render_plan_value_lines(phases) == [
        "•",
        "  id: research",
        "  depends_on: []",
        "  details:",
        "    enabled: true",
        "    models:",
        "      • fast",
        "      • deep",
        "•",
        "  id: implementation",
        "  depends_on: • research",
    ]


def test_render_plan_value_lines_orders_sets_deterministically():
    assert render_plan_value_lines({"zeta", "Alpha", "beta"}) == [
        "• Alpha",
        "• beta",
        "• zeta",
    ]


def test_render_plan_value_lines_guards_recursive_structures():
    recursive: list[object] = []
    recursive.append(recursive)

    assert render_plan_value_lines(recursive) == [
        "• ↻ recursive reference",
    ]
