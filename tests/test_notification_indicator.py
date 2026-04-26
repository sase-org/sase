"""Tests for the NotificationIndicator widget rendering."""

from sase.ace.tui.widgets.notification_indicator import NotificationIndicator


def test_all_zero_renders_dim_collapsed_envelope() -> None:
    text = NotificationIndicator._build_content(0, 0, 0)
    assert text.plain == " ✉ 0 "
    assert "dim" in str(text.style)


def test_rest_only_renders_gold_split_envelope() -> None:
    text = NotificationIndicator._build_content(0, 3, 0)
    assert text.plain == " ✉ 0+3 "
    assert "#FFD700" in str(text.style)


def test_priority_only_renders_red_split_envelope() -> None:
    text = NotificationIndicator._build_content(2, 0, 0)
    assert text.plain == " ✉ 2+0 "
    assert "#FF4444" in str(text.style)


def test_priority_dominates_when_both_present() -> None:
    text = NotificationIndicator._build_content(2, 3, 0)
    assert text.plain == " ✉ 2+3 "
    assert "#FF4444" in str(text.style)


def test_muted_only_renders_dim_cyan_with_secondary() -> None:
    text = NotificationIndicator._build_content(0, 0, 4)
    assert text.plain == " ✉ 0+0 ·4 "
    assert "#5FAFAF" in str(text.style)


def test_priority_with_muted_renders_red_primary_and_secondary() -> None:
    text = NotificationIndicator._build_content(1, 0, 2)
    assert text.plain == " ✉ 1+0 ·2 "
    assert "#FF4444" in str(text.style)


def test_rest_with_muted_renders_gold_primary_and_secondary() -> None:
    text = NotificationIndicator._build_content(0, 2, 1)
    assert text.plain == " ✉ 0+2 ·1 "
    assert "#FFD700" in str(text.style)


def test_secondary_segment_suppressed_when_muted_zero() -> None:
    text = NotificationIndicator._build_content(2, 1, 0)
    assert "·" not in text.plain
