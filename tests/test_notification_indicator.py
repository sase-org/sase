"""Tests for the NotificationIndicator widget rendering."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from rich.cells import cell_len

from sase.ace.tui.modals.notification_modal_tags import (
    MUTED_TAB_KEY,
    SNOOZED_TAB_KEY,
    NotificationTagTab,
    classify_notification_modal_tabs,
)
from sase.ace.tui.widgets import notification_tab_style
from sase.ace.tui.widgets.notification_indicator import NotificationIndicator
from sase.ace.tui.widgets.notification_tab_style import (
    resolve_notification_tab_color,
    resolve_notification_tab_icons,
)
from sase.core.time import get_timezone
from sase.notifications import Notification


@pytest.fixture(autouse=True)
def _no_config(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Start every test from an empty ``ace`` block, cached per test."""
    _use_config(monkeypatch, {})
    yield
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()


def _use_config(monkeypatch: pytest.MonkeyPatch, ace: dict[str, Any]) -> None:
    """Point the resolver at *ace* with a token that busts its own cache."""
    notification_tab_style._configured_tab_styles_for_token.cache_clear()
    notification_tab_style._indicator_max_counts_for_token.cache_clear()
    monkeypatch.setattr(
        notification_tab_style,
        "load_merged_config",
        lambda: {"ace": ace},
    )


def _resolve_notification_tab_icon(tab: NotificationTagTab) -> str:
    return resolve_notification_tab_icons((tab,))[tab.tag]


def _tab(
    tag: str | None,
    count: int,
    *,
    label: str | None = None,
    oldest_activity_at: str | None = None,
    next_wake_at: str | None = None,
    icon: str | None = None,
    kind: str = "",
) -> NotificationTagTab:
    return NotificationTagTab(
        tag=tag,
        label=label or ("General" if tag is None else tag.title()),
        count=count,
        kind=kind,
        oldest_activity_at=oldest_activity_at,
        next_wake_at=next_wake_at,
        icon=icon,
    )


def _ago(minutes: int) -> str:
    return (datetime.now(get_timezone()) - timedelta(minutes=minutes)).isoformat()


def _ahead(minutes: int) -> str:
    # The half-minute keeps ``format_relative_until``'s flooring from shaving
    # a minute off the expected phrase while the test runs.
    ahead = timedelta(minutes=minutes, seconds=30)
    return (datetime.now(get_timezone()) + ahead).isoformat()


def test_the_widget_special_cases_the_same_keys_the_panel_uses() -> None:
    """The widget spells these locally to dodge an import cycle; keep them equal."""
    from sase.ace.tui.widgets import notification_indicator

    assert notification_indicator.SNOOZED_TAB_KEY == SNOOZED_TAB_KEY
    assert notification_indicator.MUTED_TAB_KEY == MUTED_TAB_KEY


def test_no_tabs_renders_dim_collapsed_envelope() -> None:
    text = NotificationIndicator._build_content(())
    assert text.plain == " ✉ 0 "
    assert "dim" in str(text.style)


def test_empty_tabs_are_dropped_from_the_badge() -> None:
    text = NotificationIndicator._build_content((_tab("hitl", 0),))
    assert text.plain == " ✉ 0 "


def test_one_tab_renders_one_chip() -> None:
    text = NotificationIndicator._build_content((_tab("hitl", 2),))
    assert text.plain == " ⚑2 "


def test_three_tabs_render_three_chips_joined_by_single_spaces() -> None:
    text = NotificationIndicator._build_content(
        (_tab("hitl", 2), _tab("beads", 3), _tab("errors", 1))
    )
    assert text.plain == " ⚑2 ◈3 ✖1 "


def test_the_envelope_anchor_is_dropped_once_any_chip_is_present() -> None:
    """``general`` owns ``✉`` now, so an anchor would render the glyph twice."""
    text = NotificationIndicator._build_content((_tab("hitl", 2), _tab(None, 1)))
    assert text.plain == " ⚑2 ✉1 "


def test_a_sender_declared_icon_reaches_the_chip() -> None:
    text = NotificationIndicator._build_content((_tab("deploys", 3, icon="🚀"),))
    assert text.plain == " 🚀3 "


def test_chip_order_follows_input_tab_order() -> None:
    """The leftmost chip is the leftmost panel tab; that is what makes it readable."""
    tabs = (_tab("beads", 7), _tab("hitl", 5), _tab("errors", 9))
    assert NotificationIndicator._build_content(tabs).plain == " ◈7 ⚑5 ✖9 "


def test_each_chip_carries_its_own_resolved_tab_color() -> None:
    tabs = (_tab("hitl", 2), _tab("errors", 1))
    text = NotificationIndicator._build_content(tabs)
    styles = [str(span.style) for span in text.spans]
    assert f"bold {resolve_notification_tab_color(tabs[0])}" in styles
    assert f"bold {resolve_notification_tab_color(tabs[1])}" in styles


def test_snoozed_only_renders_the_moon_prefixed_count() -> None:
    tab = _tab(SNOOZED_TAB_KEY, 4)
    text = NotificationIndicator._build_content((tab,))
    assert text.plain == " ☾4 "
    assert _resolve_notification_tab_icon(tab) == "☾"
    snoozed_style = str(text.spans[0].style)
    assert snoozed_style.startswith("dim ")
    assert "#6C6C6C" in snoozed_style


def test_snoozed_chip_disappears_as_soon_as_anything_else_is_pending() -> None:
    tabs = (_tab("beads", 3), _tab(SNOOZED_TAB_KEY, 4))
    assert NotificationIndicator._build_content(tabs).plain == " ◈3 "


def test_muted_keeps_its_own_chip() -> None:
    """Only snoozed is special-cased; muted is an ordinary tab now."""
    tabs = (_tab("beads", 3), _tab(MUTED_TAB_KEY, 2))
    assert NotificationIndicator._build_content(tabs).plain == " ◈3 ⊘2 "


def test_overflow_beyond_the_configured_maximum_collapses_into_plus_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_indicator_max_counts": 2})
    tabs = (_tab("hitl", 1), _tab("beads", 2), _tab("errors", 3), _tab("docs", 4))
    assert NotificationIndicator._build_content(tabs).plain == " ⚑1 ◈2 +2 "


def test_default_maximum_admits_four_chips() -> None:
    tabs = tuple(_tab(f"tag{index}", index + 1) for index in range(5))
    assert NotificationIndicator._build_content(tabs).plain == " •1 t2 a3 g4 +1 "


def test_two_tag_tabs_render_distinct_chips() -> None:
    tabs = (_tab("axe", 2, kind="tag"), _tab("done", 3, kind="tag"))

    text = NotificationIndicator._build_content(tabs).plain

    assert text.startswith(" ")
    chips = text.strip().split()
    assert chips == ["#2", "d3"]


def test_overflow_tooltip_still_describes_every_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_indicator_max_counts": 1})
    tabs = (_tab("hitl", 1), _tab("beads", 2), _tab("errors", 3))
    tooltip = NotificationIndicator._build_tooltip(tabs).plain
    for label in ("Hitl", "Beads", "Errors"):
        assert label in tooltip


def test_tooltip_empty_state_reads_no_unread() -> None:
    assert NotificationIndicator._build_tooltip(()).plain == "No unread notifications"


def test_tooltip_mixed_state_briefs_every_tab() -> None:
    tabs = (
        _tab("hitl", 2, label="HITL", oldest_activity_at=_ago(14)),
        _tab("beads", 3, oldest_activity_at=_ago(120)),
        _tab("errors", 1, oldest_activity_at=_ago(5)),
        _tab(SNOOZED_TAB_KEY, 4, label="Snoozed", next_wake_at=_ahead(43)),
        _tab(MUTED_TAB_KEY, 2, label="Muted"),
    )
    lines = NotificationIndicator._build_tooltip(tabs).plain.splitlines()
    assert lines[0] == "6 unread · 3 tabs"
    assert lines[1] == " ⚑ HITL     2   oldest 14m ago"
    assert lines[2] == " ◈ Beads    3   oldest 2h ago"
    assert lines[3] == " ✖ Errors   1   oldest 5m ago"
    assert lines[4] == " ☾ Snoozed  4   next wakes in 43m"
    assert lines[5] == " ⊘ Muted    2"
    assert lines[6] == "Click to open the notification panel"


def test_tooltip_columns_stay_aligned_around_a_two_cell_icon() -> None:
    """A wide icon must not shift the count column on its neighbours' lines."""
    tabs = (
        _tab("deploys", 2, label="Deploys", icon="🚀"),
        _tab("hitl", 1, label="HITL"),
    )
    lines = NotificationIndicator._build_tooltip(tabs).plain.splitlines()
    assert lines[1] == " 🚀 Deploys  2"
    assert lines[2] == " ⚑  HITL     1"
    assert cell_len(lines[1]) == cell_len(lines[2])


def test_tooltip_header_counts_only_actionable_tabs() -> None:
    """Snoozed and muted rows are informational, never part of "unread"."""
    tabs = (_tab("beads", 3), _tab(SNOOZED_TAB_KEY, 9), _tab(MUTED_TAB_KEY, 7))
    assert NotificationIndicator._build_tooltip(tabs).plain.splitlines()[0] == (
        "3 unread · 1 tab"
    )


def test_tooltip_snoozed_only_state_reports_the_wake_without_claiming_unread() -> None:
    tabs = (_tab(SNOOZED_TAB_KEY, 4, label="Snoozed", next_wake_at=_ahead(43)),)
    lines = NotificationIndicator._build_tooltip(tabs).plain.splitlines()
    assert lines[0] == "No unread notifications"
    assert lines[1] == " ☾ Snoozed  4   next wakes in 43m"


def test_tooltip_labels_carry_their_tab_colors() -> None:
    tabs = (_tab("hitl", 2), _tab("errors", 1))
    text = NotificationIndicator._build_tooltip(tabs)
    styles = [str(span.style) for span in text.spans]
    assert resolve_notification_tab_color(tabs[0]) in styles
    assert resolve_notification_tab_color(tabs[1]) in styles


def test_set_tabs_updates_tooltip() -> None:
    indicator = NotificationIndicator()
    assert indicator.tooltip.plain == "No unread notifications"
    indicator.set_tabs([_tab("beads", 3)])
    assert indicator.tooltip.plain.splitlines()[0] == "3 unread · 1 tab"


def test_set_tabs_ignores_a_repeated_tab_list() -> None:
    indicator = NotificationIndicator()
    indicator.set_tabs([_tab("beads", 3)])
    before = indicator.tooltip
    indicator.set_tabs([_tab("beads", 3)])
    assert indicator.tooltip is before


def _notification(notification_id: str, **kwargs: Any) -> Notification:
    return Notification(
        id=notification_id,
        timestamp=_ago(1),
        sender="pytest",
        **kwargs,
    )


def test_indicator_chips_correspond_one_to_one_with_the_panel_tabs() -> None:
    """The badge and the panel must never disagree about what is waiting."""
    notifications = [
        _notification("a", tags=["alpha", "beta"]),
        _notification("b", tags=["alpha"]),
        _notification("c", action="UserQuestion"),
        _notification("d", muted=True, snooze_until=_ahead(30)),
    ]
    tabs, _ = classify_notification_modal_tabs(notifications)
    chips = NotificationIndicator._build_content(tabs).plain
    expected = [tab for tab in tabs if tab.count and tab.tag != SNOOZED_TAB_KEY]
    icons = resolve_notification_tab_icons(tabs)
    assert chips == " {} ".format(
        " ".join(f"{icons[tab.tag]}{tab.count}" for tab in expected)
    )
    assert sum(tab.count for tab in tabs) == len(notifications)


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


def test_chip_order_follows_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"beads": {"priority": 0}}})
    notifications = [
        _notification("b", action="TaskTriage", action_data={"panel": "beads"}),
        _notification("g", action="PlanApproval"),
        _notification("t", tags=["review"]),
    ]
    tabs, _ = classify_notification_modal_tabs(notifications)
    icons = resolve_notification_tab_icons(tabs)
    expected = [tab for tab in tabs if tab.count]

    assert [tab.tag for tab in expected] == ["hitl", "review", "beads"]
    assert NotificationIndicator._build_content(tabs).plain == " {} ".format(
        " ".join(f"{icons[tab.tag]}{tab.count}" for tab in expected)
    )


def test_tooltip_names_a_deviating_priority_and_leaves_unmarked_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"beads": {"priority": 0}}})
    tabs = (
        _tab("hitl", 2, label="HITL", kind="hitl", oldest_activity_at=_ago(14)),
        _tab("beads", 3, kind="panel", oldest_activity_at=_ago(120)),
        _tab(MUTED_TAB_KEY, 2, label="Muted", kind="muted"),
    )
    lines = NotificationIndicator._build_tooltip(tabs).plain.splitlines()

    assert lines[1] == " ⚑ HITL   2   oldest 14m ago"
    assert lines[2] == " ◈ Beads  3   oldest 2h ago · ▾ priority 0"
    assert lines[3] == " ⊘ Muted  2"


def test_tooltip_priority_fragment_stands_alone_when_there_is_no_time_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_config(monkeypatch, {"notification_tabs": {"muted": {"priority": 5}}})
    tabs = (_tab(MUTED_TAB_KEY, 2, label="Muted", kind="muted"),)
    lines = NotificationIndicator._build_tooltip(tabs).plain.splitlines()

    assert lines[1] == " ⊘ Muted  2   ▴ priority 5"
