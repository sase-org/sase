"""Tests for the full-screen notification report modal."""

from __future__ import annotations

from unittest.mock import MagicMock

from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.report_modal import ReportModal
from sase.notifications import NotificationReport


def _report(*, path: str | None = "/tmp/releases.report.json") -> NotificationReport:
    return NotificationReport(
        document={
            "title": "Release report",
            "blocks": [
                {
                    "kind": "bullets",
                    "items": [
                        {
                            "text": f"release row {index}",
                            "tone": "ok" if index % 2 == 0 else "warn",
                        }
                        for index in range(80)
                    ],
                }
            ],
        },
        source="live" if path else "snapshot",
        title="Release report",
        path=path,
        updated_at="2026-07-29T10:14:17-04:00",
        error=None,
    )


class _ReportModalTestApp(App[None]):
    def __init__(self, report: NotificationReport) -> None:
        super().__init__()
        self.report = report

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(ReportModal(self.report))


async def test_report_modal_renders_scrolls_and_closes() -> None:
    app = _ReportModalTestApp(_report())

    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        modal = app.screen_stack[-1]
        assert isinstance(modal, ReportModal)
        content = modal.query_one("#report-content", Static)
        scroll = modal.query_one("#report-scroll")
        assert "release row 0" in str(content.render())

        await pilot.press("ctrl+d")
        await pilot.pause()
        assert scroll.scroll_y > 0

        await pilot.press("g")
        await pilot.pause()
        assert scroll.scroll_y == 0

        await pilot.press("G")
        await pilot.pause()
        assert scroll.scroll_y > 0

        await pilot.press("q")
        await pilot.pause()
        assert not isinstance(app.screen_stack[-1], ReportModal)


def test_copy_path_uses_system_clipboard(monkeypatch: object) -> None:
    report = _report()
    modal = ReportModal(report)
    modal.notify = MagicMock()  # type: ignore[method-assign]
    copy = MagicMock(return_value=True)
    monkeypatch.setattr(  # type: ignore[attr-defined]
        "sase.ace.tui.modals.report_modal.copy_to_system_clipboard",
        copy,
    )

    modal.action_copy_path()

    copy.assert_called_once_with(report.path)
    modal.notify.assert_called_once_with(f"Copied: {report.path}")


def test_copy_path_warns_for_snapshot() -> None:
    modal = ReportModal(_report(path=None))
    modal.notify = MagicMock()  # type: ignore[method-assign]

    modal.action_copy_path()

    modal.notify.assert_called_once_with(
        "Snapshot reports do not have a file path",
        severity="warning",
    )
