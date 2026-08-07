from __future__ import annotations

import shlex
import signal
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.graphics.viewer import (
    ArtifactFileViewSpec,
    artifact_file_tmux_pane_exists,
    artifact_file_viewer_module_command,
    close_artifact_file_tmux_pane,
    decorate_artifact_file_tmux_panes,
    is_tmux_session,
    restore_artifact_file_tmux_pane_decoration,
    select_tmux_pane,
    toggle_artifact_file_tmux_pane_zoom,
    view_artifact_file_in_tmux_pane,
    view_artifact_files,
    view_artifact_files_in_tmux_pane,
)
from sase.ace.tui.graphics._viewer_loop import _PageLoopResult


def test_tmux_detection_returns_false_outside_tmux(monkeypatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    monkeypatch.delenv("TMUX_PANE", raising=False)

    assert is_tmux_session() is False


def test_tmux_pane_launch_warns_when_tmux_is_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.shutil.which", lambda _tool: None)

    result = view_artifact_file_in_tmux_pane(tmp_path / "artifact.png", kind="image")

    assert result.ok is False
    assert result.warning == "tmux executable not found"
    assert result.warnings[0].code == "missing_tmux"


def test_tmux_pane_launch_invokes_split_window_with_module_entrypoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifact, kind="image")

    assert result.ok is True
    assert result.pane_id == "%7"
    assert len(calls) == 1
    assert calls[0][:6] == [
        "tmux",
        "split-window",
        "-h",
        "-P",
        "-F",
        "#{pane_id}",
    ]
    assert shlex.split(calls[0][6]) == [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
        "--kind",
        "image",
        str(artifact),
    ]


def test_tmux_pane_launch_with_zoom_resizes_returned_pane(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["tmux", "split-window"]:
            return subprocess.CompletedProcess(cmd, 0, "%7\n", "")
        if cmd[:2] == ["tmux", "resize-pane"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifact, kind="image", zoom=True)

    assert result.ok is True
    assert result.pane_id == "%7"
    assert calls[0][:6] == [
        "tmux",
        "split-window",
        "-h",
        "-P",
        "-F",
        "#{pane_id}",
    ]
    assert calls[1] == ["tmux", "resize-pane", "-Z", "-t", "%7"]


def test_tmux_pane_launch_with_zoom_failure_preserves_live_pane(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["tmux", "split-window"]:
            return subprocess.CompletedProcess(cmd, 0, "%7\n", "")
        if cmd[:2] == ["tmux", "resize-pane"]:
            return subprocess.CompletedProcess(cmd, 1, "", "no pane")
        raise AssertionError(cmd)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifact, kind="image", zoom=True)

    assert result.ok is True
    assert result.pane_id == "%7"
    assert result.warning == "tmux resize-pane -Z failed with exit code 1: no pane"
    assert result.warnings[0].code == "tmux_zoom_failed"
    assert calls[1] == ["tmux", "resize-pane", "-Z", "-t", "%7"]


def test_tmux_pane_launch_passes_return_pane_env_when_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifact, kind="image")

    assert result.ok is True
    assert calls[0][:6] == [
        "tmux",
        "split-window",
        "-h",
        "-P",
        "-F",
        "#{pane_id}",
    ]
    assert calls[0][6:8] == ["-e", "SASE_ARTIFACT_RETURN_PANE_ID=%1"]
    assert shlex.split(calls[0][8]) == [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
        "--kind",
        "image",
        str(artifact),
    ]


def test_tmux_pane_launch_passes_notify_pid_env_when_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setenv("SASE_ARTIFACT_FILE_NOTIFY_PID", "12345")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifact, kind="image")

    assert result.ok is True
    assert calls[0][6:8] == ["-e", "SASE_ARTIFACT_FILE_NOTIFY_PID=12345"]
    assert shlex.split(calls[0][8]) == [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
        "--kind",
        "image",
        str(artifact),
    ]


def test_tmux_pane_launch_invokes_multi_artifact_entrypoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = (
        ArtifactFileViewSpec(tmp_path / "first.png", "image"),
        ArtifactFileViewSpec(tmp_path / "second.md", "markdown"),
    )
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "%7\n", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = view_artifact_file_in_tmux_pane(artifacts[0].path, kind=artifacts[0].kind)
    assert result.ok is True
    assert result.pane_id == "%7"

    calls.clear()
    result = view_artifact_files_in_tmux_pane(artifacts)

    assert result.ok is True
    assert result.pane_id == "%7"
    assert shlex.split(calls[0][6]) == [
        sys.executable,
        "-m",
        "sase.ace.tui.graphics.viewer",
        "--kind",
        "image",
        "--kind",
        "markdown",
        str(artifacts[0].path),
        str(artifacts[1].path),
    ]


def test_tmux_pane_helpers_check_and_kill_tracked_pane(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["tmux", "display-message"]:
            return subprocess.CompletedProcess(cmd, 0, "%7\n", "")
        if cmd[:2] == ["tmux", "kill-pane"]:
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    assert artifact_file_tmux_pane_exists("%7") is True
    result = close_artifact_file_tmux_pane("%7")

    assert result.ok is True
    assert calls == [
        ["tmux", "display-message", "-p", "-t", "%7", "#{pane_id}"],
        ["tmux", "kill-pane", "-t", "%7"],
    ]


def test_tmux_select_pane_helper_focuses_pane(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = select_tmux_pane("%7")

    assert result.ok is True
    assert calls == [["tmux", "select-pane", "-t", "%7"]]


def test_tmux_select_pane_helper_surfaces_failure(monkeypatch) -> None:
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, "", "no pane"),
    )

    result = select_tmux_pane("%7")

    assert result.ok is False
    assert result.warning == "tmux select-pane failed with exit code 1: no pane"
    assert result.warnings[0].code == "tmux_select_failed"


def test_tmux_zoom_helper_toggles_current_tmux_pane(monkeypatch) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = toggle_artifact_file_tmux_pane_zoom()

    assert result.ok is True
    assert calls == [["tmux", "resize-pane", "-Z", "-t", "%7"]]


def test_tmux_zoom_helper_uses_current_pane_without_tmux_pane_env(
    monkeypatch,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = toggle_artifact_file_tmux_pane_zoom()

    assert result.ok is True
    assert calls == [["tmux", "resize-pane", "-Z"]]


def test_tmux_zoom_helper_surfaces_failure(monkeypatch) -> None:
    monkeypatch.setenv("TMUX_PANE", "%7")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 1, "", "no pane"),
    )

    result = toggle_artifact_file_tmux_pane_zoom()

    assert result.ok is False
    assert result.warning == "tmux resize-pane -Z failed with exit code 1: no pane"
    assert result.warnings[0].code == "tmux_zoom_failed"


def test_tmux_artifact_decoration_snapshots_sets_and_restores(monkeypatch) -> None:
    calls: list[list[str]] = []
    option_values = {
        "pane-border-status": "off",
        "pane-border-format": "#{pane_index}",
        "pane-border-style": "default",
        "pane-active-border-style": "default",
    }
    title_values = {
        "%1": "origin title",
        "%7": "artifact title",
    }
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:3] == ["tmux", "show-options", "-wqv"]:
            return subprocess.CompletedProcess(
                cmd, 0, option_values[cmd[-1]] + "\n", ""
            )
        if cmd[:3] == ["tmux", "display-message", "-p"]:
            return subprocess.CompletedProcess(cmd, 0, title_values[cmd[4]] + "\n", "")
        if cmd[:2] in (["tmux", "select-pane"], ["tmux", "set-option"]):
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    result = decorate_artifact_file_tmux_panes("%7")

    assert result.ok is True
    assert result.warning is None
    assert result.state is not None
    assert result.state.target_pane_id == "%1"
    assert [(opt.name, opt.value) for opt in result.state.window_options] == [
        ("pane-border-status", "off"),
        ("pane-border-format", "#{pane_index}"),
        ("pane-border-style", "default"),
        ("pane-active-border-style", "default"),
    ]
    assert [(title.pane_id, title.title) for title in result.state.pane_titles] == [
        ("%1", "origin title"),
        ("%7", "artifact title"),
    ]
    assert ["tmux", "select-pane", "-t", "%1", "-T", "SASE TUI"] in calls
    assert ["tmux", "select-pane", "-t", "%7", "-T", "Artifact Viewer"] in calls
    assert [
        "tmux",
        "set-option",
        "-wq",
        "-t",
        "%1",
        "pane-border-status",
        "top",
    ] in calls
    assert any(
        call[:6] == ["tmux", "set-option", "-wq", "-t", "%1", "pane-border-format"]
        and "#{?pane_active" in call[-1]
        for call in calls
    )

    calls.clear()
    restore = restore_artifact_file_tmux_pane_decoration(result.state)

    assert restore.ok is True
    assert [
        "tmux",
        "set-option",
        "-wq",
        "-t",
        "%1",
        "pane-border-status",
        "off",
    ] in calls
    assert ["tmux", "select-pane", "-t", "%1", "-T", "origin title"] in calls
    assert ["tmux", "select-pane", "-t", "%7", "-T", "artifact title"] in calls


def test_tmux_artifact_decoration_failure_does_not_block_viewing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    calls: list[list[str]] = []
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ["tmux", "split-window"]:
            return subprocess.CompletedProcess(cmd, 0, "%7\n", "")
        if cmd[:3] == ["tmux", "show-options", "-wqv"]:
            return subprocess.CompletedProcess(cmd, 1, "", "old tmux")
        return subprocess.CompletedProcess(cmd, 0, "title\n", "")

    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", fake_run)

    launch = view_artifact_file_in_tmux_pane(artifact, kind="image")
    decoration = decorate_artifact_file_tmux_panes("%7")

    assert launch.ok is True
    assert launch.pane_id == "%7"
    assert decoration.ok is True
    assert decoration.state is not None
    assert decoration.warning is not None
    assert [warning.code for warning in decoration.warnings] == [
        "tmux_option_snapshot_failed",
        "tmux_option_snapshot_failed",
        "tmux_option_snapshot_failed",
        "tmux_option_snapshot_failed",
    ]


def test_artifact_file_viewer_notifies_parent_pid_on_exit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = tmp_path / "artifact.png"
    artifact.write_bytes(b"png")
    kill = MagicMock()
    monkeypatch.setenv("SASE_ARTIFACT_FILE_NOTIFY_PID", "4242")
    monkeypatch.setattr("sase.ace.tui.graphics._viewer_launch.os.kill", kill)
    monkeypatch.setattr(
        "sase.ace.tui.graphics._viewer_launch.run_artifact_sequence_loop",
        lambda *args, **kwargs: _PageLoopResult(),
    )

    result = view_artifact_files((ArtifactFileViewSpec(artifact, "image"),))

    assert result.ok is True
    kill.assert_called_once_with(4242, signal.SIGUSR1)


def test_tmux_pane_close_refuses_current_pane(monkeypatch) -> None:
    kill = MagicMock()
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", kill)

    result = close_artifact_file_tmux_pane("%1")

    assert result.ok is False
    assert result.warning == "Refusing to close the current tmux pane"
    kill.assert_not_called()


def test_tmux_pane_view_warns_instead_of_crashing_on_missing_path(
    monkeypatch,
) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )

    result = view_artifact_files_in_tmux_pane(
        (ArtifactFileViewSpec(None, "image"),)  # type: ignore[arg-type]
    )

    assert result.ok is False
    assert result.warnings[0].code == "missing_artifact_path"


def test_artifact_file_viewer_module_command_raises_value_error_on_missing_path() -> (
    None
):
    with pytest.raises(ValueError, match="requires a path"):
        artifact_file_viewer_module_command(
            (ArtifactFileViewSpec(None, "image"),)  # type: ignore[arg-type]
        )
