"""Badge, evidence group, and +1 pane iteration for the notification modal."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_constants import DEFAULT_HINT_TEXT
from sase.ace.tui.modals.notification_modal_gate import NotificationSummaryMixin
from sase.ace.tui.modals.notification_modal_plus_ones import (
    plus_one_evidence_renderables,
    plus_one_report_suffix,
)
from sase.bead.plus_one_presentation import PLUS_ONE_RICH_STYLE, PLUS_ONE_SECTION_LABEL
from sase.notifications import Notification, NotificationPlusOne
from tests._notification_modal_helpers import _KeyEvent, _make_notification


def _style_for(text: Any, fragment: str) -> str | None:
    for start, end, style in text.spans:
        if text.plain[start:end] == fragment:
            return str(style)
    return None


def _render_plain(renderable: object) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


def _plus_ones(*notes: str) -> list[NotificationPlusOne]:
    return [
        NotificationPlusOne(
            timestamp=f"2026-07-29T10:{index:02d}:00-04:00",
            sender="ci_watch",
            note=note,
        )
        for index, note in enumerate(notes, start=1)
    ]


class _SummaryPane(NotificationSummaryMixin):
    def __init__(self) -> None:
        self._current_file_index = 0


def test_styled_label_appends_accent_plus_one_badge_after_title() -> None:
    notification = _make_notification("n1")
    notification.notes = ["CI failure: sase-org/sase"]
    notification.plus_ones = _plus_ones("one", "two", "three")

    modal = NotificationModal([notification])
    label = modal._create_styled_label(notification)

    assert "[+3]" in label.plain
    assert label.plain.index("CI failure: sase-org/sase") < label.plain.index("[+3]")
    assert _style_for(label, "  [+3]") == PLUS_ONE_RICH_STYLE


def test_styled_label_badge_count_includes_dropped_overflow() -> None:
    notification = _make_notification("n1", plus_ones_dropped=2)
    notification.notes = ["CI failure"]
    notification.plus_ones = _plus_ones("still failing")

    label = NotificationModal([notification])._create_styled_label(notification)

    assert "[+3]" in label.plain
    assert "[+1]" not in label.plain


def test_styled_label_omits_plus_one_badge_when_empty() -> None:
    notification = _make_notification("n1")
    notification.notes = ["ordinary row"]

    label = NotificationModal([notification])._create_styled_label(notification)

    assert "[+" not in label.plain


def test_summary_pane_lists_plus_one_evidence_under_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_plus_ones.format_relative_time",
        lambda _timestamp: "2m ago",
    )
    notification = _make_notification("n1")
    notification.notes = ["CI failure: sase-org/sase"]
    notification.plus_ones = _plus_ones("recovered", "re-failed")

    title, content = _SummaryPane()._render_summary_pane(notification)
    plain = _render_plain(content)

    assert title == "Notification"
    assert "CI failure: sase-org/sase" in plain
    assert PLUS_ONE_SECTION_LABEL in plain
    assert "+1 ci_watch · 2m ago — recovered" in plain
    assert "+1 ci_watch · 2m ago — re-failed" in plain
    notes_at = plain.index("CI failure: sase-org/sase")
    evidence_at = plain.index(PLUS_ONE_SECTION_LABEL)
    assert notes_at < evidence_at


def test_evidence_group_is_absent_without_plus_ones() -> None:
    notification = _make_notification("n1")
    notification.notes = ["nothing to corroborate"]

    assert plus_one_evidence_renderables(notification) == []
    assert PLUS_ONE_SECTION_LABEL not in _render_plain(
        _SummaryPane()._render_summary_pane(notification)[1]
    )


def test_report_suffix_names_count_and_latest_age(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_plus_ones.format_relative_time",
        lambda _timestamp: "4m ago",
    )
    notification = _make_notification("n1")
    notification.plus_ones = _plus_ones("older", "newest")
    notification.plus_ones_dropped = 1

    suffix = plus_one_report_suffix(notification)

    assert suffix is not None
    assert suffix.plain == " · +3 (latest 4m ago)"
    assert _style_for(suffix, " · +3 (latest 4m ago)") == PLUS_ONE_RICH_STYLE


def test_plus_key_cycles_newest_first_then_wraps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_plus_ones.format_absolute_time",
        lambda _timestamp, now=None: "today 10:03",
    )
    notification = _make_notification("n1")
    notification.plus_ones = _plus_ones("oldest", "middle", "newest")
    modal = NotificationModal([notification])
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal._update_hint_footer = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]
    modal._get_highlighted_notification = (  # type: ignore[method-assign]
        lambda: notification
    )

    modal.action_cycle_plus_ones()
    assert modal._plus_one_cursor == 0
    title, content = modal._render_plus_one_pane(notification)
    plain = _render_plain(content)
    assert title == "+1"
    assert "+1 1/3 · ci_watch · today 10:03" in plain
    assert "newest" in plain
    assert "oldest" not in plain
    assert "+ next" in plain

    modal.action_cycle_plus_ones()
    assert modal._plus_one_cursor == 1
    assert "middle" in _render_plain(modal._render_plus_one_pane(notification)[1])

    modal.action_cycle_plus_ones()
    assert modal._plus_one_cursor == 2
    assert "oldest" in _render_plain(modal._render_plus_one_pane(notification)[1])

    modal.action_cycle_plus_ones()
    assert modal._plus_one_cursor is None
    assert modal._render_plus_one_pane(notification) is None
    assert modal._display_file.call_count == 4


def test_plus_key_without_entries_shows_status_hint() -> None:
    notification = _make_notification("n1")
    modal = NotificationModal([notification])
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]
    modal._get_highlighted_notification = (  # type: ignore[method-assign]
        lambda: notification
    )

    modal.action_cycle_plus_ones()

    modal.notify.assert_called_once_with("No +1 notes on this notification")
    modal._display_file.assert_not_called()
    assert modal._plus_one_cursor is None


def test_plus_key_event_is_consumed_before_app_bindings() -> None:
    notification = _make_notification("n1", plus_ones=_plus_ones("note"))
    modal = NotificationModal([notification])
    modal.action_cycle_plus_ones = MagicMock()  # type: ignore[method-assign]

    event = _KeyEvent("plus", "+")
    modal.on_key(event)

    modal.action_cycle_plus_ones.assert_called_once_with()
    assert event.prevented is True
    assert event.stopped is True


def test_selection_change_resets_plus_one_pane() -> None:
    notification = _make_notification("n1", plus_ones=_plus_ones("note"))
    modal = NotificationModal([notification])
    modal._plus_one_cursor = 0
    modal._display_file = MagicMock()  # type: ignore[method-assign]
    modal._update_hint_footer = MagicMock()  # type: ignore[method-assign]
    event = SimpleNamespace(option=SimpleNamespace(id="0"))

    modal.on_option_list_option_highlighted(event)  # type: ignore[arg-type]

    assert modal._plus_one_cursor is None
    modal._display_file.assert_called_once_with(notification)


def test_tab_change_resets_plus_one_pane() -> None:
    notification = _make_notification("n1", plus_ones=_plus_ones("note"))
    modal = NotificationModal([notification])
    modal._plus_one_cursor = 0

    modal._clear_tab_scoped_state()

    assert modal._plus_one_cursor is None


def test_display_file_dispatches_plus_one_pane_ahead_of_report() -> None:
    notification = Notification(
        id="report-1",
        timestamp="2026-07-29T10:14:17-04:00",
        sender="ci_watch",
        notes=["CI failure"],
        action="ViewReport",
        action_data={"report": "{}"},
        plus_ones=_plus_ones("newest"),
    )
    modal = NotificationModal([notification])
    modal._plus_one_cursor = 0
    title = MagicMock()
    content = MagicMock()

    def query_one(selector: str, *_args: object, **_kwargs: object) -> object:
        if selector == "#notification-file-title":
            return title
        if selector == "#notification-file-content":
            return content
        raise LookupError(selector)

    modal.query_one = MagicMock(side_effect=query_one)  # type: ignore[method-assign]
    modal._set_image_preview_mode = MagicMock()  # type: ignore[method-assign]
    modal._reset_file_scroll = MagicMock()  # type: ignore[method-assign]
    modal._render_report_pane = MagicMock(  # type: ignore[method-assign]
        side_effect=AssertionError("report pane must not render in +1 mode")
    )

    modal._display_file(notification)

    title.update.assert_called_once()
    assert "ci_watch · +1" in title.update.call_args.args[0]
    modal._render_report_pane.assert_not_called()
    modal._reset_file_scroll.assert_called_once_with()


def test_footer_hint_mentions_plus_one_key() -> None:
    assert "+: +1" in DEFAULT_HINT_TEXT
