"""Async tmux pane launch: off-thread split, in-flight guard, timeouts."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.graphics import ArtifactFileViewerResult, TmuxPaneDecorationResult
from tests.ace.tui.artifact_file_viewer._helpers import (
    _patch_tmux_run,
    _patch_tmux_which,
)

from ._artifact_file_image_helpers import _ImageActionApp, _decoration_state


def _image_artifact(tmp_path: Path) -> SimpleNamespace:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    return SimpleNamespace(path=str(image), kind="image", label="Image")


def _select_and_open(app: _ImageActionApp, artifact: object) -> None:
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [artifact]
    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None
    callback(artifact)


def test_second_a_while_open_in_flight_toasts_and_does_nothing() -> None:
    app = _ImageActionApp(None)
    app._artifact_file_tmux_open_in_flight = True
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [SimpleNamespace(path="/tmp/a.png", kind="image", label="A")]

    app.action_open_artifact_files()

    app.notify.assert_called_once_with(
        "Artifact viewer is already opening",
        severity="warning",
    )
    assert app.pushed == []


def test_tmux_open_leaves_os_environ_unchanged(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = _image_artifact(tmp_path)
    app = _ImageActionApp(artifact.path)
    monkeypatch.delenv("SASE_ARTIFACT_FILE_NOTIFY_PID", raising=False)
    before = dict(os.environ)
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file_in_tmux_pane",
        lambda _artifact, **_kwargs: ArtifactFileViewerResult(True, pane_id="%7"),
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.decorate_artifact_file_tmux_panes",
        lambda _pane_id, **_kwargs: TmuxPaneDecorationResult(
            True, state=_decoration_state()
        ),
    )

    def fail_exists(_pane_id: str) -> bool:
        raise AssertionError("artifact_file_tmux_pane_exists should be skipped")

    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        fail_exists,
    )

    _select_and_open(app, artifact)

    assert dict(os.environ) == before
    assert app._artifact_file_tmux_pane_id == "%7"
    assert app._artifact_file_tmux_decoration_state == _decoration_state()
    assert "-artifact-file-viewer-active" in app.content.classes
    assert app._artifact_file_tmux_open_in_flight is False


def test_tmux_timeout_surfaces_as_warning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = _image_artifact(tmp_path)
    app = _ImageActionApp(artifact.path)
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setenv("TMUX_PANE", "%1")
    _patch_tmux_which(monkeypatch)

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, timeout=2)

    _patch_tmux_run(monkeypatch, fake_run)

    _select_and_open(app, artifact)

    app.notify.assert_any_call(
        "tmux split-window timed out after 2s",
        severity="warning",
    )
    assert app._artifact_file_tmux_pane_id is None
    assert app._artifact_file_tmux_open_in_flight is False


@pytest.mark.asyncio
async def test_tmux_subprocess_does_not_run_on_ui_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    artifact = _image_artifact(tmp_path)
    app = _ImageActionApp(artifact.path)
    main = threading.current_thread()
    threads: list[threading.Thread] = []
    monkeypatch.setenv("TMUX", "/tmp/tmux")
    monkeypatch.setenv("TMUX_PANE", "%1")
    _patch_tmux_which(monkeypatch)

    def fake_run(cmd, **kwargs):
        threads.append(threading.current_thread())
        if cmd[:2] == ["tmux", "split-window"]:
            return subprocess.CompletedProcess(cmd, 0, "%7\n", "")
        if cmd[:3] == ["tmux", "show-options", "-wqv"]:
            return subprocess.CompletedProcess(cmd, 0, "off\n", "")
        if cmd[:3] == ["tmux", "display-message", "-p"]:
            return subprocess.CompletedProcess(cmd, 0, "title\n", "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    _patch_tmux_run(monkeypatch, fake_run)

    _select_and_open(app, artifact)
    tasks = getattr(app, "_pump_free_async_tasks", set())
    assert tasks
    await asyncio.gather(*tuple(tasks))

    assert threads
    assert all(thread is not main for thread in threads)
    assert app._artifact_file_tmux_pane_id == "%7"
    assert app._artifact_file_tmux_open_in_flight is False
    assert "-artifact-file-viewer-active" in app.content.classes
