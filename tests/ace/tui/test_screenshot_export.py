"""Tests for live TUI screenshot export request files."""

from __future__ import annotations

from pathlib import Path

from sase.ace.testing import AcePage
from sase.ace.tui.screenshot_export import (
    complete_export,
    fail_export,
    reserve_export_paths,
    screenshot_request_dir,
)


def test_screenshot_request_dir_sanitizes_tmux_names(tmp_path: Path) -> None:
    request_dir = screenshot_request_dir("agent/session", "sase tmux:1", root=tmp_path)

    assert request_dir.parent.parent == tmp_path
    assert "/" not in request_dir.relative_to(tmp_path).as_posix().split("/")[0]
    assert request_dir.name.startswith("sase_tmux_1-")


def test_export_protocol_writes_done_and_error_markers(tmp_path: Path) -> None:
    first = reserve_export_paths(tmp_path)

    assert first.sequence == 1
    assert first.pending.exists()
    complete_export(first, "<svg>ok</svg>")

    assert first.svg.read_text(encoding="utf-8") == "<svg>ok</svg>"
    assert first.done.read_text(encoding="utf-8") == "svg=screen_1.svg\n"
    assert not first.pending.exists()

    second = reserve_export_paths(tmp_path)
    fail_export(second, "boom")

    assert second.sequence == 2
    assert second.error.read_text(encoding="utf-8") == "boom\n"
    assert not second.pending.exists()


async def test_app_export_body_writes_svg_and_done(tmp_path: Path) -> None:
    async with AcePage() as page:
        paths = await page.app._run_screenshot_export(tmp_path)

    assert paths.sequence == 1
    assert paths.done.exists()
    assert not paths.error.exists()
    svg = paths.svg.read_text(encoding="utf-8")
    assert "<svg" in svg
    assert "rich-terminal" in svg


async def test_signal_schedule_spawns_export_task(tmp_path: Path) -> None:
    async with AcePage() as page:
        page.app._screenshot_export_request_dir = tmp_path
        page.app._schedule_screenshot_export_from_signal()
        await page.wait_for(lambda _state: (tmp_path / "screen_1.done").exists())

    assert (tmp_path / "screen_1.svg").exists()
