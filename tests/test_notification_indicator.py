"""Tests for the NotificationIndicator widget rendering."""

from sase.ace.tui.widgets.notification_indicator import NotificationIndicator


def test_all_zero_renders_dim_collapsed_envelope() -> None:
    text = NotificationIndicator._build_content(0, 0, 0)
    assert text.plain == " ✉ 0 "
    assert "dim" in str(text.style)


def test_rest_only_renders_gold_envelope() -> None:
    text = NotificationIndicator._build_content(0, 3, 0)
    assert text.plain == " ✉ 3 "
    assert "#FFD700" in str(text.style)


def test_priority_only_renders_orange_single_count() -> None:
    text = NotificationIndicator._build_content(2, 0, 0)
    assert text.plain == " ✉ 2 "
    assert "#FF8700" in str(text.style)


def test_priority_and_rest_render_summed_orange_count() -> None:
    text = NotificationIndicator._build_content(2, 3, 0)
    assert text.plain == " ✉ 5 "
    assert "#FF8700" in str(text.style)


def test_muted_only_collapses_to_single_count_dim_cyan() -> None:
    text = NotificationIndicator._build_content(0, 0, 4)
    assert text.plain == " ✉ 4 "
    assert "#5FAFAF" in str(text.style)


def test_priority_with_muted_renders_orange_badge_and_bare_dot() -> None:
    text = NotificationIndicator._build_content(1, 0, 2)
    assert text.plain == " ✉ 1 · "
    assert "#FF8700" in str(text.style)


def test_rest_with_muted_renders_gold_badge_and_bare_dot() -> None:
    text = NotificationIndicator._build_content(0, 2, 1)
    assert text.plain == " ✉ 2 · "
    assert "#FFD700" in str(text.style)


def test_muted_dot_suppressed_when_muted_zero() -> None:
    text = NotificationIndicator._build_content(2, 1, 0)
    assert "·" not in text.plain


def test_muted_dot_carries_no_digits() -> None:
    """The muted marker is a bare dot; the exact figure lives in the tooltip."""
    text = NotificationIndicator._build_content(1, 2, 7)
    assert text.plain == " ✉ 3 · "
    assert "7" not in text.plain


def test_snooze_to_unread_transition_changes_buckets() -> None:
    """A snoozed row (muted=1) flipping to unread (rest=1) renders the swap."""
    snoozed = NotificationIndicator._build_content(0, 0, 1)
    expired = NotificationIndicator._build_content(0, 1, 0)
    assert snoozed.plain == " ✉ 1 "
    assert expired.plain == " ✉ 1 "


def test_tooltip_all_zero_reads_no_unread() -> None:
    assert NotificationIndicator._build_tooltip(0, 0, 0) == "No unread notifications"


def test_tooltip_mixed_lists_every_nonzero_bucket() -> None:
    tooltip = NotificationIndicator._build_tooltip(2, 3, 1)
    assert tooltip == "2 priority · 3 other · 1 muted"


def test_tooltip_muted_only_lists_muted_bucket() -> None:
    assert NotificationIndicator._build_tooltip(0, 0, 4) == "4 muted"


def test_set_counts_updates_tooltip() -> None:
    indicator = NotificationIndicator()
    assert indicator.tooltip == "No unread notifications"
    indicator.set_counts(2, 3, 1)
    assert indicator.tooltip == "2 priority · 3 other · 1 muted"


async def test_click_dispatches_show_notifications_action() -> None:
    from textual.app import App, ComposeResult

    calls: list[str] = []

    class _TestApp(App[None]):
        def compose(self) -> ComposeResult:
            yield NotificationIndicator(id="notification-indicator")

        def action_show_notifications(self) -> None:
            calls.append("shown")

    app = _TestApp()
    async with app.run_test() as pilot:
        await pilot.click("#notification-indicator")
        await pilot.pause()
        assert calls == ["shown"]
