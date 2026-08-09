"""Tests for generated tool-call reports in the view-file hint flow."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.tools.report import SlowToolCallReportSpec

from ._view_files_helpers import _make_app, _report_spec


async def test_tool_call_report_hint_is_materialized_for_pager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    report_path = str(tmp_path / ".sase" / "tool_call_reports" / "report.md")
    app = _make_app(report_path)
    app._hint_tool_call_reports = {
        report_path: _report_spec(report_path, status="success")
    }
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1")

    assert Path(report_path).is_file()
    assert "succeeded" in Path(report_path).read_text(encoding="utf-8")
    app._view_files_with_pager.assert_called_once_with([report_path])


async def test_tool_call_report_materialization_runs_off_event_loop_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = str(tmp_path / "report.md")
    app = _make_app(report_path)
    app._hint_tool_call_reports = {report_path: _report_spec(report_path)}
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    event_loop_thread = threading.get_ident()
    writer_threads: list[int] = []

    def write_report(_spec: SlowToolCallReportSpec) -> str:
        writer_threads.append(threading.get_ident())
        return report_path

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_tool_call_report",
        write_report,
    )

    await app._process_view_input("1")

    assert writer_threads
    assert all(thread_id != event_loop_thread for thread_id in writer_threads)
    app._view_files_with_pager.assert_called_once_with([report_path])


async def test_mixed_report_and_file_selection_preserves_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    report_path = str(tmp_path / ".sase" / "tool_call_reports" / "report.md")
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")
    app = _make_app(str(notes), report_path)
    app._hint_tool_call_reports = {report_path: _report_spec(report_path)}
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("2 1")

    app._view_files_with_pager.assert_called_once_with([report_path, str(notes)])


async def test_tool_call_report_hint_is_materialized_for_editor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    report_path = str(tmp_path / ".sase" / "tool_call_reports" / "report.md")
    app = _make_app(report_path)
    app._hint_tool_call_reports = {report_path: _report_spec(report_path)}
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1@")

    assert Path(report_path).is_file()
    result = app._open_files_in_editor.call_args.args[0]
    assert result.files == [report_path]
    assert result.open_in_editor is True


async def test_tool_call_report_hint_is_materialized_for_clipboard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    report_path = str(tmp_path / ".sase" / "tool_call_reports" / "report.md")
    app = _make_app(report_path)
    app._hint_tool_call_reports = {report_path: _report_spec(report_path)}
    app._copy_files_to_clipboard = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1%")

    assert Path(report_path).is_file()
    app._copy_files_to_clipboard.assert_called_once_with([report_path])


async def test_tool_call_report_materialization_failure_drops_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    report_path = str(tmp_path / ".sase" / "tool_call_reports" / "report.md")
    app = _make_app(report_path)
    app._hint_tool_call_reports = {report_path: _report_spec(report_path)}
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_tool_call_report",
        lambda _spec: None,
    )

    await app._process_view_input("1")

    app._view_files_with_pager.assert_not_called()
    app.notify.assert_any_call(
        f"Failed to build tool-call report: {report_path}",
        severity="error",
    )
