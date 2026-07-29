"""Rendering tests for notification report previews and dispatch."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from sase.ace.tui.actions.agents._notification_handlers import handle_view_report
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.modals.notification_modal_report import NotificationReportMixin
from sase.ace.tui.modals.report_modal import ReportModal
from sase.notifications import Notification


class _ReportPane(NotificationReportMixin):
    def query_one(self, *_args: object, **_kwargs: object) -> object:
        raise LookupError


def _document(*, title: str = "Release report") -> dict[str, object]:
    return {
        "title": title,
        "blocks": [
            {
                "kind": "headline",
                "text": "2 merged today · 3 pending",
                "tone": "ok",
            },
            {
                "kind": "rows",
                "columns": ["REPOSITORY", "PR", "STATE"],
                "rows": [
                    {
                        "cells": ["sase-org/sase", "#312", "checks not green"],
                        "tone": "warn",
                    }
                ],
            },
        ],
    }


def _notification(
    *,
    action: str | None = "ViewReport",
    action_data: dict[str, str] | None = None,
    files: list[str] | None = None,
) -> Notification:
    return Notification(
        id="report-notification",
        timestamp="2026-07-29T10:14:17-04:00",
        sender="ci_watch",
        action=action,
        action_data=action_data or {},
        files=files or [],
    )


def _render_plain(renderable: object) -> str:
    console = Console(record=True, width=100, color_system=None)
    console.print(renderable)
    return console.export_text()


def test_non_report_notification_has_no_report_pane() -> None:
    assert (
        _ReportPane()._render_report_pane(
            _notification(action="JumpToAgent"),
        )
        is None
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("live", "live · updated 2m ago"),
        ("snapshot", "snapshot · captured 2m ago"),
    ],
)
def test_report_pane_renders_provenance_and_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    expected: str,
) -> None:
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_report.format_relative_time",
        lambda _timestamp: "2m ago",
    )
    action_data = {"report": json.dumps(_document())}
    if source == "live":
        path = tmp_path / "release.report.json"
        path.write_text(json.dumps(_document()), encoding="utf-8")
        action_data = {"report_path": str(path)}

    pane = _ReportPane()._render_report_pane(
        _notification(action_data=action_data),
    )

    assert pane is not None
    title, content = pane
    plain = _render_plain(content)
    assert title == "Release report"
    assert expected in plain
    assert "2 merged today · 3 pending" in plain
    assert "sase-org/sase" in plain


@pytest.mark.parametrize(
    ("action_data", "expected"),
    [
        ({}, "report source is missing"),
        ({"report_path": "relative.json"}, "report path must be absolute"),
        ({"report": "{not-json"}, "report document is not valid JSON"),
    ],
)
def test_report_pane_renders_loader_failures_without_raising(
    action_data: dict[str, str],
    expected: str,
) -> None:
    pane = _ReportPane()._render_report_pane(
        _notification(action_data=action_data),
    )

    assert pane is not None
    assert expected in _render_plain(pane[1])


def test_report_pane_lists_attachments_only_when_present() -> None:
    action_data = {"report": json.dumps(_document())}
    without_files = _ReportPane()._render_report_pane(
        _notification(action_data=action_data)
    )
    with_files = _ReportPane()._render_report_pane(
        _notification(
            action_data=action_data,
            files=["/tmp/audit.json", "/tmp/details.txt"],
        )
    )

    assert without_files is not None
    assert with_files is not None
    assert "attachments:" not in _render_plain(without_files[1])
    assert "attachments: audit.json, details.txt" in _render_plain(with_files[1])


def test_display_file_dispatches_report_before_empty_attachment_state() -> None:
    notification = _notification(
        action_data={"report": json.dumps(_document(title="Current releases"))}
    )
    modal = NotificationModal([notification])
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

    modal._display_file(notification)

    title.update.assert_called_once_with("📊 ci_watch · Current releases")
    assert "No files attached" not in _render_plain(content.update.call_args.args[0])
    modal._set_image_preview_mode.assert_called_once_with(False)
    modal._reset_file_scroll.assert_called_once_with()


class _DispatchApp:
    def __init__(self) -> None:
        self.screens: list[object] = []
        self.notices: list[tuple[str, str]] = []

    def push_screen(self, screen: object) -> None:
        self.screens.append(screen)

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notices.append((message, severity))


def test_view_report_dispatch_pushes_report_modal() -> None:
    app = _DispatchApp()

    handled = handle_view_report(
        app,
        _notification(action_data={"report": json.dumps(_document())}),
    )

    assert handled is True
    assert len(app.screens) == 1
    assert isinstance(app.screens[0], ReportModal)
    assert app.notices == []


def test_view_report_dispatch_warns_once_for_failed_load() -> None:
    app = _DispatchApp()

    handled = handle_view_report(app, _notification())

    assert handled is False
    assert app.screens == []
    assert app.notices == [
        ("Unable to open report: report source is missing", "warning")
    ]
