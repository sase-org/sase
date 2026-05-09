from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from sase.ace.tui.actions.agents._panels import AgentPanelsMixin
from sase.ace.tui.graphics import ArtifactViewerResult


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, *_args) -> None:
        return None


class _ClassRecorder:
    def __init__(self) -> None:
        self.classes: set[str] = set()

    def add_class(self, class_name: str) -> None:
        self.classes.add(class_name)

    def remove_class(self, class_name: str) -> None:
        self.classes.discard(class_name)


class _ImageActionApp(AgentPanelsMixin):
    def __init__(self, image_path: str | None) -> None:
        self.current_tab = "agents"
        self.current_attempt_number = None
        self.detail = MagicMock()
        self.detail.get_current_image_path.return_value = image_path
        self.content = _ClassRecorder()
        self.agent_list = MagicMock()
        self.suspend_recorder = _SuspendRecorder()
        self.notify = MagicMock()
        self._selected_agent = None
        self._artifacts = []
        self.pushed = []
        self._artifact_tmux_pane_id = None

    def query_one(self, selector, *_args, **_kwargs):
        if selector == "#agents-content":
            return self.content
        if selector == "#agent-list-panel":
            return self.agent_list
        return self.detail

    def suspend(self):
        return self.suspend_recorder

    def _get_selected_agent(self):
        return self._selected_agent

    def _list_selected_agent_artifacts(self, agent):
        del agent
        return self._artifacts

    def push_screen(self, modal, callback=None):
        self.pushed.append((modal, callback))


def test_agents_open_artifacts_action_pushes_single_artifact_selection_modal(
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

    def fake_viewer(viewed_artifact) -> ArtifactViewerResult:
        calls.append(viewed_artifact)
        assert app.suspend_recorder.entered is True
        return ArtifactViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifact", fake_viewer)

    app.action_open_agent_artifacts()

    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert modal.__class__.__name__ == "AgentArtifactSelectionModal"
    assert callback is not None
    assert calls == []

    callback(artifact)

    assert calls == [artifact]
    app.notify.assert_not_called()


def test_agents_open_artifacts_single_selection_uses_tmux_pane_without_suspend(
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

    def fake_tmux_viewer(viewed_artifact) -> ArtifactViewerResult:
        calls.append(viewed_artifact)
        assert app.suspend_recorder.entered is False
        return ArtifactViewerResult(True, pane_id="%7")

    same_pane_viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_agent_artifact_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifact", same_pane_viewer)

    app.action_open_agent_artifacts()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    assert calls == [artifact]
    assert app._artifact_tmux_pane_id == "%7"
    assert "-artifact-viewer-active" in app.content.classes
    same_pane_viewer.assert_not_called()
    app.notify.assert_not_called()


def test_agents_open_artifacts_action_surfaces_tmux_warning(
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
        "sase.ace.tui.graphics.view_agent_artifact_in_tmux_pane",
        lambda _artifact: ArtifactViewerResult(False, warning="tmux missing"),
    )

    app.action_open_agent_artifacts()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    assert app.suspend_recorder.entered is False
    app.notify.assert_called_once_with("tmux missing", severity="warning")


def test_agents_open_artifacts_action_warns_when_no_artifacts(monkeypatch) -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifact", viewer)

    app.action_open_agent_artifacts()

    viewer.assert_not_called()
    app.notify.assert_called_once_with("No artifacts found", severity="warning")


def test_agents_open_artifacts_action_warns_for_running_without_artifacts(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="RUNNING")
    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifact", viewer)

    app.action_open_agent_artifacts()

    viewer.assert_not_called()
    app.notify.assert_called_once_with(
        "No completed artifacts for this agent",
        severity="warning",
    )


def test_agents_open_artifacts_action_pushes_selection_modal() -> None:
    app = _ImageActionApp(None)
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [
        SimpleNamespace(path="/tmp/chat.md", kind="chat", label="Chat"),
        SimpleNamespace(path="/tmp/image.png", kind="image", label="Image"),
    ]

    app.action_open_agent_artifacts()

    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert modal.__class__.__name__ == "AgentArtifactSelectionModal"
    assert callback is not None


def test_agents_open_artifacts_modal_callback_restores_agent_list_focus(
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
        "sase.ace.tui.graphics.view_agent_artifact",
        lambda _artifact: ArtifactViewerResult(True),
    )
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)

    app.action_open_agent_artifacts()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifacts_modal_callback_opens_marked_sequence(
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

    def fake_viewer(selected_artifacts) -> ArtifactViewerResult:
        calls.append(list(selected_artifacts))
        assert app.suspend_recorder.entered is True
        return ArtifactViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: False)
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifacts", fake_viewer)

    app.action_open_agent_artifacts()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifacts)

    assert calls == [artifacts]
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifacts_modal_callback_opens_marked_sequence_in_tmux(
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

    def fake_tmux_viewer(selected_artifacts) -> ArtifactViewerResult:
        calls.append(list(selected_artifacts))
        assert app.suspend_recorder.entered is False
        return ArtifactViewerResult(True, pane_id="%7")

    same_pane_viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_agent_artifacts_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifacts", same_pane_viewer)

    app.action_open_agent_artifacts()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifacts)

    assert calls == [artifacts]
    assert app._artifact_tmux_pane_id == "%7"
    assert "-artifact-viewer-active" in app.content.classes
    same_pane_viewer.assert_not_called()
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifacts_action_closes_live_tracked_tmux_pane(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_tmux_pane_id = "%7"
    app.content.add_class("-artifact-viewer-active")
    exists = MagicMock(return_value=True)
    close = MagicMock(return_value=ArtifactViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr("sase.ace.tui.graphics.artifact_tmux_pane_exists", exists)
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_tmux_pane", close)

    app.action_open_agent_artifacts()

    exists.assert_called_once_with("%7")
    close.assert_called_once_with("%7")
    assert app._artifact_tmux_pane_id is None
    assert "-artifact-viewer-active" not in app.content.classes
    assert app.pushed == []
    app.notify.assert_not_called()


def test_agents_open_artifacts_action_clears_stale_tmux_pane_and_opens_modal(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_tmux_pane_id = "%7"
    app.content.add_class("-artifact-viewer-active")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [SimpleNamespace(path="/tmp/chat.md", kind="chat", label="Chat")]
    close = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: False,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_tmux_pane", close)

    app.action_open_agent_artifacts()

    close.assert_not_called()
    assert app._artifact_tmux_pane_id is None
    assert "-artifact-viewer-active" not in app.content.classes
    assert len(app.pushed) == 1
    modal, callback = app.pushed[0]
    assert modal.__class__.__name__ == "AgentArtifactSelectionModal"
    assert callback is not None


def test_agents_focus_tracked_artifact_tmux_pane_selects_live_pane(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_tmux_pane_id = "%7"
    select = MagicMock(return_value=ArtifactViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.select_tmux_pane", select)

    assert app._focus_tracked_artifact_tmux_pane() is True

    select.assert_called_once_with("%7")
    app.notify.assert_not_called()


def test_agents_focus_tracked_artifact_tmux_pane_surfaces_select_warning(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_tmux_pane_id = "%7"
    app.content.add_class("-artifact-viewer-active")
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.select_tmux_pane",
        lambda _pane_id: ArtifactViewerResult(False, warning="select failed"),
    )

    assert app._focus_tracked_artifact_tmux_pane() is True

    app.notify.assert_called_once_with("select failed", severity="warning")
    assert "-artifact-viewer-active" in app.content.classes


def test_agents_focus_tracked_artifact_tmux_pane_clears_stale_pane(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_tmux_pane_id = "%7"
    app.content.add_class("-artifact-viewer-active")
    select = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: False,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.select_tmux_pane", select)

    assert app._focus_tracked_artifact_tmux_pane() is False

    select.assert_not_called()
    assert app._artifact_tmux_pane_id is None
    assert "-artifact-viewer-active" not in app.content.classes
