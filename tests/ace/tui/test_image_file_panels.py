from __future__ import annotations

import json
import types
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console, Group
from rich.text import Text

from sase.ace.tui.actions.agents._panels import AgentPanelsMixin
from sase.ace.tui.graphics import (
    ArtifactViewerResult,
    ImageFallbackRenderable,
    ImageViewerResult,
    image_preview_size_for_viewport,
)
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.models._loaders._done_loaders import (
    _load_done_agent_for_dir,
    load_done_agents_from_snapshot,
)
from sase.ace.tui.widgets.file_panel import AgentFilePanel
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    DoneMarkerWire,
)
from sase.notifications import Notification


def _make_file_panel() -> MagicMock:
    panel = MagicMock()
    panel.post_message = MagicMock()
    panel._has_displayed_content = False
    panel._file_list = []
    panel._current_file_index = 0
    panel._total_line_count = 0
    panel._visible_line_count = 0
    panel._base_trim_size = 0
    panel._is_trimmed = False
    panel._full_content = "old"
    panel._full_content_lexer = "text"
    panel._content_mode = "none"
    panel._static_header_path = None
    panel._current_image_renderable = None
    panel._post_file_visibility = types.MethodType(
        AgentFilePanel._post_file_visibility, panel
    )
    panel._post_trim_changed = MagicMock()
    panel._count_lines = types.MethodType(AgentFilePanel._count_lines, panel)
    panel._consume_image_cleanup_segments = types.MethodType(
        AgentFilePanel._consume_image_cleanup_segments, panel
    )
    panel._image_render_context = types.MethodType(
        AgentFilePanel._image_render_context, panel
    )
    panel._image_preview_size = MagicMock(return_value=(33, 9))
    panel._display_static_image = types.MethodType(
        AgentFilePanel._display_static_image, panel
    )
    return panel


def test_agent_file_panel_uses_image_preview_before_text_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "render.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n\xff")
    panel = _make_file_panel()
    calls: list[tuple[str, int, int]] = []

    def fake_image_preview(path, _context, *, columns, rows):
        calls.append((path, columns, rows))
        return Text("image-preview")

    monkeypatch.setattr(
        "sase.ace.tui.widgets.file_panel._display.image_preview",
        fake_image_preview,
    )

    AgentFilePanel.display_static_file(panel, str(image))

    assert calls == [(str(image), 33, 9)]
    assert panel._content_mode == "image"
    assert panel._static_header_path == str(image)
    assert panel._full_content is None
    panel.post_message.assert_called()
    assert panel.post_message.call_args[0][0].has_file is True
    group = panel.update.call_args[0][0]
    assert isinstance(group, Group)


def test_agent_file_panel_current_image_path_requires_visible_existing_image(
    tmp_path: Path,
) -> None:
    image = tmp_path / "visible.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    text = tmp_path / "notes.txt"
    text.write_text("hello", encoding="utf-8")
    missing = tmp_path / "missing.jpg"
    panel = AgentFilePanel()
    panel._file_list = [str(text), str(image), "__live_diff__", str(missing)]

    panel._current_file_index = 0
    assert panel.get_current_image_path() is None

    panel._current_file_index = 1
    assert panel.get_current_image_path() == str(image)

    panel._current_file_index = 2
    assert panel.get_current_image_path() is None

    panel._current_file_index = 3
    assert panel.get_current_image_path() is None


def test_notification_modal_uses_image_preview_before_text_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "notification.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n\xff")
    notification = Notification(
        id="n1",
        timestamp="2026-04-30T12:00:00-04:00",
        sender="test",
        files=[str(image)],
    )
    modal = NotificationModal([notification])
    title = MagicMock()
    content = MagicMock()
    scroll = MagicMock()
    scroll.scrollable_content_region = SimpleNamespace(width=28, height=7)
    calls: list[str] = []

    def fake_query_one(selector, _type=None):
        if selector == "#notification-file-title":
            return title
        if selector == "#notification-file-content":
            return content
        if selector == "#notification-file-scroll":
            return scroll
        raise AssertionError(selector)

    def fake_image_preview(path, _context, *, columns, rows):
        calls.append(path)
        assert (columns, rows) == (28, 7)
        return Text("image-preview")

    monkeypatch.setattr(modal, "query_one", fake_query_one)
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal.image_preview",
        fake_image_preview,
    )

    modal._display_file(notification)

    assert calls == [str(image)]
    content.update.assert_called_once()
    assert isinstance(content.update.call_args[0][0], Group)
    title.update.assert_called_once()
    scroll.scroll_home.assert_called_once_with(animate=False)


def test_notification_modal_current_image_path_tracks_file_index(
    tmp_path: Path,
) -> None:
    image = tmp_path / "notification.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    text = tmp_path / "notes.md"
    text.write_text("hello", encoding="utf-8")
    notification = Notification(
        id="n1",
        timestamp="2026-04-30T12:00:00-04:00",
        sender="test",
        files=[str(text), str(image)],
    )
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]

    modal._current_file_index = 0
    assert modal._get_current_image_path() is None

    modal._current_file_index = 1
    assert modal._get_current_image_path() == str(image)


def test_agent_file_panel_image_size_uses_scroll_viewport() -> None:
    panel = MagicMock()
    scroll = SimpleNamespace(
        scrollable_content_region=SimpleNamespace(width=31, height=11)
    )
    panel._get_scroll_container = MagicMock(return_value=scroll)

    assert AgentFilePanel._image_preview_size(panel) == (31, 9)


def test_notification_image_size_uses_scroll_viewport(monkeypatch) -> None:
    modal = NotificationModal([])
    content = MagicMock()
    scroll = SimpleNamespace(
        scrollable_content_region=SimpleNamespace(width=22, height=30)
    )

    def fake_query_one(selector, _type=None):
        if selector == "#notification-file-scroll":
            return scroll
        raise AssertionError(selector)

    monkeypatch.setattr(modal, "query_one", fake_query_one)

    assert modal._image_preview_size(content) == (22, 30)


def test_image_preview_size_caps_large_viewports() -> None:
    scroll = SimpleNamespace(
        scrollable_content_region=SimpleNamespace(width=220, height=90)
    )

    assert image_preview_size_for_viewport(scroll_widget=scroll) == (160, 60)


def test_notification_image_mode_marks_layout_widgets(monkeypatch) -> None:
    modal = NotificationModal([])
    widgets = {
        "#notification-container": MagicMock(),
        "#notification-left": MagicMock(),
        "#notification-right": MagicMock(),
    }

    def fake_query_one(selector, _type=None):
        return widgets[selector]

    monkeypatch.setattr(modal, "query_one", fake_query_one)

    modal._set_image_preview_mode(True)
    modal._set_image_preview_mode(False)

    for widget in widgets.values():
        widget.add_class.assert_called_once_with("image-preview")
        widget.remove_class.assert_called_once_with("image-preview")


def test_image_preview_size_for_tiny_viewport_stays_bounded() -> None:
    scroll = SimpleNamespace(
        scrollable_content_region=SimpleNamespace(width=3, height=2)
    )

    assert image_preview_size_for_viewport(
        scroll_widget=scroll,
        reserved_rows=2,
    ) == (3, 1)


def test_done_loader_adds_image_paths_to_extra_files(tmp_path: Path) -> None:
    artifact_dir = tmp_path / "20260430120000"
    artifact_dir.mkdir()
    plan = tmp_path / "plan.md"
    pdf = tmp_path / "notes.pdf"
    image = tmp_path / "image.png"
    duplicate = tmp_path / "duplicate.png"
    done = {
        "cl_name": "feature",
        "project_file": "/tmp/project.gp",
        "outcome": "completed",
        "plan_path": str(plan),
        "markdown_pdf_paths": [str(pdf), str(plan)],
        "image_paths": [str(image), str(plan), str(duplicate)],
    }
    (artifact_dir / "done.json").write_text(json.dumps(done), encoding="utf-8")

    agent = _load_done_agent_for_dir(artifact_dir, "ace-run", {}, {})

    assert agent is not None
    assert agent.extra_files == [str(plan), str(pdf), str(image), str(duplicate)]


def test_snapshot_done_loader_adds_image_paths_to_extra_files(tmp_path: Path) -> None:
    plan = tmp_path / "plan.md"
    pdf = tmp_path / "notes.pdf"
    image = tmp_path / "image.png"
    duplicate = tmp_path / "duplicate.png"
    record = AgentArtifactRecordWire(
        project_name="myproj",
        project_dir=str(tmp_path / "myproj"),
        project_file=str(tmp_path / "myproj" / "myproj.gp"),
        workflow_dir_name="ace-run",
        artifact_dir=str(tmp_path / "artifacts" / "ace-run" / "20260430120000"),
        timestamp="20260430120000",
        done=DoneMarkerWire(
            outcome="completed",
            cl_name="feature",
            project_file="/tmp/project.gp",
            plan_path=str(plan),
            markdown_pdf_paths=[str(pdf), str(plan)],
            image_paths=[str(image), str(plan), str(duplicate)],
        ),
        has_done_marker=True,
    )
    snapshot = AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root=str(tmp_path),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[record],
    )

    agents = load_done_agents_from_snapshot(snapshot, {}, {})

    assert len(agents) == 1
    assert agents[0].extra_files == [
        str(plan),
        str(pdf),
        str(image),
        str(duplicate),
    ]


def test_image_fallback_mentions_editor_actions(tmp_path: Path) -> None:
    image = tmp_path / "fallback.jpg"
    image.write_bytes(b"jpeg")
    renderable = ImageFallbackRenderable(str(image), "no graphics")

    console = Console(record=True, width=100)
    console.print(renderable)

    fallback_text = console.export_text()
    assert "Open artifact with A" in fallback_text


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, *_args) -> None:
        return None


class _ImageActionApp(AgentPanelsMixin):
    def __init__(self, image_path: str | None) -> None:
        self.current_tab = "agents"
        self.current_attempt_number = None
        self.detail = MagicMock()
        self.detail.get_current_image_path.return_value = image_path
        self.agent_list = MagicMock()
        self.suspend_recorder = _SuspendRecorder()
        self.notify = MagicMock()
        self._selected_agent = None
        self._artifacts = []
        self.pushed = []

    def query_one(self, selector, *_args, **_kwargs):
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


def test_agents_open_artifacts_action_runs_single_viewer_inside_suspend(
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

    assert calls == [artifact]
    app.notify.assert_not_called()


def test_agents_open_artifacts_action_uses_tmux_pane_without_suspend(
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
        return ArtifactViewerResult(True)

    same_pane_viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.is_tmux_session", lambda: True)
    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_agent_artifact_in_tmux_pane",
        fake_tmux_viewer,
    )
    monkeypatch.setattr("sase.ace.tui.graphics.view_agent_artifact", same_pane_viewer)

    app.action_open_agent_artifacts()

    assert calls == [artifact]
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


def test_notification_view_image_action_runs_viewer_inside_suspend(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image = tmp_path / "notification.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    notification = Notification(
        id="n1",
        timestamp="2026-04-30T12:00:00-04:00",
        sender="test",
        files=[str(image)],
    )
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    suspend_recorder = _SuspendRecorder()
    modal.notify = MagicMock()  # type: ignore[method-assign]
    calls: list[str] = []

    def fake_viewer(path: str) -> ImageViewerResult:
        calls.append(path)
        assert suspend_recorder.entered is True
        return ImageViewerResult(True)

    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_attachments.view_image_file",
        fake_viewer,
    )

    with patch.object(
        NotificationModal,
        "app",
        new=SimpleNamespace(suspend=lambda: suspend_recorder),
    ):
        modal.action_view_image()

    assert calls == [str(image)]
    modal.notify.assert_not_called()


def test_notification_view_image_action_warns_for_non_image(monkeypatch) -> None:
    notification = Notification(
        id="n1",
        timestamp="2026-04-30T12:00:00-04:00",
        sender="test",
        files=["/tmp/not-image.txt"],
    )
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    modal.notify = MagicMock()  # type: ignore[method-assign]
    viewer = MagicMock()
    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_attachments.view_image_file",
        viewer,
    )

    modal.action_view_image()

    viewer.assert_not_called()
    modal.notify.assert_called_once_with("No image visible", severity="warning")
