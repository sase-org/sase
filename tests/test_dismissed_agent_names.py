"""Tests for dismissed-name compatibility helpers in ``sase.agent.names``."""

from __future__ import annotations

from datetime import date, datetime

from sase.agent.names import (
    add_dismissed_prefix,
    is_dismissed_prefixed,
    strip_dismissed_prefix,
)

_DAY = date(2026, 4, 28)  # YYmmdd -> "260428"
_OTHER_DAY = date(2026, 4, 29)  # -> "260429"


class TestIsDismissedPrefixed:
    def test_matches_canonical_prefix(self) -> None:
        assert is_dismissed_prefixed("260428.foo")

    def test_matches_with_collision_suffix(self) -> None:
        assert is_dismissed_prefixed("260428.foo_2")

    def test_matches_when_base_has_dots(self) -> None:
        assert is_dismissed_prefixed("260428.m.claude.plan")

    def test_rejects_non_prefixed_name(self) -> None:
        assert not is_dismissed_prefixed("foo")

    def test_rejects_repeat_suffix_only(self) -> None:
        assert not is_dismissed_prefixed("a.1")

    def test_rejects_short_digit_run(self) -> None:
        assert not is_dismissed_prefixed("12345.foo")

    def test_rejects_long_digit_run(self) -> None:
        assert not is_dismissed_prefixed("1234567.foo")

    def test_rejects_missing_dot(self) -> None:
        assert not is_dismissed_prefixed("260428foo")

    def test_rejects_empty_string(self) -> None:
        assert not is_dismissed_prefixed("")


class TestAddDismissedPrefix:
    def test_adds_prefix_for_simple_name(self) -> None:
        assert add_dismissed_prefix("foo", _DAY) == "260428.foo"

    def test_accepts_datetime_input(self) -> None:
        ts = datetime(2026, 4, 28, 14, 30)
        assert add_dismissed_prefix("foo", ts) == "260428.foo"

    def test_idempotent_when_already_prefixed(self) -> None:
        assert add_dismissed_prefix("260428.foo", _DAY) == "260428.foo"

    def test_idempotent_ignores_caller_date_when_already_prefixed(self) -> None:
        assert add_dismissed_prefix("260428.foo", _OTHER_DAY) == "260428.foo"

    def test_preserves_dotted_base(self) -> None:
        assert add_dismissed_prefix("m.claude.plan", _DAY) == "260428.m.claude.plan"

    def test_preserves_repeat_suffix(self) -> None:
        assert add_dismissed_prefix("a.1", _DAY) == "260428.a.1"

    def test_preserves_workflow_child_segment(self) -> None:
        assert add_dismissed_prefix("sase-z.2.code", _DAY) == "260428.sase-z.2.code"


class TestStripDismissedPrefix:
    def test_strips_canonical_prefix(self) -> None:
        assert strip_dismissed_prefix("260428.foo") == "foo"

    def test_strips_only_one_prefix(self) -> None:
        assert strip_dismissed_prefix("260428.260429.foo") == "260429.foo"

    def test_preserves_collision_suffix(self) -> None:
        assert strip_dismissed_prefix("260428.foo_2") == "foo_2"

    def test_preserves_dotted_base(self) -> None:
        assert strip_dismissed_prefix("260428.m.claude.plan") == "m.claude.plan"

    def test_returns_input_when_unprefixed(self) -> None:
        assert strip_dismissed_prefix("foo") == "foo"

    def test_returns_input_for_repeat_suffix_only(self) -> None:
        assert strip_dismissed_prefix("a.1") == "a.1"
