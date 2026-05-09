from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

from sase.ace.tui.graphics.viewer import (
    ArtifactViewSpec,
    artifact_tmux_pane_exists,
    close_artifact_tmux_pane,
    is_tmux_session,
    select_tmux_pane,
    view_artifact_file_in_tmux_pane,
    view_artifact_files_in_tmux_pane,
)


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


def test_tmux_pane_launch_invokes_multi_artifact_entrypoint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifacts = (
        ArtifactViewSpec(tmp_path / "first.png", "image"),
        ArtifactViewSpec(tmp_path / "second.md", "markdown"),
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

    assert artifact_tmux_pane_exists("%7") is True
    result = close_artifact_tmux_pane("%7")

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


def test_tmux_pane_close_refuses_current_pane(monkeypatch) -> None:
    kill = MagicMock()
    monkeypatch.setenv("TMUX_PANE", "%1")
    monkeypatch.setattr(
        "sase.ace.tui.graphics.viewer.shutil.which",
        lambda tool: f"/usr/bin/{tool}" if tool == "tmux" else None,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.viewer.subprocess.run", kill)

    result = close_artifact_tmux_pane("%1")

    assert result.ok is False
    assert result.warning == "Refusing to close the current tmux pane"
    kill.assert_not_called()
