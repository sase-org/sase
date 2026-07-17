from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from rich.console import Console
from rich.console import Group
from rich.text import Text

from sase.ace.tui.graphics import ArtifactFileViewerResult
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.notifications import Notification


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, *_args) -> None:
        return None


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


def test_notification_modal_uses_video_placeholder_before_text_read(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = tmp_path / "notification.mp4"
    video.write_bytes(b"video")
    notification = Notification(
        id="n1",
        timestamp="2026-04-30T12:00:00-04:00",
        sender="test",
        files=[str(video)],
    )
    modal = NotificationModal([notification])
    title = MagicMock()
    content = MagicMock()
    scroll = MagicMock()

    def fake_query_one(selector, _type=None):
        if selector == "#notification-file-title":
            return title
        if selector == "#notification-file-content":
            return content
        if selector == "#notification-file-scroll":
            return scroll
        raise AssertionError(selector)

    monkeypatch.setattr(modal, "query_one", fake_query_one)

    modal._display_file(notification)

    content.update.assert_called_once()
    console = Console(record=True, width=100, color_system=None)
    console.print(content.update.call_args[0][0])
    output = console.export_text()
    assert "▶ video" in output
    assert "notification.mp4" in output
    assert "press V to play" in output
    scroll.scroll_home.assert_called_once_with(animate=False)


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

    def fake_viewer(path: str) -> ArtifactFileViewerResult:
        calls.append(path)
        assert suspend_recorder.entered is True
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_attachments.view_artifact_file",
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


def test_notification_view_image_action_runs_viewer_for_video(
    tmp_path: Path,
    monkeypatch,
) -> None:
    video = tmp_path / "notification.webm"
    video.write_bytes(b"video")
    notification = Notification(
        id="n1",
        timestamp="2026-04-30T12:00:00-04:00",
        sender="test",
        files=[str(video)],
    )
    modal = NotificationModal([notification])
    modal._get_highlighted_notification = lambda: notification  # type: ignore[method-assign]
    suspend_recorder = _SuspendRecorder()
    modal.notify = MagicMock()  # type: ignore[method-assign]
    calls: list[str] = []

    def fake_viewer(path: str) -> ArtifactFileViewerResult:
        calls.append(path)
        assert suspend_recorder.entered is True
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr(
        "sase.ace.tui.modals.notification_modal_attachments.view_artifact_file",
        fake_viewer,
    )

    with patch.object(
        NotificationModal,
        "app",
        new=SimpleNamespace(suspend=lambda: suspend_recorder),
    ):
        modal.action_view_image()

    assert calls == [str(video)]
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
        "sase.ace.tui.modals.notification_modal_attachments.view_artifact_file",
        viewer,
    )

    modal.action_view_image()

    viewer.assert_not_called()
    modal.notify.assert_called_once_with(
        "No image or video visible",
        severity="warning",
    )
