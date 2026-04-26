"""Tests for the NotificationIndicator widget rendering."""

from sase.ace.tui.widgets.notification_indicator import NotificationIndicator


def test_zero_unread_zero_muted_renders_dim_envelope() -> None:
    text = NotificationIndicator._build_content(0, 0)
    assert text.plain == " ✉ 0 "


def test_unread_only_renders_gold_envelope() -> None:
    text = NotificationIndicator._build_content(5, 0)
    assert text.plain == " ✉ 5 "


def test_muted_only_renders_dim_envelope_with_secondary() -> None:
    text = NotificationIndicator._build_content(0, 2)
    assert text.plain == " ✉ 0 ·2 "


def test_unread_and_muted_renders_both_segments() -> None:
    text = NotificationIndicator._build_content(5, 2)
    assert text.plain == " ✉ 5 ·2 "


def test_secondary_segment_suppressed_when_muted_zero() -> None:
    """No secondary `·N` segment renders when muted is zero."""
    text = NotificationIndicator._build_content(3, 0)
    assert "·" not in text.plain
