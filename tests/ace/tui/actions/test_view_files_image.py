"""Tests for ordinary and image artifact routing in the view-file hint flow."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from sase.ace.tui.graphics import ArtifactFileViewerResult, ArtifactFileViewSpec
from sase.ace.tui.widgets import HintInputBar

from ._view_files_helpers import _make_app


def test_view_submission_schedules_untracked_worker() -> None:
    app = _make_app("notes.md")
    app._remove_hint_input_bar = MagicMock()  # type: ignore[method-assign]
    scheduled: list[object] = []
    app.run_worker = MagicMock(  # type: ignore[attr-defined]
        side_effect=lambda work, **_kwargs: scheduled.append(work)
    )

    app.on_hint_input_bar_submitted(HintInputBar.Submitted("1", "view"))

    app._remove_hint_input_bar.assert_called_once_with()
    app.run_worker.assert_called_once()  # type: ignore[attr-defined]
    assert len(scheduled) == 1
    scheduled[0].close()  # type: ignore[attr-defined]


async def test_text_only_selection_uses_pager(tmp_path: Path, monkeypatch) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello", encoding="utf-8")
    app = _make_app(str(notes))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    await app._process_view_input("1")

    app._view_files_with_pager.assert_called_once_with([str(notes)])
    viewer.assert_not_called()


async def test_image_only_selection_uses_artifact_file_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactFileViewSpec]] = []

    def fake_viewer(specs) -> ArtifactFileViewerResult:
        calls.append(list(specs))
        assert app.suspend_recorder.entered is True
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    await app._process_view_input("1")

    assert calls == [[ArtifactFileViewSpec(str(image), kind="image")]]
    app._view_files_with_pager.assert_not_called()
    app.notify.assert_not_called()


async def test_video_only_selection_uses_artifact_file_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    app = _make_app(str(video))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactFileViewSpec]] = []

    def fake_viewer(specs) -> ArtifactFileViewerResult:
        calls.append(list(specs))
        assert app.suspend_recorder.entered is True
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    await app._process_view_input("1")

    assert calls == [[ArtifactFileViewSpec(str(video), kind="file")]]
    app._view_files_with_pager.assert_not_called()
    app.notify.assert_not_called()


async def test_mixed_selection_routes_all_files_in_order(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    notes = tmp_path / "notes.md"
    notes.write_text("# notes", encoding="utf-8")
    app = _make_app(str(image), str(notes))
    app._view_files_with_pager = MagicMock()  # type: ignore[method-assign]
    calls: list[list[ArtifactFileViewSpec]] = []

    def fake_viewer(specs) -> ArtifactFileViewerResult:
        calls.append(list(specs))
        return ArtifactFileViewerResult(True)

    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", fake_viewer)

    await app._process_view_input("1 2")

    assert calls == [
        [
            ArtifactFileViewSpec(str(image), kind="image"),
            ArtifactFileViewSpec(str(notes), kind="file"),
        ]
    ]
    app._view_files_with_pager.assert_not_called()


async def test_artifact_file_viewer_warning_is_surfaced(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))

    monkeypatch.setattr(
        "sase.ace.tui.graphics.view_artifact_files",
        lambda _specs: ArtifactFileViewerResult(False, warning="kitten missing"),
    )

    await app._process_view_input("1")

    app.notify.assert_called_once_with("kitten missing", severity="warning")


async def test_editor_suffix_bypasses_artifact_file_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._open_files_in_editor = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    await app._process_view_input("1@")

    app._open_files_in_editor.assert_called_once()
    result = app._open_files_in_editor.call_args.args[0]
    assert result.open_in_editor is True
    assert result.files == [str(image)]
    viewer.assert_not_called()


async def test_clipboard_suffix_bypasses_artifact_file_viewer(
    tmp_path: Path, monkeypatch
) -> None:
    image = tmp_path / "shot.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    app = _make_app(str(image))
    app._copy_files_to_clipboard = MagicMock()  # type: ignore[method-assign]

    viewer = MagicMock()
    monkeypatch.setattr("sase.ace.tui.graphics.view_artifact_files", viewer)

    await app._process_view_input("1%")

    app._copy_files_to_clipboard.assert_called_once_with([str(image)])
    viewer.assert_not_called()
