"""Tests for generated tool-call reports in the view-file hint flow."""

from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from unittest.mock import MagicMock

import pytest

from sase.core.glossary_facade import GlossaryCatalog, GlossaryEntry
from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.memory.legacy_glossary_read_report import GlossaryReadReportSpec
from sase.memory.memory_read_report import MemoryReadReportSpec
from sase.xprompt._glossary_catalog_projects import EditorGlossaryProject
from sase.xprompt.glossary_catalog import (
    EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION,
    EditorGlossaryCatalog,
    EditorGlossaryCatalogResult,
)

from ._view_files_helpers import (
    _glossary_spec,
    _make_app,
    _memory_spec,
    _report_spec,
)


class _Signature:
    def to_wire(self) -> dict[str, object]:
        return {}


def _assert_pager_document_paths(app: object, paths: list[str]) -> None:
    pager = app._view_files_with_pager_screen  # type: ignore[attr-defined]
    pager.assert_called_once()
    (document,) = pager.call_args.args
    assert [section.title for section in document.sections] == paths


def _catalog_result() -> EditorGlossaryCatalogResult:
    entries = (
        GlossaryEntry(
            index=0,
            term="Alpha",
            normalized_term="alpha",
            definition="Mentions Beta then Gamma.",
            configured_aliases=(),
            display_aliases=(),
            effective_aliases=("Alpha",),
            source=None,
        ),
        GlossaryEntry(
            index=1,
            term="Beta",
            normalized_term="beta",
            definition="Beta definition.",
            configured_aliases=(),
            display_aliases=(),
            effective_aliases=("Beta",),
            source=None,
        ),
        GlossaryEntry(
            index=2,
            term="Gamma",
            normalized_term="gamma",
            definition="Gamma definition.",
            configured_aliases=(),
            display_aliases=(),
            effective_aliases=("Gamma",),
            source=None,
        ),
    )
    project = EditorGlossaryProject(
        key="sase",
        name="sase",
        aliases=(),
        workspace_dir=Path("/tmp/sase"),
    )
    return EditorGlossaryCatalogResult(
        project=project,
        catalog=EditorGlossaryCatalog(
            schema_version=EDITOR_GLOSSARY_CATALOG_SCHEMA_VERSION,
            project=project,
            config_path=Path("/tmp/sase/sase/memory/glossary"),
            config_signature=_Signature(),  # type: ignore[arg-type]
            catalog=GlossaryCatalog(schema_version=1, entries=entries),
            compiled=None,  # type: ignore[arg-type]
        ),
    )


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
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1")

    assert Path(report_path).is_file()
    assert "succeeded" in Path(report_path).read_text(encoding="utf-8")
    _assert_pager_document_paths(app, [report_path])


async def test_tool_call_report_materialization_runs_off_event_loop_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = str(tmp_path / "report.md")
    app = _make_app(report_path)
    app._hint_tool_call_reports = {report_path: _report_spec(report_path)}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    event_loop_thread = threading.get_ident()
    writer_threads: list[int] = []

    def write_report(_spec: SlowToolCallReportSpec) -> str:
        writer_threads.append(threading.get_ident())
        Path(report_path).write_text("report", encoding="utf-8")
        return report_path

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_tool_call_report",
        write_report,
    )

    await app._process_view_input("1")

    assert writer_threads
    assert all(thread_id != event_loop_thread for thread_id in writer_threads)
    _assert_pager_document_paths(app, [report_path])


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
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("2 1")

    _assert_pager_document_paths(app, [report_path, str(notes)])


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
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_tool_call_report",
        lambda _spec: None,
    )

    await app._process_view_input("1")

    app._view_files_with_pager_screen.assert_not_called()
    app.notify.assert_any_call(
        f"Failed to build hint report: {report_path}",
        severity="error",
    )


async def test_glossary_hint_is_materialized_for_pager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.xprompt.glossary_catalog.editor_glossary_catalog_for_project",
        lambda _project: _catalog_result(),
    )
    report_path = str(tmp_path / ".sase" / "glossary_read_reports" / "report.md")
    app = _make_app(report_path)
    app._hint_glossary_reports = {report_path: _glossary_spec(report_path)}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1")

    assert Path(report_path).is_file()
    body = Path(report_path).read_text(encoding="utf-8")
    assert "sase memory read glossary:Alpha" in body
    assert "Mentions Beta then Gamma." in body
    _assert_pager_document_paths(app, [report_path])


async def test_glossary_report_materialization_runs_off_event_loop_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = str(tmp_path / "glossary-report.md")
    app = _make_app(report_path)
    app._hint_glossary_reports = {report_path: _glossary_spec(report_path)}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    event_loop_thread = threading.get_ident()
    writer_threads: list[int] = []

    def write_report(_spec: GlossaryReadReportSpec) -> str:
        writer_threads.append(threading.get_ident())
        Path(report_path).write_text("glossary report", encoding="utf-8")
        return report_path

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_glossary_read_report",
        write_report,
    )

    await app._process_view_input("1")

    assert writer_threads
    assert all(thread_id != event_loop_thread for thread_id in writer_threads)
    _assert_pager_document_paths(app, [report_path])


async def test_mixed_glossary_tool_call_and_file_selection_preserves_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.xprompt.glossary_catalog.editor_glossary_catalog_for_project",
        lambda _project: _catalog_result(),
    )
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")
    glossary_path = str(tmp_path / ".sase" / "glossary_read_reports" / "glossary.md")
    tool_path = str(tmp_path / ".sase" / "tool_call_reports" / "tool.md")
    app = _make_app(str(notes), glossary_path, tool_path)
    app._hint_glossary_reports = {glossary_path: _glossary_spec(glossary_path)}
    app._hint_tool_call_reports = {tool_path: _report_spec(tool_path)}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("3 1 2")

    _assert_pager_document_paths(app, [tool_path, str(notes), glossary_path])


async def test_memory_report_hint_is_materialized_for_pager(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = str(tmp_path / ".sase" / "memory_read_reports" / "memory.md")
    app = _make_app(report_path)
    app._hint_memory_reports = {report_path: _memory_spec(report_path)}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    def write_report(_spec: MemoryReadReportSpec) -> str:
        Path(report_path).parent.mkdir(parents=True, exist_ok=True)
        Path(report_path).write_text("memory report", encoding="utf-8")
        return report_path

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_memory_read_report",
        write_report,
    )

    await app._process_view_input("1")

    assert Path(report_path).read_text(encoding="utf-8") == "memory report"
    _assert_pager_document_paths(app, [report_path])


async def test_memory_report_materialization_runs_off_event_loop_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = str(tmp_path / "memory-report.md")
    app = _make_app(report_path)
    app._hint_memory_reports = {report_path: _memory_spec(report_path)}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    event_loop_thread = threading.get_ident()
    writer_threads: list[int] = []

    def write_report(_spec: MemoryReadReportSpec) -> str:
        writer_threads.append(threading.get_ident())
        Path(report_path).write_text("memory report", encoding="utf-8")
        return report_path

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_memory_read_report",
        write_report,
    )

    await app._process_view_input("1")

    assert writer_threads
    assert all(thread_id != event_loop_thread for thread_id in writer_threads)
    _assert_pager_document_paths(app, [report_path])


async def test_memory_report_hint_is_materialized_for_editor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = str(tmp_path / "memory-report.md")
    app = _make_app(report_path)
    app._hint_memory_reports = {report_path: _memory_spec(report_path)}
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_memory_read_report",
        lambda _spec: report_path,
    )

    await app._process_view_input("1@")

    result = app._open_files_in_editor.call_args.args[0]
    assert result.files == [report_path]
    assert result.open_in_editor is True


async def test_memory_report_hint_is_materialized_for_clipboard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = str(tmp_path / "memory-report.md")
    app = _make_app(report_path)
    app._hint_memory_reports = {report_path: _memory_spec(report_path)}
    app._copy_files_to_clipboard = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_memory_read_report",
        lambda _spec: report_path,
    )

    await app._process_view_input("1%")

    app._copy_files_to_clipboard.assert_called_once_with([report_path])


async def test_mixed_memory_glossary_tool_call_and_file_selection_preserves_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("notes", encoding="utf-8")
    memory_path = str(tmp_path / "memory.md")
    glossary_path = str(tmp_path / "glossary.md")
    tool_path = str(tmp_path / "tool.md")
    app = _make_app(str(notes), memory_path, glossary_path, tool_path)
    app._hint_memory_reports = {memory_path: _memory_spec(memory_path)}
    app._hint_glossary_reports = {glossary_path: _glossary_spec(glossary_path)}
    app._hint_tool_call_reports = {tool_path: _report_spec(tool_path)}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]

    def write_memory(_spec: MemoryReadReportSpec) -> str:
        Path(memory_path).write_text("memory", encoding="utf-8")
        return memory_path

    def write_glossary(_spec: GlossaryReadReportSpec) -> str:
        Path(glossary_path).write_text("glossary", encoding="utf-8")
        return glossary_path

    def write_tool(_spec: SlowToolCallReportSpec) -> str:
        Path(tool_path).write_text("tool", encoding="utf-8")
        return tool_path

    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_memory_read_report",
        write_memory,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_glossary_read_report",
        write_glossary,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_tool_call_report",
        write_tool,
    )

    await app._process_view_input("4 2 1 3")

    _assert_pager_document_paths(
        app, [tool_path, memory_path, str(notes), glossary_path]
    )


async def test_memory_report_materialization_failure_drops_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report_path = str(tmp_path / "memory-report.md")
    app = _make_app(report_path)
    app._hint_memory_reports = {report_path: _memory_spec(report_path)}
    app._view_files_with_pager_screen = MagicMock()  # type: ignore[method-assign]
    monkeypatch.setattr(
        "sase.ace.tui.actions.hints._processing.write_memory_read_report",
        lambda _spec: None,
    )

    await app._process_view_input("1")

    app._view_files_with_pager_screen.assert_not_called()
    app.notify.assert_any_call(
        f"Failed to build hint report: {report_path}",
        severity="error",
    )
