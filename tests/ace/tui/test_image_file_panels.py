from __future__ import annotations

import json
import types
from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console, Group
from rich.text import Text

from sase.ace.tui.graphics import ImageFallbackRenderable
from sase.ace.tui.modals.notification_modal import NotificationModal
from sase.ace.tui.models._loaders._done_loaders import _load_done_agent_for_dir
from sase.ace.tui.widgets.file_panel import AgentFilePanel
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
    panel._graphics_capability = types.MethodType(
        AgentFilePanel._graphics_capability, panel
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

    def fake_image_preview(path, _capability, *, columns, rows):
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
    calls: list[str] = []

    def fake_query_one(selector, _type=None):
        if selector == "#notification-file-title":
            return title
        if selector == "#notification-file-content":
            return content
        if selector == "#notification-file-scroll":
            return scroll
        raise AssertionError(selector)

    def fake_image_preview(path, _capability, *, columns, rows):
        calls.append(path)
        assert (columns, rows) == (40, 12)
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


def test_image_fallback_mentions_editor_actions(tmp_path: Path) -> None:
    image = tmp_path / "fallback.jpg"
    image.write_bytes(b"jpeg")
    renderable = ImageFallbackRenderable(str(image), "no graphics")

    console = Console(record=True, width=100)
    console.print(renderable)

    fallback_text = console.export_text()
    assert "Open with e in notifications" in fallback_text
    assert "%E in agent panels" in fallback_text
