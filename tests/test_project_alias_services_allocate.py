"""Tests for project name allocation."""

from __future__ import annotations

import pytest

from sase.project_aliases import allocate_project_name
from tests._project_alias_services_helpers import _record


def test_allocate_project_name_uses_available_base() -> None:
    assert allocate_project_name("foo", [_record("alpha")]) == "foo"


def test_allocate_project_name_walks_underscore_suffixes() -> None:
    records = [
        _record("foo"),
        _record("alpha", aliases=["foo_1"]),
        _record("beta", display_name="foo_2"),
    ]

    assert allocate_project_name("foo", records) == "foo_3"


def test_allocate_project_name_counts_alias_and_display_collisions() -> None:
    records = [
        _record("alpha", aliases=["widgets"]),
        _record("beta", display_name="widgets_1"),
    ]

    assert allocate_project_name("widgets", records) == "widgets_2"


def test_allocate_project_name_reuses_current_project_display_name() -> None:
    records = [
        _record("alpha", display_name="widgets"),
        _record("beta", aliases=["widgets_1"]),
    ]

    assert allocate_project_name("widgets", records, project_name="alpha") == "widgets"


def test_allocate_project_name_rejects_invalid_base() -> None:
    with pytest.raises(ValueError, match="invalid project name"):
        allocate_project_name(".hidden", [])


def test_allocate_project_name_is_case_insensitive() -> None:
    records = [
        _record(
            "alpha",
            archive_file="/tmp/projects/alpha/alpha.archive",
            aliases=["Widgets"],
        ),
    ]

    assert allocate_project_name("widgets", records) == "widgets_1"
    assert allocate_project_name("WIDGETS", records) == "WIDGETS_1"
