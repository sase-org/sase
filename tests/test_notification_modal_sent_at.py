"""Tests for the notification modal's sent-time detail line."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_sent_at import (
    NotificationSentAtMixin,
    _build_sent_at_text,
)
from tests._notification_modal_helpers import _make_notification


def _render_plain(renderable: object) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


@pytest.fixture(autouse=True)
def _stable_time_formatting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_absolute_time",
        lambda _timestamp, now=None: "today 13:18:42",
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_sent_at.format_relative_time",
        lambda _timestamp: "4m ago",
    )


class TestBuildSentAtText:
    def test_renders_absolute_and_relative(self) -> None:
        notification = _make_notification("n1")
        plain = _render_plain(_build_sent_at_text(notification))
        assert plain.strip() == "sent today 13:18:42 · 4m ago"

    def test_absolute_segment_is_bold_relative_segment_is_dim(self) -> None:
        notification = _make_notification("n1")
        text = _build_sent_at_text(notification)
        spans_by_text = {
            text.plain[start:end]: style for start, end, style in text.spans
        }
        assert spans_by_text.get("today 13:18:42") == "bold"
        assert spans_by_text.get("4m ago") == "dim"

    def test_renders_presented_origin_agent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sase.core.agent_identity_facade.present_agent_name",
            lambda _name: "claude_coder",
        )
        notification = _make_notification(
            "n1",
            action_data={"origin_agent": " bbugyi200.athena.claude_coder "},
        )

        text = _build_sent_at_text(notification)

        assert text.plain == ("sent today 13:18:42 · 4m ago · filed by @claude_coder")
        spans_by_text = {
            text.plain[start:end]: style for start, end, style in text.spans
        }
        assert spans_by_text.get("filed by ") == "dim"
        assert spans_by_text.get("@claude_coder") == "#87D7FF"

    def test_omits_blank_origin_agent(self) -> None:
        notification = _make_notification(
            "n1",
            action_data={"origin_agent": "   "},
        )

        assert _build_sent_at_text(notification).plain == (
            "sent today 13:18:42 · 4m ago"
        )

    def test_falls_back_to_raw_origin_when_presentation_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail_to_present(_name: str) -> str:
            raise RuntimeError("identity unavailable")

        monkeypatch.setattr(
            "sase.core.agent_identity_facade.present_agent_name",
            fail_to_present,
        )
        notification = _make_notification(
            "n1",
            action_data={"origin_agent": "remote.agent"},
        )

        assert _build_sent_at_text(notification).plain.endswith(
            " · filed by @remote.agent"
        )


class _SentAtHost(NotificationSentAtMixin):
    def __init__(self, label: Any) -> None:
        self._label = label

    def query_one(self, selector: str, *_args: object, **_kwargs: object) -> Any:
        if selector == "#notification-sent-at":
            return self._label
        raise LookupError(selector)


class TestUpdateSentAt:
    def test_none_clears_label_and_hides_it(self) -> None:
        label = MagicMock()
        host = _SentAtHost(label)

        host._update_sent_at(None)

        label.update.assert_called_once()
        assert label.update.call_args.args[0].plain == ""
        label.add_class.assert_called_once_with("hidden")
        label.remove_class.assert_not_called()

    def test_notification_sets_text_and_unhides(self) -> None:
        label = MagicMock()
        host = _SentAtHost(label)
        notification = _make_notification("n1")

        host._update_sent_at(notification)

        label.update.assert_called_once()
        assert label.update.call_args.args[0].plain == "sent today 13:18:42 · 4m ago"
        label.remove_class.assert_called_once_with("hidden")
        label.add_class.assert_not_called()

    def test_missing_widget_degrades_silently(self) -> None:
        class _NoLabelHost(NotificationSentAtMixin):
            def query_one(self, *_args: object, **_kwargs: object) -> Any:
                raise LookupError("no such widget")

        _NoLabelHost()._update_sent_at(_make_notification("n1"))  # should not raise

    def test_garbage_timestamp_still_renders_without_raising(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.undo()  # restore real formatters for this one test
        label = MagicMock()
        host = _SentAtHost(label)
        notification = _make_notification("n1", timestamp="not-a-real-timestamp")

        host._update_sent_at(notification)

        label.update.assert_called_once()
        rendered = label.update.call_args.args[0].plain
        assert "not-a-real-timestamp" in rendered


def _query_one_recorder(
    *,
    title: Any,
    content: Any,
    sent_at: Any,
    scroll: Any | None = None,
) -> Any:
    def query_one(selector: str, *_args: object, **_kwargs: object) -> Any:
        if selector == "#notification-file-title":
            return title
        if selector == "#notification-file-content":
            return content
        if selector == "#notification-sent-at":
            return sent_at
        if selector == "#notification-file-scroll" and scroll is not None:
            return scroll
        raise LookupError(selector)

    return query_one


class TestDisplayFileUpdatesSentAtLine:
    def test_no_files_attached(self) -> None:
        notification = _make_notification("n1")
        modal = NotificationModal([notification])
        title, content, sent_at = MagicMock(), MagicMock(), MagicMock()
        modal.query_one = MagicMock(  # type: ignore[method-assign]
            side_effect=_query_one_recorder(
                title=title, content=content, sent_at=sent_at
            )
        )

        modal._display_file(notification)

        sent_at.update.assert_called_once()
        assert sent_at.update.call_args.args[0].plain == "sent today 13:18:42 · 4m ago"
        sent_at.remove_class.assert_called_once_with("hidden")

    def test_text_attachment(self, tmp_path: Path) -> None:
        file_path = tmp_path / "notes.txt"
        file_path.write_text("hello world", encoding="utf-8")
        notification = _make_notification("n1")
        notification.files = [str(file_path)]
        modal = NotificationModal([notification])
        title, content, sent_at = MagicMock(), MagicMock(), MagicMock()
        scroll = MagicMock()
        modal.query_one = MagicMock(  # type: ignore[method-assign]
            side_effect=_query_one_recorder(
                title=title, content=content, sent_at=sent_at, scroll=scroll
            )
        )

        modal._display_file(notification)

        sent_at.update.assert_called_once()
        assert sent_at.update.call_args.args[0].plain == "sent today 13:18:42 · 4m ago"
        sent_at.remove_class.assert_called_once_with("hidden")

    def test_question_notification(self, tmp_path: Path) -> None:
        notification = _make_notification("n1", action="UserQuestion")
        notification.action_data = {"response_dir": str(tmp_path / "question")}
        modal = NotificationModal([notification])
        title, content, sent_at = MagicMock(), MagicMock(), MagicMock()
        modal.query_one = MagicMock(  # type: ignore[method-assign]
            side_effect=_query_one_recorder(
                title=title, content=content, sent_at=sent_at
            )
        )

        modal._display_file(notification)

        sent_at.update.assert_called_once()
        assert sent_at.update.call_args.args[0].plain == "sent today 13:18:42 · 4m ago"
        sent_at.remove_class.assert_called_once_with("hidden")

    def test_report_notification(self) -> None:
        document = {
            "title": "Release report",
            "blocks": [{"kind": "headline", "text": "2 merged today", "tone": "ok"}],
        }
        notification = _make_notification("n1", action="ViewReport")
        notification.action_data = {"report": json.dumps(document)}
        modal = NotificationModal([notification])
        title, content, sent_at = MagicMock(), MagicMock(), MagicMock()
        modal.query_one = MagicMock(  # type: ignore[method-assign]
            side_effect=_query_one_recorder(
                title=title, content=content, sent_at=sent_at
            )
        )

        modal._display_file(notification)

        sent_at.update.assert_called_once()
        assert sent_at.update.call_args.args[0].plain == "sent today 13:18:42 · 4m ago"
        sent_at.remove_class.assert_called_once_with("hidden")


class TestCyclingAttachmentsLeavesSentAtLineUnchanged:
    def test_next_file_changes_content_not_title_or_sent_line(
        self, tmp_path: Path
    ) -> None:
        first = tmp_path / "a.txt"
        first.write_text("a", encoding="utf-8")
        second = tmp_path / "b.txt"
        second.write_text("b", encoding="utf-8")
        notification = _make_notification("n1")
        notification.files = [str(first), str(second)]
        modal = NotificationModal([notification])
        modal._get_highlighted_notification = (  # type: ignore[method-assign]
            lambda: notification
        )
        title, content, sent_at = MagicMock(), MagicMock(), MagicMock()
        scroll = MagicMock()
        modal.query_one = MagicMock(  # type: ignore[method-assign]
            side_effect=_query_one_recorder(
                title=title, content=content, sent_at=sent_at, scroll=scroll
            )
        )

        modal.action_next_file()

        # The header title reflects the notification, not the current attachment,
        # so cycling files leaves it unchanged; the body composed into content
        # is what carries the per-file "b.txt" reference now.
        title_texts = {call.args[0] for call in title.update.call_args_list}
        assert len(title_texts) == 1
        content_texts = [
            _render_plain(call.args[0]) for call in content.update.call_args_list
        ]
        assert any("b.txt" in text for text in content_texts)
        sent_at_texts = {call.args[0].plain for call in sent_at.update.call_args_list}
        assert sent_at_texts == {"sent today 13:18:42 · 4m ago"}
