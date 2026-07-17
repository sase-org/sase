from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._panel_artifact_files import (
    AgentPanelArtifactFileMixin,
)
from sase.ace.tui.graphics import (
    ArtifactFileViewerResult,
    TmuxPaneDecorationResult,
)
from sase.ace.tui.modals import ArtifactFileSelectionResult
from sase.core.artifact_file_facade import ArtifactFile

from ._artifact_file_image_helpers import _ImageActionApp, _decoration_state


class _ArtifactCacheApp(AgentPanelArtifactFileMixin):
    def __init__(self) -> None:
        self._daemon_read_client = None
        self._daemon_read_args = None


class _ArtifactCacheAgent:
    def __init__(self, artifacts_dir: Path) -> None:
        self.identity = ("run", "feature", "20260514100000")
        self.status = "RUNNING"
        self.diff_path = None
        self.response_path = None
        self.extra_files = []
        self._artifacts_dir = artifacts_dir

    def get_artifacts_dir(self) -> str:
        return str(self._artifacts_dir)


def test_agents_open_artifact_files_action_pushes_single_file_selection_modal(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _ImageActionApp(str(image))
    artifact = SimpleNamespace(path=str(image), kind="image", label="Image")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [artifact]
    calls: list[object] = []

    def fake_viewer(viewed_artifact) -> ArtifactFileViewerResult:
        calls.append(viewed_artifact)
        assert app.suspend_recorder.entered is True
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file", fake_viewer
    )

    app.action_open_artifact_files()

    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert modal.__class__.__name__ == "ArtifactFileSelectionModal"
    assert callback is not None
    assert calls == []

    callback(artifact)

    assert calls == [artifact]
    app.notify.assert_not_called()


def test_non_tmux_artifact_open_records_external_tool_wait(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import json

    from sase.logs import tui_external_tools_jsonl_path

    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _ImageActionApp(str(image))
    artifact = SimpleNamespace(path=str(image), kind="image", label="Image")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [artifact]

    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file",
        lambda _artifact: ArtifactFileViewerResult(True),
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None
    callback(artifact)

    # The intentional viewer suspend is logged as an external-tool wait, not a
    # generic event-loop stall.
    records = [
        json.loads(line)
        for line in tui_external_tools_jsonl_path().read_text().splitlines()
    ]
    assert len(records) == 1
    record = records[0]
    assert record["event"] == "external_tool_wait"
    assert record["action"] == "open_artifact_file"
    assert record["tool_kind"] == "artifact_file_viewer"
    assert record["path_count"] == 1
    assert record["current_tab"] == "agents"
    assert "elapsed_seconds" in record


def test_agents_artifact_cache_refetches_after_artifact_state_changes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _ArtifactCacheApp()
    agent = _ArtifactCacheAgent(tmp_path)
    artifact = ArtifactFile(
        id="chat",
        label="Chat",
        kind="chat",
        path=str(tmp_path / "chat.md"),
    )
    pages = [
        SimpleNamespace(artifact_files=[], request=None, shared_snapshot=None),
        SimpleNamespace(artifact_files=[artifact], request=None, shared_snapshot=None),
    ]
    calls = 0

    def fake_read_artifact_files_for_tui(*_args, **_kwargs):
        nonlocal calls
        page = pages[calls]
        calls += 1
        return SimpleNamespace(value=page, used_daemon=False)

    monkeypatch.setattr(
        "sase.ace.tui.actions.agents._artifact_file_provider.read_artifact_files_for_tui",
        fake_read_artifact_files_for_tui,
    )

    assert app._list_selected_artifact_files(agent) == []

    agent.status = "DONE"
    (tmp_path / "done.json").write_text("{}", encoding="utf-8")

    assert app._list_selected_artifact_files(agent) == [artifact]
    assert calls == 2


def test_agents_open_artifact_files_single_selection_uses_tmux_pane_without_suspend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _ImageActionApp(str(image))
    artifact = SimpleNamespace(path=str(image), kind="image", label="Image")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [artifact]
    calls: list[object] = []

    def fake_tmux_viewer(viewed_artifact) -> ArtifactFileViewerResult:
        calls.append(viewed_artifact)
        assert app.suspend_recorder.entered is False
        return ArtifactFileViewerResult(True, pane_id="%7")

    same_pane_viewer = MagicMock()
    decorate = MagicMock(
        return_value=TmuxPaneDecorationResult(True, state=_decoration_state())
    )
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.decorate_artifact_file_tmux_panes", decorate
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file", same_pane_viewer
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    assert calls == [artifact]
    assert app._artifact_file_tmux_pane_id == "%7"
    decorate.assert_called_once_with("%7")
    assert app._artifact_file_tmux_decoration_state == _decoration_state()
    assert "-artifact-file-viewer-active" in app.content.classes
    same_pane_viewer.assert_not_called()
    app.notify.assert_not_called()


def test_agents_open_artifact_files_zoomed_single_selection_passes_zoom_to_tmux(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _ImageActionApp(str(image))
    artifact = SimpleNamespace(path=str(image), kind="image", label="Image")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [artifact]
    calls: list[tuple[object, bool]] = []

    def fake_tmux_viewer(
        viewed_artifact,
        *,
        zoom: bool = False,
    ) -> ArtifactFileViewerResult:
        calls.append((viewed_artifact, zoom))
        assert app.suspend_recorder.entered is False
        return ArtifactFileViewerResult(True, pane_id="%7")

    decorate = MagicMock(
        return_value=TmuxPaneDecorationResult(True, state=_decoration_state())
    )
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.decorate_artifact_file_tmux_panes", decorate
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(ArtifactFileSelectionResult([artifact], zoom=True))

    assert calls == [(artifact, True)]
    assert app._artifact_file_tmux_pane_id == "%7"
    decorate.assert_called_once_with("%7")
    assert app._artifact_file_tmux_decoration_state == _decoration_state()
    assert "-artifact-file-viewer-active" in app.content.classes
    app.notify.assert_not_called()


def test_agents_tmux_artifact_launch_exposes_notify_pid_temporarily(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _ImageActionApp(str(image))
    artifact = SimpleNamespace(path=str(image), kind="image", label="Image")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [artifact]
    notify_values: list[str | None] = []
    monkeypatch.delenv("SASE_ARTIFACT_FILE_NOTIFY_PID", raising=False)
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.decorate_artifact_file_tmux_panes",
        lambda _pane_id: TmuxPaneDecorationResult(True, state=_decoration_state()),
    )

    def fake_tmux_viewer(_viewed_artifact) -> ArtifactFileViewerResult:
        notify_values.append(os.environ.get("SASE_ARTIFACT_FILE_NOTIFY_PID"))
        return ArtifactFileViewerResult(True, pane_id="%7")

    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file_in_tmux_pane",
        fake_tmux_viewer,
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    assert notify_values == [str(os.getpid())]
    assert os.environ.get("SASE_ARTIFACT_FILE_NOTIFY_PID") is None


def test_agents_open_artifact_files_action_surfaces_tmux_warning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _ImageActionApp(str(image))
    artifact = SimpleNamespace(path=str(image), kind="image", label="Image")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [artifact]
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file_in_tmux_pane",
        lambda _artifact: ArtifactFileViewerResult(False, warning="tmux missing"),
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    assert app.suspend_recorder.entered is False
    app.notify.assert_called_once_with("tmux missing", severity="warning")


def test_agents_open_artifact_files_action_warns_when_no_files(monkeypatch) -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_registered_artifact_file", viewer)

    app.action_open_artifact_files()

    viewer.assert_not_called()
    app.notify.assert_called_once_with("No artifact files found", severity="warning")


def test_agents_open_artifact_files_action_warns_for_running_without_files(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="RUNNING")
    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_registered_artifact_file", viewer)

    app.action_open_artifact_files()

    viewer.assert_not_called()
    app.notify.assert_called_once_with(
        "No completed artifact files for this agent",
        severity="warning",
    )


def test_agents_open_artifact_files_action_pushes_selection_modal() -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [
        SimpleNamespace(path="/tmp/chat.md", kind="chat", label="Chat"),
        SimpleNamespace(path="/tmp/image.png", kind="image", label="Image"),
    ]

    app.action_open_artifact_files()

    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert modal.__class__.__name__ == "ArtifactFileSelectionModal"
    assert callback is not None


def test_agents_open_artifact_files_modal_callback_restores_agent_list_focus(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    artifact = SimpleNamespace(path=str(image), kind="image", label="Image")
    app = _ImageActionApp(str(image))
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [
        SimpleNamespace(path="/tmp/chat.md", kind="chat", label="Chat"),
        artifact,
    ]
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_file",
        lambda _artifact: ArtifactFileViewerResult(True),
    )
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifact_files_modal_callback_opens_marked_sequence(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    artifacts = [
        SimpleNamespace(path=str(tmp_path / "chat.md"), kind="chat", label="Chat"),
        SimpleNamespace(path=str(tmp_path / "image.png"), kind="image", label="Image"),
    ]
    app._artifacts = artifacts
    calls: list[list[object]] = []

    def fake_viewer(selected_artifacts) -> ArtifactFileViewerResult:
        calls.append(list(selected_artifacts))
        assert app.suspend_recorder.entered is True
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_files", fake_viewer
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifacts)

    assert calls == [artifacts]
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifact_files_modal_callback_opens_marked_sequence_in_tmux(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    artifacts = [
        SimpleNamespace(path=str(tmp_path / "chat.md"), kind="chat", label="Chat"),
        SimpleNamespace(path=str(tmp_path / "image.png"), kind="image", label="Image"),
    ]
    app._artifacts = artifacts
    calls: list[list[object]] = []

    def fake_tmux_viewer(selected_artifacts) -> ArtifactFileViewerResult:
        calls.append(list(selected_artifacts))
        assert app.suspend_recorder.entered is False
        return ArtifactFileViewerResult(True, pane_id="%7")

    same_pane_viewer = MagicMock()
    decorate = MagicMock(
        return_value=TmuxPaneDecorationResult(True, state=_decoration_state())
    )
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_files_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.decorate_artifact_file_tmux_panes", decorate
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_files", same_pane_viewer
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifacts)

    assert calls == [artifacts]
    assert app._artifact_file_tmux_pane_id == "%7"
    decorate.assert_called_once_with("%7")
    assert app._artifact_file_tmux_decoration_state == _decoration_state()
    assert "-artifact-file-viewer-active" in app.content.classes
    same_pane_viewer.assert_not_called()
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifact_files_zoomed_marked_sequence_passes_zoom_to_tmux(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    artifacts = [
        SimpleNamespace(path=str(tmp_path / "chat.md"), kind="chat", label="Chat"),
        SimpleNamespace(path=str(tmp_path / "image.png"), kind="image", label="Image"),
    ]
    app._artifacts = artifacts
    calls: list[tuple[list[object], bool]] = []

    def fake_tmux_viewer(
        selected_artifacts,
        *,
        zoom: bool = False,
    ) -> ArtifactFileViewerResult:
        calls.append((list(selected_artifacts), zoom))
        assert app.suspend_recorder.entered is False
        return ArtifactFileViewerResult(True, pane_id="%7")

    decorate = MagicMock(
        return_value=TmuxPaneDecorationResult(True, state=_decoration_state())
    )
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_file_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_registered_artifact_files_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.decorate_artifact_file_tmux_panes", decorate
    )

    app.action_open_artifact_files()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(ArtifactFileSelectionResult(artifacts, zoom=True))

    assert calls == [(artifacts, True)]
    assert app._artifact_file_tmux_pane_id == "%7"
    decorate.assert_called_once_with("%7")
    assert app._artifact_file_tmux_decoration_state == _decoration_state()
    assert "-artifact-file-viewer-active" in app.content.classes
    app.agent_list.focus.assert_called_once_with()
