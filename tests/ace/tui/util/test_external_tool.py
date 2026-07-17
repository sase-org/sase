"""Tests for the watchdog-aware external-tool suspend helper."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.ace.tui.util.external_tool import suspend_for_external_tool
from sase.logs import tui_telemetry


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = 0
        self.exited = 0

    def __enter__(self) -> None:
        self.entered += 1

    def __exit__(self, *_args: object) -> bool:
        self.exited += 1
        return False


class _FakeWatchdog:
    def __init__(self) -> None:
        self.paused = 0
        self.resumed = 0

    def pause(self) -> None:
        self.paused += 1

    def resume(self) -> None:
        self.resumed += 1


class _FakeApp:
    def __init__(self, *, watchdog: _FakeWatchdog | None, signals_wired: bool) -> None:
        self.current_tab = "agents"
        self.current_idx = 3
        self._stall_watchdog = watchdog
        self._stall_watchdog_suspend_signals_wired = signals_wired
        self._suspend = _SuspendRecorder()

    def suspend(self) -> _SuspendRecorder:
        return self._suspend


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_helper_enters_suspend_and_records_wait(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_external_tools.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_EXTERNAL_TOOLS_JSONL", str(path))
    watchdog = _FakeWatchdog()
    app = _FakeApp(watchdog=watchdog, signals_wired=False)
    ran_inside_suspend = False

    with suspend_for_external_tool(
        app,
        action="edit_spec",
        tool_kind="editor",
        command="/usr/bin/nvim",
        path_count=2,
    ):
        ran_inside_suspend = app._suspend.entered == 1
        assert app._suspend.exited == 0

    assert ran_inside_suspend
    assert app._suspend.exited == 1
    # No global signal hookup → helper pauses/resumes the watchdog itself.
    assert watchdog.paused == 1
    assert watchdog.resumed == 1

    records = _records(path)
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "external_tool_wait"
    assert record["action"] == "edit_spec"
    assert record["tool_kind"] == "editor"
    assert record["command"] == "nvim"  # basename only
    assert record["path_count"] == 2
    assert record["current_tab"] == "agents"
    assert record["current_idx"] == 3
    assert isinstance(record["elapsed_seconds"], float)
    assert record["elapsed_seconds"] >= 0.0


def test_helper_resumes_and_records_on_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_external_tools.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_EXTERNAL_TOOLS_JSONL", str(path))
    watchdog = _FakeWatchdog()
    app = _FakeApp(watchdog=watchdog, signals_wired=False)

    with pytest.raises(RuntimeError, match="boom"):
        with suspend_for_external_tool(
            app,
            action="open_artifact_file",
            tool_kind="artifact_file_viewer",
            path_count=1,
        ):
            raise RuntimeError("boom")

    # The watchdog is resumed and the wait is still recorded on the error path.
    assert watchdog.paused == 1
    assert watchdog.resumed == 1
    records = _records(path)
    assert len(records) == 1
    assert records[0]["action"] == "open_artifact_file"
    assert "command" not in records[0]


def test_helper_skips_manual_pause_when_signals_wired(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_external_tools.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_EXTERNAL_TOOLS_JSONL", str(path))
    watchdog = _FakeWatchdog()
    app = _FakeApp(watchdog=watchdog, signals_wired=True)

    with suspend_for_external_tool(
        app,
        action="open_artifact_files",
        tool_kind="artifact_file_viewer",
        path_count=3,
    ):
        pass

    # Global signal hookup owns pause/resume; the helper must not double-pause.
    assert watchdog.paused == 0
    assert watchdog.resumed == 0
    assert app._suspend.entered == 1
    records = _records(path)
    assert len(records) == 1
    assert records[0]["path_count"] == 3


def test_helper_tolerates_missing_watchdog(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "tui_external_tools.jsonl"
    monkeypatch.setattr(tui_telemetry, "TUI_EXTERNAL_TOOLS_JSONL", str(path))
    app = _FakeApp(watchdog=None, signals_wired=False)

    with suspend_for_external_tool(
        app,
        action="edit_panel",
        tool_kind="editor",
        command="vi",
        path_count=1,
    ):
        pass

    assert app._suspend.entered == 1
    records = _records(path)
    assert len(records) == 1
