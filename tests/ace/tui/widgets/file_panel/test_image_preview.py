from __future__ import annotations

import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from rich.console import Console
from rich.console import Group
from rich.text import Text

from sase.ace.tui.widgets.file_panel import AgentFilePanel


def _make_file_panel() -> MagicMock:
    panel = MagicMock()
    panel.post_message = MagicMock()
    panel._has_displayed_content = False
    panel._file_list = []
    panel._current_file_index = 0
    panel._total_line_count = 0
    panel._visible_line_count = 0
    panel._is_content_capped = False
    panel._full_content = "old"
    panel._full_content_lexer = "text"
    panel._content_mode = "none"
    panel._static_header_path = None
    panel._current_image_renderable = None
    panel._post_file_visibility = types.MethodType(
        AgentFilePanel._post_file_visibility, panel
    )
    panel._post_line_count_changed = MagicMock()
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
    panel._display_static_video = types.MethodType(
        AgentFilePanel._display_static_video, panel
    )
    panel._update_body = types.MethodType(AgentFilePanel._update_body, panel)
    # Async-static-read state used by display_static_file.
    panel._static_request_id = 0
    panel._static_worker = None
    panel._cancel_static_worker = types.MethodType(
        AgentFilePanel._cancel_static_worker, panel
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


def test_agent_file_panel_uses_video_placeholder_before_text_read(
    tmp_path: Path,
) -> None:
    video = tmp_path / "render.mp4"
    video.write_bytes(b"video")
    panel = _make_file_panel()
    panel.run_worker = MagicMock()

    AgentFilePanel.display_static_file(panel, str(video))

    panel.run_worker.assert_not_called()
    assert panel._content_mode == "video"
    assert panel._static_header_path == str(video)
    assert panel._full_content is None
    panel.post_message.assert_called()
    assert panel.post_message.call_args[0][0].has_file is True
    group = panel.update.call_args[0][0]
    assert isinstance(group, Group)
    console = Console(record=True, width=100, color_system=None)
    console.print(group)
    output = console.export_text()
    assert "▶ video" in output
    assert "render.mp4" in output
    assert "use the view key to play" in output


def test_agent_file_panel_image_size_uses_scroll_viewport() -> None:
    panel = MagicMock()
    scroll = SimpleNamespace(
        scrollable_content_region=SimpleNamespace(width=31, height=11)
    )
    panel._get_scroll_container = MagicMock(return_value=scroll)

    assert AgentFilePanel._image_preview_size(panel) == (31, 9)
