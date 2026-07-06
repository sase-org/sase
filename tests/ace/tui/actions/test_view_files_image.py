"""Tests for image-aware routing of the ``v`` view-file hint flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from sase.ace.tui.actions.hints._files import FileViewingMixin
from sase.ace.tui.actions.hints._processing import InputProcessingMixin
from sase.ace.tui.graphics import ArtifactViewerResult, ArtifactViewSpec


class _SuspendRecorder:
    def __init__(self) -> None:
        self.entered = False

    def __enter__(self) -> None:
        self.entered = True

    def __exit__(self, *_args) -> None:
        return None


class _ViewApp(InputProcessingMixin, FileViewingMixin):
    """Minimal app combining the hint view mixins for routing tests."""

    def __init__(self, hint_mappings: dict[int, str]) -> None:
        self._hint_mappings = hint_mappings
        self._hint_changespec_name = "cs"
        self.notify = MagicMock()
        self.suspend_recorder = _SuspendRecorder()

    def suspend(self):
        return self.suspend_recorder


def _make_app(*paths: str) -> _ViewApp:
    return _ViewApp({i + 1: path for i, path in enumerate(paths)})


def test_text_only_selection_uses_pager(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    app._process_view_input("1")

    app._view_files_with_pager.assert_called_once_with([str(notes)])
    viewer.assert_not_called()


def test_image_only_selection_uses_artifact_viewer(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactViewSpec]] = []

    def fake_viewer(specs) -> ArtifactViewerResult:
        calls.append(list(specs))
        assert app.suspend_recorder.entered is True
        return ArtifactViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    app._process_view_input("1")

    assert calls == [[ArtifactViewSpec(str(image), kind="image")]]
    app._view_files_with_pager.assert_not_called()
    app.notify.assert_not_called()


def test_video_only_selection_uses_artifact_viewer(tmp_path: Path, monkeypatch) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    app = _make_app(str(video))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactViewSpec]] = []

    def fake_viewer(specs) -> ArtifactViewerResult:
        calls.append(list(specs))
        assert app.suspend_recorder.entered is True
        return ArtifactViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    app._process_view_input("1")

    assert calls == [[ArtifactViewSpec(str(video), kind="file")]]
    app._view_files_with_pager.assert_not_called()
    app.notify.assert_not_called()


def test_mixed_selection_routes_all_files_in_order(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    notes = tmp_path / "notes.md"
    notes.write_text("# notes", encoding="utf-8")
    app = _make_app(str(image), str(notes))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactViewSpec]] = []

    def fake_viewer(specs) -> ArtifactViewerResult:
        calls.append(list(specs))
        return ArtifactViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    app._process_view_input("1 2")

    assert calls == [
        [
            ArtifactViewSpec(str(image), kind="image"),
            ArtifactViewSpec(str(notes), kind="file"),
        ]
    ]
    app._view_files_with_pager.assert_not_called()


def test_artifact_viewer_warning_is_surfaced(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))

    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_artifact_files",
        lambda _specs: ArtifactViewerResult(False, warning="kitten missing"),
    )

    app._process_view_input("1")

    app.notify.assert_called_once_with("kitten missing", severity="warning")


def test_editor_suffix_bypasses_artifact_viewer(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    app._process_view_input("1@")

    app._open_files_in_editor.assert_called_once()
    result = app._open_files_in_editor.call_args.args[0]
    assert result.open_in_editor is True
    assert result.files == [str(image)]
    viewer.assert_not_called()


def test_clipboard_suffix_bypasses_artifact_viewer(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._copy_files_to_clipboard = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    app._process_view_input("1%")

    app._copy_files_to_clipboard.assert_called_once_with([str(image)])
    viewer.assert_not_called()
