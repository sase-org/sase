from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.graphics import ArtifactFileViewerResult

from ._artifact_file_image_helpers import (
    _ImageActionApp,
    _ImageQuitApp,
    _decoration_state,
)


def test_agents_open_artifact_files_action_closes_live_tracked_tmux_pane(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_file_tmux_pane_id = "%7"
    app._artifact_file_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-file-viewer-active")
    exists = MagicMock(return_value=True)
    close = MagicMock(return_value=ArtifactFileViewerResult(True))
    restore = MagicMock(return_value=ArtifactFileViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr("sase.ace.tui.graphics.artifact_file_tmux_pane_exists", exists)
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_file_tmux_pane", close)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_file_tmux_pane_decoration",
        restore,
    )

    app.action_open_artifact_files()

    exists.assert_called_once_with("%7")
    restore.assert_called_once_with(_decoration_state())
    close.assert_called_once_with("%7")
    assert app._artifact_file_tmux_pane_id is None
    assert app._artifact_file_tmux_decoration_state is None
    assert "-artifact-file-viewer-active" not in app.content.classes
    assert app.pushed == []
    app.notify.assert_not_called()


def test_agents_open_artifact_files_action_clears_stale_tmux_pane_and_opens_modal(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_file_tmux_pane_id = "%7"
    app._artifact_file_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-file-viewer-active")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [SimpleNamespace(path="/tmp/chat.md", kind="chat", label="Chat")]
    close = MagicMock()
    restore = MagicMock(return_value=ArtifactFileViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: False,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_file_tmux_pane", close)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_file_tmux_pane_decoration",
        restore,
    )

    app.action_open_artifact_files()

    close.assert_not_called()
    restore.assert_called_once_with(_decoration_state())
    assert app._artifact_file_tmux_pane_id is None
    assert app._artifact_file_tmux_decoration_state is None
    assert "-artifact-file-viewer-active" not in app.content.classes
    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert modal.__class__.__name__ == "ArtifactFileSelectionModal"
    assert callback is not None


def test_agents_focus_tracked_artifact_file_tmux_pane_selects_live_pane(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_file_tmux_pane_id = "%7"
    select = MagicMock(return_value=ArtifactFileViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.select_tmux_pane", select)

    assert app._focus_tracked_artifact_file_tmux_pane() is True

    select.assert_called_once_with("%7")
    app.notify.assert_not_called()


def test_agents_focus_tracked_artifact_file_tmux_pane_surfaces_select_warning(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_file_tmux_pane_id = "%7"
    app.content.add_class("-artifact-file-viewer-active")
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.select_tmux_pane",
        lambda _pane_id: ArtifactFileViewerResult(False, warning="select failed"),
    )

    assert app._focus_tracked_artifact_file_tmux_pane() is True

    app.notify.assert_called_once_with("select failed", severity="warning")
    assert "-artifact-file-viewer-active" in app.content.classes


def test_agents_focus_tracked_artifact_file_tmux_pane_clears_stale_pane(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_file_tmux_pane_id = "%7"
    app._artifact_file_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-file-viewer-active")
    select = MagicMock()
    restore = MagicMock(return_value=ArtifactFileViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: False,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.select_tmux_pane", select)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_file_tmux_pane_decoration",
        restore,
    )

    assert app._focus_tracked_artifact_file_tmux_pane() is False

    select.assert_not_called()
    restore.assert_called_once_with(_decoration_state())
    assert app._artifact_file_tmux_pane_id is None
    assert app._artifact_file_tmux_decoration_state is None
    assert "-artifact-file-viewer-active" not in app.content.classes


@pytest.mark.asyncio
async def test_action_quit_closes_live_artifact_pane_before_quit_flow(
    monkeypatch,
) -> None:
    app = _ImageQuitApp()
    app._artifact_file_tmux_pane_id = "%7"
    app._artifact_file_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-file-viewer-active")
    close = MagicMock(return_value=ArtifactFileViewerResult(True))
    restore = MagicMock(return_value=ArtifactFileViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_file_tmux_pane", close)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_file_tmux_pane_decoration",
        restore,
    )

    await app.action_quit()

    restore.assert_called_once_with(_decoration_state())
    close.assert_called_once_with("%7")
    assert app._artifact_file_tmux_pane_id is None
    assert app._artifact_file_tmux_decoration_state is None
    assert "-artifact-file-viewer-active" not in app.content.classes
    assert app.count_running_tasks_calls == 0
    assert app.did_quit is False


@pytest.mark.asyncio
async def test_action_quit_ignores_stale_artifact_pane_and_continues(
    monkeypatch,
) -> None:
    app = _ImageQuitApp()
    app._artifact_file_tmux_pane_id = "%7"
    app._artifact_file_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-file-viewer-active")
    close = MagicMock()
    restore = MagicMock(return_value=ArtifactFileViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: False,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_file_tmux_pane", close)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_file_tmux_pane_decoration",
        restore,
    )

    await app.action_quit()

    close.assert_not_called()
    restore.assert_called_once_with(_decoration_state())
    assert app._artifact_file_tmux_pane_id is None
    assert app._artifact_file_tmux_decoration_state is None
    assert "-artifact-file-viewer-active" not in app.content.classes
    assert app.count_running_tasks_calls == 1
    assert app.did_quit is True


def test_agents_artifact_close_signal_path_clears_layout_without_tmux_check(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_file_tmux_pane_id = "%7"
    app._artifact_file_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-file-viewer-active")
    pane_exists = MagicMock()
    restore = MagicMock(return_value=ArtifactFileViewerResult(True))
    scheduled: list[Callable[[], None]] = []
    app.call_later = lambda callback: scheduled.append(callback)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        pane_exists,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_file_tmux_pane_decoration",
        restore,
    )

    app._schedule_artifact_file_viewer_closed_from_signal()

    assert app._artifact_file_tmux_pane_id == "%7"
    assert "-artifact-file-viewer-active" in app.content.classes
    assert len(scheduled) == 1

    scheduled[0]()
    scheduled[0]()

    pane_exists.assert_not_called()
    restore.assert_called_once_with(_decoration_state())
    assert app._artifact_file_tmux_pane_id is None
    assert app._artifact_file_tmux_decoration_state is None
    assert "-artifact-file-viewer-active" not in app.content.classes
