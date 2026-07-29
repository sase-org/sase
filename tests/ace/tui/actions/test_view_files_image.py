"""Tests for image-aware routing of the ``v`` view-file hint flow."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.hints._files import FileViewingMixin
from sase.ace.tui.actions.hints._processing import InputProcessingMixin
from sase.ace.tui.graphics import ArtifactFileViewerResult, ArtifactFileViewSpec
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.tools.report import SlowToolCallReportSpec
from sase.ace.tui.widgets import HintInputBar
from sase.ace.tui.widgets.prompt_panel._agent_display_state import (
    AgentHintRender,
    CommitViewSpec,
)


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, *_args) -> None:
        return None


class _ViewApp(InputProcessingMixin, FileViewingMixin):
    """Minimal app combining the hint view mixins for routing tests."""

    def __init__(self, hint_mappings: dict[int, str]) -> None:
        self._hint_mappings = hint_mappings
        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        self._hint_changespec_name = "cs"
        self.notify = MagicMock()
        self.app = SimpleNamespace(push_screen=MagicMock())
        self.suspend_recorder = _SuspendRecorder()

    def suspend(self):
        return self.suspend_recorder


class _PendingHintContainer:
    is_attached = True

    def __init__(self) -> None:
        self.mounted: list[object] = []

    def mount(self, widget: object) -> None:
        self.mounted.append(widget)


class _PendingAgentDetail:
    def __init__(self) -> None:
        self.update_calls = 0

    def update_display_with_hints(self, _agent: object) -> AgentHintRender:
        self.update_calls += 1
        return AgentHintRender(
            file_hints={},
            tool_call_reports={},
            header_enrichment_pending=True,
        )


class _ReadyFamilyAgentDetail:
    def __init__(self) -> None:
        self.update_calls = 0

    def update_display_with_hints(self, _agent: object) -> AgentHintRender:
        self.update_calls += 1
        return AgentHintRender(
            file_hints={1: "/tmp/family-report.txt"},
            tool_call_reports={},
        )


class _EmptyAgentDetail:
    def __init__(self) -> None:
        self.update_calls = 0

    def update_display_with_hints(self, _agent: object) -> AgentHintRender:
        self.update_calls += 1
        return AgentHintRender(file_hints={}, tool_call_reports={})


class _PendingAgentViewApp(FileViewingMixin):
    def __init__(self) -> None:
        self.agent = SimpleNamespace(
            cl_name="pending-agent",
            identity=("pending-agent",),
            is_family_container_row=False,
        )
        self.detail = _PendingAgentDetail()
        self.container = _PendingHintContainer()
        self.current_tab = "agents"
        self._hint_mode_active = False
        self._hint_mode_hints_for = None
        self._hint_mappings = {}
        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        self.notify = MagicMock()
        self._refresh_agents_display = MagicMock()

    def _refocus_existing_hint_bar(self) -> bool:
        return False

    def _get_selected_agent(self) -> object:
        return self.agent

    def _remove_hint_input_bar(self) -> None:
        self._cancel_agent_hint_render_tasks()
        self._hint_mode_active = False
        self.container.mounted.clear()
        self._refresh_agents_display()

    def query_one(self, selector: str, _type: object = None) -> object:
        del _type
        if selector == "#agent-detail-panel":
            return self.detail
        if selector == "#agent-detail-container":
            return self.container
        raise AssertionError(selector)


def _make_app(*paths: str) -> _ViewApp:
    return _ViewApp({i + 1: path for i, path in enumerate(paths)})


@pytest.mark.asyncio
async def test_cold_agent_hint_render_keeps_view_mode_open_for_enrichment() -> None:
    app = _PendingAgentViewApp()

    app._view_agent_files()

    assert len(app.container.mounted) == 1
    assert app.detail.update_calls == 0
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    app.notify.assert_not_called()
    app._refresh_agents_display.assert_not_called()
    assert app._hint_mode_active
    assert app._hint_changespec_name == "pending-agent"
    assert len(app.container.mounted) == 1
    assert isinstance(app.container.mounted[0], HintInputBar)


@pytest.mark.asyncio
async def test_family_with_displayed_artifact_mounts_view_hint_input() -> None:
    app = _PendingAgentViewApp()
    app.agent = SimpleNamespace(
        cl_name="family",
        identity=("family",),
        is_family_container_row=True,
    )
    app.detail = _ReadyFamilyAgentDetail()

    app._view_agent_files()

    assert len(app.container.mounted) == 1
    assert app.detail.update_calls == 0
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    app.notify.assert_not_called()
    app._refresh_agents_display.assert_not_called()
    assert app._hint_mappings == {1: "/tmp/family-report.txt"}
    assert len(app.container.mounted) == 1
    assert isinstance(app.container.mounted[0], HintInputBar)


@pytest.mark.asyncio
async def test_ordinary_agent_empty_hint_render_keeps_warning_behavior() -> None:
    app = _PendingAgentViewApp()
    app.detail = _EmptyAgentDetail()

    app._view_agent_files()

    assert len(app.container.mounted) == 1
    assert app.detail.update_calls == 0
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    app.notify.assert_called_once_with(
        "No files or commits found in agent details",
        severity="warning",
    )
    app._refresh_agents_display.assert_called_once_with()
    assert not app._hint_mode_active
    assert app.container.mounted == []


class _ImmediateSubmitAgentViewApp(InputProcessingMixin, FileViewingMixin):
    def __init__(self) -> None:
        self.agent = SimpleNamespace(
            cl_name="immediate-submit",
            identity=("immediate-submit",),
            is_family_container_row=False,
        )
        self.detail = _ReadyFamilyAgentDetail()
        self.container = _PendingHintContainer()
        self.current_tab = "agents"
        self._hint_mode_active = False
        self._hint_mode_hints_for = None
        self._accept_mode_active = False
        self._rewind_mode_active = False
        self._hint_mappings = {}
        self._hint_tool_call_reports = {}
        self._hint_commit_views = {}
        self._hint_changespec_name = ""
        self.notify = MagicMock()
        self._refresh_agents_display = MagicMock()
        self._view_files_with_pager = MagicMock()
        self._workers: list[asyncio.Task[object]] = []

    def _get_selected_agent(self) -> object:
        return self.agent

    def _refocus_existing_hint_bar(self) -> bool:
        return False

    def query_one(self, selector: str, _type: object = None) -> object:
        del _type
        if selector == "#agent-detail-panel":
            return self.detail
        if selector == "#agent-detail-container":
            return self.container
        raise AssertionError(selector)

    def _remove_hint_input_bar(self, *, refresh: bool = True) -> None:
        del refresh
        self._cancel_agent_hint_render_tasks()
        self._hint_mode_active = False
        self.container.mounted.clear()

    def run_worker(self, work: object, **_kwargs: object) -> asyncio.Task[object]:
        task = asyncio.create_task(work)  # type: ignore[arg-type]
        self._workers.append(task)
        return task


@pytest.mark.asyncio
async def test_immediate_agent_hint_submission_waits_for_rendered_mapping() -> None:
    app = _ImmediateSubmitAgentViewApp()

    app._view_agent_files()
    assert app.detail.update_calls == 0
    assert app._hint_mappings == {}

    app.on_hint_input_bar_submitted(HintInputBar.Submitted("1", "view"))

    for _ in range(8):
        await asyncio.sleep(0)

    app._view_files_with_pager.assert_called_once_with(["/tmp/family-report.txt"])
    app.notify.assert_not_called()


def _commit_spec(
    *,
    sha: str = "abcdef1234567890",
    diff_path: str | None = None,
) -> CommitViewSpec:
    return CommitViewSpec(
        short_sha=sha[:12],
        sha=sha,
        repo_name="sase",
        cwd="/workspace/sase",
        subject="feat: add commit viewer",
        message="feat: add commit viewer\n\nBody line",
        diff_path=diff_path,
        is_primary=True,
    )


def _report_spec(
    report_path: str,
    *,
    status: str = "failure",
) -> SlowToolCallReportSpec:
    response_summary = (
        {"stdout_preview": "succeeded"}
        if status == "success"
        else {"stderr_preview": "failed"}
    )
    return SlowToolCallReportSpec(
        entry=ToolCallEntry(
            recorded_at="2026-07-07T14:35:02+00:00",
            runtime="codex",
            event="ToolUse",
            status=status,
            tool_name="Bash",
            tool_use_id="call_1",
            duration_ms=30_000,
            tool_input_summary={"command": "just test"},
            tool_response_summary=response_summary,
            source_path="/artifacts/tool_calls.jsonl",
            line_number=4,
        ),
        source_label=None,
        agent_name="agent--code",
        report_path=report_path,
    )


def test_view_submission_schedules_untracked_worker() -> None:
    app = _make_app("notes.md")
    app._remove_hint_input_bar = MagicMock()  # type: ignore[method-assign]
    scheduled: list[object] = []
    app.run_worker = MagicMock(  # type: ignore[attr-defined]
        side_effect=lambda work, **_kwargs: scheduled.append(work)
    )

    app.on_hint_input_bar_submitted(HintInputBar.Submitted("1", "view"))

    app._remove_hint_input_bar.assert_called_once_with()
    app.run_worker.assert_called_once()  # type: ignore[attr-defined]
    assert len(scheduled) == 1
    scheduled[0].close()  # type: ignore[attr-defined]


async def test_text_only_selection_uses_pager(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    await app._process_view_input("1")

    app._view_files_with_pager.assert_called_once_with([str(notes)])
    viewer.assert_not_called()


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
    await asyncio.sleep(0.05)

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


async def test_commit_hint_opens_commit_view_modal() -> None:
    app = _make_app()
    spec = _commit_spec()
    app._hint_commit_views = {1: spec}

    await app._process_view_input("1")

    app.app.push_screen.assert_called_once()
    modal = app.app.push_screen.call_args.args[0]
    assert isinstance(modal, CommitViewModal)
    assert modal._commit_specs == (spec,)


async def test_multiple_commit_hints_open_one_navigable_commit_view_modal() -> None:
    app = _make_app()
    first = _commit_spec(sha="111111111111111111111111")
    second = _commit_spec(sha="222222222222222222222222")
    app._hint_commit_views = {1: first, 2: second}

    await app._process_view_input("2 1")

    app.app.push_screen.assert_called_once()
    modal = app.app.push_screen.call_args.args[0]
    assert isinstance(modal, CommitViewModal)
    assert modal._commit_specs == (second, first)
    app.notify.assert_not_called()


async def test_commit_hint_copy_suffix_copies_short_sha(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) is None or True,
    )
    app = _make_app()
    app._hint_commit_views = {1: _commit_spec(sha="abcdef1234567890")}

    await app._process_view_input("1%")
    await asyncio.sleep(0.05)

    assert copied == ["abcdef123456"]
    app.notify.assert_called_once_with(
        "Copied 1 commit SHA(s)",
        severity="information",
    )
    app.app.push_screen.assert_not_called()


async def test_multiple_commit_hint_copy_suffix_copies_all_short_shas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(
        "sase.ace.tui.actions.clipboard._delivery.copy_to_system_clipboard",
        lambda content: copied.append(content) is None or True,
    )
    app = _make_app()
    app._hint_commit_views = {
        1: _commit_spec(sha="111111111111111111111111"),
        2: _commit_spec(sha="222222222222222222222222"),
    }

    await app._process_view_input("1 2%")
    await asyncio.sleep(0.05)

    assert copied == ["111111111111 222222222222"]
    app.notify.assert_called_once_with(
        "Copied 2 commit SHA(s)",
        severity="information",
    )
    app.app.push_screen.assert_not_called()


async def test_commit_hint_editor_suffix_opens_raw_diff_path(tmp_path: Path) -> None:
    diff_path = tmp_path / "commit.diff"
    app = _make_app()
    app._hint_commit_views = {1: _commit_spec(diff_path=str(diff_path))}
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1@")

    result = app._open_files_in_editor.call_args.args[0]
    assert result.files == [str(diff_path)]
    assert result.open_in_editor is True
    app.app.push_screen.assert_not_called()


async def test_multiple_commit_hint_editor_suffix_opens_raw_diff_paths(
    tmp_path: Path,
) -> None:
    first_diff = tmp_path / "first.diff"
    third_diff = tmp_path / "third.diff"
    app = _make_app()
    app._hint_commit_views = {
        1: _commit_spec(sha="111111111111111111111111", diff_path=str(first_diff)),
        2: _commit_spec(sha="222222222222222222222222"),
        3: _commit_spec(sha="333333333333333333333333", diff_path=str(third_diff)),
    }
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    await app._process_view_input("1 2 3@")

    result = app._open_files_in_editor.call_args.args[0]
    assert result.files == [str(first_diff), str(third_diff)]
    assert result.open_in_editor is True
    app.notify.assert_called_once_with(
        "No raw diff path for commit(s): 222222222222",
        severity="warning",
    )
    app.app.push_screen.assert_not_called()


async def test_image_only_selection_uses_artifact_file_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactFileViewSpec]] = []

    def fake_viewer(specs) -> ArtifactFileViewerResult:
        calls.append(list(specs))
        assert app.suspend_recorder.entered is True
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    await app._process_view_input("1")

    assert calls == [[ArtifactFileViewSpec(str(image), kind="image")]]
    app._view_files_with_pager.assert_not_called()
    app.notify.assert_not_called()


async def test_video_only_selection_uses_artifact_file_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    app = _make_app(str(video))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactFileViewSpec]] = []

    def fake_viewer(specs) -> ArtifactFileViewerResult:
        calls.append(list(specs))
        assert app.suspend_recorder.entered is True
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    await app._process_view_input("1")

    assert calls == [[ArtifactFileViewSpec(str(video), kind="file")]]
    app._view_files_with_pager.assert_not_called()
    app.notify.assert_not_called()


async def test_mixed_selection_routes_all_files_in_order(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    notes = tmp_path / "notes.md"
    notes.write_text("# notes", encoding="utf-8")
    app = _make_app(str(image), str(notes))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactFileViewSpec]] = []

    def fake_viewer(specs) -> ArtifactFileViewerResult:
        calls.append(list(specs))
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    await app._process_view_input("1 2")

    assert calls == [
        [
            ArtifactFileViewSpec(str(image), kind="image"),
            ArtifactFileViewSpec(str(notes), kind="file"),
        ]
    ]
    app._view_files_with_pager.assert_not_called()


async def test_artifact_file_viewer_warning_is_surfaced(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))

    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_artifact_files",
        lambda _specs: ArtifactFileViewerResult(False, warning="kitten missing"),
    )

    await app._process_view_input("1")

    app.notify.assert_called_once_with("kitten missing", severity="warning")


async def test_editor_suffix_bypasses_artifact_file_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    await app._process_view_input("1@")

    app._open_files_in_editor.assert_called_once()
    result = app._open_files_in_editor.call_args.args[0]
    assert result.open_in_editor is True
    assert result.files == [str(image)]
    viewer.assert_not_called()


async def test_clipboard_suffix_bypasses_artifact_file_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._copy_files_to_clipboard = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    await app._process_view_input("1%")

    app._copy_files_to_clipboard.assert_called_once_with([str(image)])
    viewer.assert_not_called()
