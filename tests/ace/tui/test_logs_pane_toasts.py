"""Toast-history rendering tests for the Admin Center Logs tab."""

from __future__ import annotations

import json
from pathlib import Path

from rich.text import Text

from sase.ace.testing import AcePage
from sase.logs import toast_log
from sase.ace.tui.logs import log_sources
from sase.ace.tui.modals.logs_pane import _CYAN, _GOLD, _render_log_detail


def _toast_json(
    *,
    timestamp: str,
    session_id: str,
    session_started_at: str,
    pid: int,
    message: str,
    severity: str = "information",
    title: str = "",
) -> str:
    return json.dumps(
        {
            "timestamp": timestamp,
            "session_id": session_id,
            "session_started_at": session_started_at,
            "pid": pid,
            "severity": severity,
            "title": title,
            "message": message,
        }
    )


def _write_toast_records(records: list[str]) -> None:
    path = toast_log.tui_toasts_jsonl_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(records) + "\n", encoding="utf-8")


def _style_at(text: Text, needle: str) -> set[str]:
    pos = text.plain.index(needle)
    return {
        str(span.style)
        for span in text.spans
        if span.start <= pos < span.end and span.style is not None
    }


def test_render_toasts_groups_sessions_newest_first(log_dir: Path) -> None:
    current_session = toast_log.current_toast_session()
    _write_toast_records(
        [
            _toast_json(
                timestamp="2026-07-06T22:03:12Z",
                session_id="20260706T220100Z-98111",
                session_started_at="2026-07-06T22:01:00Z",
                pid=98111,
                message="Patch must be Ready to mail",
                severity="warning",
            ),
            _toast_json(
                timestamp="2026-07-06T22:15:33Z",
                session_id="20260706T220100Z-98111",
                session_started_at="2026-07-06T22:01:00Z",
                pid=98111,
                message="Saved query to slot 2",
            ),
            _toast_json(
                timestamp="2026-07-07T00:01:00Z",
                session_id="20260706T235500Z-900",
                session_started_at="2026-07-06T23:55:00Z",
                pid=900,
                message="First toast after midnight",
                severity="warning",
            ),
            _toast_json(
                timestamp="2026-07-07T09:12:10Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="Mailing my-change...",
            ),
            _toast_json(
                timestamp="2026-07-07T09:12:41Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="Refreshed",
            ),
            _toast_json(
                timestamp="2026-07-07T09:12:42Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="Refreshed",
            ),
            _toast_json(
                timestamp="2026-07-07T09:13:47Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="PR is not set",
                severity="warning",
            ),
            _toast_json(
                timestamp="2026-07-07T09:14:03Z",
                session_id=current_session.session_id,
                session_started_at=current_session.session_started_at,
                pid=current_session.pid,
                message="boom\ntrace line",
                severity="error",
                title="Workflow error",
            ),
        ]
    )
    source = next(s for s in log_sources() if s.id == "tui_toasts")

    text = _render_log_detail(source)
    plain = text.plain

    assert "TUI Toasts" in plain
    assert "8 toasts" in plain
    assert plain.index("This session") < plain.index("pid 900")
    assert plain.index("pid 900") < plain.index("pid 98111")
    assert plain.index("Workflow error") < plain.index("PR is not set")
    assert plain.index("PR is not set") < plain.index("Refreshed")
    assert "Refreshed  ×2" in plain
    assert plain.count("Refreshed") == 1
    assert "20:01:00" in plain
    assert "boom\n            trace line" in plain
    assert "✖" in plain
    assert "⚠" in plain
    assert "·" in plain
    assert f"pid {current_session.pid}" in plain

    assert f"bold {_GOLD}" in _style_at(text, "This session")
    assert "red" in _style_at(text, "boom")
    assert _GOLD in _style_at(text, "PR is not set")
    assert _CYAN in _style_at(text, "05:14:03")


def test_render_empty_toasts_source_shows_notification_history_copy(
    log_dir: Path,
) -> None:
    source = next(s for s in log_sources() if s.id == "tui_toasts")

    text = _render_log_detail(source).plain

    assert "No toasts yet" in text
    assert "notifications shown in the TUI will appear here" in text


async def test_ace_app_notify_records_toast_history(log_dir: Path) -> None:
    async with AcePage(query='"toast"') as page:
        session = toast_log.current_toast_session()

        page.app.notify("Info toast")
        page.app.notify("Warn toast", severity="warning")
        page.app.notify("Error toast", title="Failure", severity="error")

        assert toast_log.flush_toasts(timeout=2.0)

    records = [
        record
        for record in toast_log.read_recent_toasts()
        if record.message in {"Info toast", "Warn toast", "Error toast"}
    ]
    assert [record.message for record in records] == [
        "Info toast",
        "Warn toast",
        "Error toast",
    ]
    assert {record.session_id for record in records} == {session.session_id}
    assert records[0].severity == "information"
    assert records[1].severity == "warning"
    assert records[2].severity == "error"
    assert records[2].title == "Failure"
