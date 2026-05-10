from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sase.ace.tui.actions.agents._panels import AgentPanelsMixin
from sase.ace.tui.actions.lifecycle import LifecycleMixin
from sase.ace.tui.graphics import (
    ArtifactViewerResult,
    TmuxPaneDecorationResult,
    TmuxPaneDecorationState,
)


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
        self._artifacts_by_agent: dict[object, list[object]] = {}
        self.pushed = []
        self._artifact_tmux_pane_id = None
        self._artifact_tmux_decoration_state = None
        self._agents_with_children = []
        self._marked_agents = set()

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
        if agent is not None and id(agent) in self._artifacts_by_agent:
            return self._artifacts_by_agent[id(agent)]
        return self._artifacts

    def push_screen(self, modal, callback=None):
        self.pushed.append((modal, callback))


class _ImageQuitApp(_ImageActionApp, LifecycleMixin):
    def __init__(self) -> None:
        super().__init__(None)
        self.count_running_tasks_calls = 0
        self.did_quit = False

    def _count_running_tasks(self) -> int:
        self.count_running_tasks_calls += 1
        return 0

    def _do_quit(self) -> None:
        self.did_quit = True


def _decoration_state() -> TmuxPaneDecorationState:
    return TmuxPaneDecorationState(
        target_pane_id="%1",
        window_options=(),
        pane_titles=(),
    )


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
    decorate = MagicMock(
        return_value=TmuxPaneDecorationResult(True, state=_decoration_state())
    )
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_agent_artifact_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.decorate_artifact_tmux_panes", decorate)
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifact", same_pane_viewer)

    app.action_open_agent_artifacts()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    assert calls == [artifact]
    assert app._artifact_tmux_pane_id == "%7"
    decorate.assert_called_once_with("%7")
    assert app._artifact_tmux_decoration_state == _decoration_state()
    assert "-artifact-viewer-active" in app.content.classes
    same_pane_viewer.assert_not_called()
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
    monkeypatch.delenv("SASE_ARTIFACT_NOTIFY_PID", raising=False)
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.decorate_artifact_tmux_panes",
        lambda _pane_id: TmuxPaneDecorationResult(True, state=_decoration_state()),
    )

    def fake_tmux_viewer(_viewed_artifact) -> ArtifactViewerResult:
        notify_values.append(os.environ.get("SASE_ARTIFACT_NOTIFY_PID"))
        return ArtifactViewerResult(True, pane_id="%7")

    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_agent_artifact_in_tmux_pane",
        fake_tmux_viewer,
    )

    app.action_open_agent_artifacts()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifact)

    assert notify_values == [str(os.getpid())]
    assert os.environ.get("SASE_ARTIFACT_NOTIFY_PID") is None


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
    decorate = MagicMock(
        return_value=TmuxPaneDecorationResult(True, state=_decoration_state())
    )
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_agent_artifacts_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.decorate_artifact_tmux_panes", decorate)
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifacts", same_pane_viewer)

    app.action_open_agent_artifacts()
    _modal, callback = app.pushed[0]
    assert callback is not None

    callback(artifacts)

    assert calls == [artifacts]
    assert app._artifact_tmux_pane_id == "%7"
    decorate.assert_called_once_with("%7")
    assert app._artifact_tmux_decoration_state == _decoration_state()
    assert "-artifact-viewer-active" in app.content.classes
    same_pane_viewer.assert_not_called()
    app.agent_list.focus.assert_called_once_with()


def test_agents_open_artifacts_action_closes_live_tracked_tmux_pane(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_tmux_pane_id = "%7"
    app._artifact_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-viewer-active")
    exists = MagicMock(return_value=True)
    close = MagicMock(return_value=ArtifactViewerResult(True))
    restore = MagicMock(return_value=ArtifactViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr("sase.ace.tui.graphics.artifact_tmux_pane_exists", exists)
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_tmux_pane", close)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_tmux_pane_decoration",
        restore,
    )

    app.action_open_agent_artifacts()

    exists.assert_called_once_with("%7")
    restore.assert_called_once_with(_decoration_state())
    close.assert_called_once_with("%7")
    assert app._artifact_tmux_pane_id is None
    assert app._artifact_tmux_decoration_state is None
    assert "-artifact-viewer-active" not in app.content.classes
    assert app.pushed == []
    app.notify.assert_not_called()


def test_agents_open_artifacts_action_clears_stale_tmux_pane_and_opens_modal(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_tmux_pane_id = "%7"
    app._artifact_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-viewer-active")
    app._selected_agent = SimpleNamespace(status="DONE")
    app._artifacts = [SimpleNamespace(path="/tmp/chat.md", kind="chat", label="Chat")]
    close = MagicMock()
    restore = MagicMock(return_value=ArtifactViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: False,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_tmux_pane", close)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_tmux_pane_decoration",
        restore,
    )

    app.action_open_agent_artifacts()

    close.assert_not_called()
    restore.assert_called_once_with(_decoration_state())
    assert app._artifact_tmux_pane_id is None
    assert app._artifact_tmux_decoration_state is None
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
    app._artifact_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-viewer-active")
    select = MagicMock()
    restore = MagicMock(return_value=ArtifactViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: False,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.select_tmux_pane", select)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_tmux_pane_decoration",
        restore,
    )

    assert app._focus_tracked_artifact_tmux_pane() is False

    select.assert_not_called()
    restore.assert_called_once_with(_decoration_state())
    assert app._artifact_tmux_pane_id is None
    assert app._artifact_tmux_decoration_state is None
    assert "-artifact-viewer-active" not in app.content.classes


@pytest.mark.asyncio
async def test_action_quit_closes_live_artifact_pane_before_quit_flow(
    monkeypatch,
) -> None:
    app = _ImageQuitApp()
    app._artifact_tmux_pane_id = "%7"
    app._artifact_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-viewer-active")
    close = MagicMock(return_value=ArtifactViewerResult(True))
    restore = MagicMock(return_value=ArtifactViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: True,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_tmux_pane", close)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_tmux_pane_decoration",
        restore,
    )

    await app.action_quit()

    restore.assert_called_once_with(_decoration_state())
    close.assert_called_once_with("%7")
    assert app._artifact_tmux_pane_id is None
    assert app._artifact_tmux_decoration_state is None
    assert "-artifact-viewer-active" not in app.content.classes
    assert app.count_running_tasks_calls == 0
    assert app.did_quit is False


@pytest.mark.asyncio
async def test_action_quit_ignores_stale_artifact_pane_and_continues(
    monkeypatch,
) -> None:
    app = _ImageQuitApp()
    app._artifact_tmux_pane_id = "%7"
    app._artifact_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-viewer-active")
    close = MagicMock()
    restore = MagicMock(return_value=ArtifactViewerResult(True))
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        lambda _pane_id: False,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.close_artifact_tmux_pane", close)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_tmux_pane_decoration",
        restore,
    )

    await app.action_quit()

    close.assert_not_called()
    restore.assert_called_once_with(_decoration_state())
    assert app._artifact_tmux_pane_id is None
    assert app._artifact_tmux_decoration_state is None
    assert "-artifact-viewer-active" not in app.content.classes
    assert app.count_running_tasks_calls == 1
    assert app.did_quit is True


def test_agents_artifact_close_signal_path_clears_layout_without_tmux_check(
    monkeypatch,
) -> None:
    app = _ImageActionApp(None)
    app._artifact_tmux_pane_id = "%7"
    app._artifact_tmux_decoration_state = _decoration_state()
    app.content.add_class("-artifact-viewer-active")
    pane_exists = MagicMock()
    restore = MagicMock(return_value=ArtifactViewerResult(True))
    scheduled: list[Callable[[], None]] = []
    app.call_later = lambda callback: scheduled.append(callback)  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "sase.ace.tui.graphics.artifact_tmux_pane_exists",
        pane_exists,
    )
    monkeypatch.setattr(
        "sase.ace.tui.graphics.restore_artifact_tmux_pane_decoration",
        restore,
    )

    app._schedule_artifact_viewer_closed_from_signal()

    assert app._artifact_tmux_pane_id == "%7"
    assert "-artifact-viewer-active" in app.content.classes
    assert len(scheduled) == 1

    scheduled[0]()
    scheduled[0]()

    pane_exists.assert_not_called()
    restore.assert_called_once_with(_decoration_state())
    assert app._artifact_tmux_pane_id is None
    assert app._artifact_tmux_decoration_state is None
    assert "-artifact-viewer-active" not in app.content.classes


def _marked_agent(
    *,
    name: str,
    artifacts: list[object],
    agent_name: str | None = None,
) -> SimpleNamespace:
    identity = ("RUNNING", name, None)
    return SimpleNamespace(
        status="DONE",
        identity=identity,
        display_name=name,
        agent_name=agent_name,
        _artifacts=artifacts,
    )


def test_agents_open_artifacts_action_aggregates_marked_agents() -> None:
    foo = _marked_agent(
        name="foo",
        artifacts=[
            SimpleNamespace(path="/tmp/foo/proposal.md", kind="plan", label="Plan"),
            SimpleNamespace(path="/tmp/foo/diff.patch", kind="diff", label="Diff"),
        ],
    )
    bar = _marked_agent(
        name="bar",
        artifacts=[
            SimpleNamespace(path="/tmp/bar/proposal.md", kind="plan", label="Plan"),
            SimpleNamespace(path="/tmp/bar/diff.patch", kind="diff", label="Diff"),
        ],
    )
    app = _ImageActionApp(None)
    app._selected_agent = foo
    app._agents_with_children = [foo, bar]
    app._marked_agents = {foo.identity, bar.identity}
    app._artifacts_by_agent = {
        id(foo): foo._artifacts,
        id(bar): bar._artifacts,
    }

    app.action_open_agent_artifacts()

    assert len(app.pushed) == 1
    modal, _callback = app.pushed[0]
    assert modal.__class__.__name__ == "AgentArtifactSelectionModal"
    assert len(modal._artifacts) == 4
    assert modal._artifacts[0] is foo._artifacts[0]
    assert modal._artifacts[1] is foo._artifacts[1]
    assert modal._artifacts[2] is bar._artifacts[0]
    assert modal._artifacts[3] is bar._artifacts[1]
    assert modal._agent_labels == ["foo", "foo", "bar", "bar"]
    assert modal._agent_count == 2
    assert modal._title_text() == "Agent Artifacts  [4 from 2 agents]"
    app.notify.assert_not_called()


def test_agents_open_artifacts_action_marked_path_skips_stale_marks() -> None:
    foo = _marked_agent(
        name="foo",
        artifacts=[
            SimpleNamespace(path="/tmp/foo/diff.patch", kind="diff", label="Diff"),
        ],
    )
    stale_identity = ("RUNNING", "ghost", None)
    app = _ImageActionApp(None)
    app._selected_agent = foo
    app._agents_with_children = [foo]
    app._marked_agents = {foo.identity, stale_identity}
    app._artifacts_by_agent = {id(foo): foo._artifacts}

    app.action_open_agent_artifacts()

    assert len(app.pushed) == 1
    modal, _callback = app.pushed[0]
    assert len(modal._artifacts) == 1
    assert modal._agent_count == 1
    assert modal._title_text() == "Agent Artifacts  [1]"


def test_agents_open_artifacts_action_warns_when_marked_artifacts_empty() -> None:
    foo = _marked_agent(name="foo", artifacts=[])
    bar = _marked_agent(name="bar", artifacts=[])
    app = _ImageActionApp(None)
    app._selected_agent = foo
    app._agents_with_children = [foo, bar]
    app._marked_agents = {foo.identity, bar.identity}
    app._artifacts_by_agent = {id(foo): [], id(bar): []}

    app.action_open_agent_artifacts()

    assert app.pushed == []
    app.notify.assert_called_once_with(
        "No artifacts found in marked agents",
        severity="warning",
    )


def test_agents_open_artifacts_action_warns_when_all_marks_stale() -> None:
    stale_a = ("RUNNING", "ghost-a", None)
    stale_b = ("RUNNING", "ghost-b", None)
    app = _ImageActionApp(None)
    app._agents_with_children = []
    app._marked_agents = {stale_a, stale_b}

    app.action_open_agent_artifacts()

    assert app.pushed == []
    app.notify.assert_called_once_with(
        "No marked agents remain",
        severity="warning",
    )


def test_agents_open_artifacts_action_uses_agent_name_suffix_when_distinct() -> None:
    foo = _marked_agent(
        name="cl-name-foo",
        agent_name="planner",
        artifacts=[
            SimpleNamespace(path="/tmp/foo/plan.md", kind="plan", label="Plan"),
        ],
    )
    app = _ImageActionApp(None)
    app._selected_agent = foo
    app._agents_with_children = [foo]
    app._marked_agents = {foo.identity}
    app._artifacts_by_agent = {id(foo): foo._artifacts}

    app.action_open_agent_artifacts()

    assert len(app.pushed) == 1
    modal, _callback = app.pushed[0]
    assert modal._agent_labels == ["cl-name-foo @planner"]
