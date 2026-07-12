"""Tests for Vim-style search in the Agents-tab zoom panel."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from sase.ace.tui.modals import ZoomPanelModal, ZoomPanelSeed, ZoomPanelTarget
from sase.ace.tui.modals.zoom_panel_modal import _renderable_to_text
from sase.ace.tui.modals.zoom_panel_search import (
    _line_start_offsets,
    _offset_for_row,
    _offset_to_row_col,
)

from tests.ace.tui._agents_zoom_panel_helpers import (
    _ModalTestApp,
    _RecordingZoomPanelModal,
    _make_agent,
    _seeded_files_modal,
    _wait_for_file_content,
)


def _metadata_modal(text: str) -> ZoomPanelModal:
    agent = _make_agent(status="DONE")
    return ZoomPanelModal(
        agent_provider=lambda: None,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.METADATA,
        seed=ZoomPanelSeed(metadata_renderable=Text(text)),
        refresh_interval=10,
    )


def _search_command(modal: ZoomPanelModal) -> Static:
    return modal.query_one("#zoom-search-command", Static)


def _search_scroll(modal: ZoomPanelModal) -> VerticalScroll:
    return modal.query_one("#zoom-search-scroll", VerticalScroll)


def test_zoom_search_offset_helpers_map_logical_lines() -> None:
    starts = _line_start_offsets("alpha\nbeta\ngamma")

    assert starts == (0, 6, 11)
    assert _offset_to_row_col(starts, 0) == (0, 0)
    assert _offset_to_row_col(starts, 6) == (1, 0)
    assert _offset_to_row_col(starts, 10) == (1, 4)
    assert _offset_for_row(starts, 2) == 11
    assert _offset_for_row(starts, 200) == 11


async def test_zoom_search_entry_captures_zoom_shortcut_keys() -> None:
    modal = _metadata_modal("alpha beta")

    async with _ModalTestApp().run_test(size=(100, 30)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("slash", "q", "backspace", "a")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ZoomPanelModal)
        assert modal._zoom_search_mode == "typing"
        assert modal._zoom_search_direction == "forward"
        assert modal._zoom_search_query == "a"
        assert not _search_command(modal).has_class("hidden")

        await pilot.press("escape")
        await pilot.press("question_mark")
        await pilot.pause()

        assert isinstance(pilot.app.screen, ZoomPanelModal)
        assert modal._zoom_search_mode == "typing"
        assert modal._zoom_search_direction == "reverse"


async def test_zoom_search_incsearch_cancel_and_refresh_timer_resume() -> None:
    class FakeTimer:
        def __init__(self) -> None:
            self.pause_count = 0
            self.resume_count = 0

        def pause(self) -> None:
            self.pause_count += 1

        def resume(self) -> None:
            self.resume_count += 1

        def stop(self) -> None:
            pass

    modal = _metadata_modal("top\nmiddle needle\nbottom needle")
    timer = FakeTimer()

    async with _ModalTestApp().run_test(size=(100, 30)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        modal._refresh_timer = timer  # type: ignore[assignment]

        await pilot.press("slash", "n", "e", "e", "d", "l", "e")
        await pilot.pause()

        assert timer.pause_count == 1
        assert modal._zoom_search_current_selection is not None
        assert modal._zoom_search_current_selection.index == 0
        assert "[1/2]" in _search_command(modal).render().plain
        assert not _search_scroll(modal).has_class("hidden")
        assert modal.query_one("#zoom-metadata-scroll").has_class("hidden")

        await pilot.press("escape")
        await pilot.pause()

        assert modal._zoom_search_mode == "off"
        assert timer.resume_count == 1
        assert _search_scroll(modal).has_class("hidden")
        assert not modal.query_one("#zoom-metadata-scroll").has_class("hidden")


async def test_zoom_search_no_match_readout_restores_origin() -> None:
    modal = _metadata_modal("alpha beta")

    async with _ModalTestApp().run_test(size=(100, 30)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("slash", "z", "z", "z")
        await pilot.pause()

        assert modal._zoom_search_current_selection is None
        assert "pattern not found" in _search_command(modal).render().plain
        assert int(_search_scroll(modal).scroll_y) == 0


async def test_zoom_search_commit_repeat_and_wrap_feedback() -> None:
    modal = _RecordingZoomPanelModal(
        agent_provider=lambda: None,
        initial_agent=_make_agent(status="DONE"),
        initial_target=ZoomPanelTarget.METADATA,
        seed=ZoomPanelSeed(metadata_renderable=Text("alpha beta alpha beta alpha")),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(100, 30)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("slash", "a", "l", "p", "h", "a", "enter")
        await pilot.pause()

        assert modal._zoom_search_mode == "committed"
        assert modal._last_zoom_search == ("alpha", "forward")
        assert "[1/3]" in _search_command(modal).render().plain

        await pilot.press("n")
        await pilot.pause()
        assert modal._zoom_search_current_selection is not None
        assert modal._zoom_search_current_selection.index == 1
        assert "[2/3]" in _search_command(modal).render().plain

        await pilot.press("n", "n")
        await pilot.pause()
        assert modal._zoom_search_current_selection is not None
        assert modal._zoom_search_current_selection.index == 0
        assert modal.notifications[-1] == (
            "search hit BOTTOM, continuing at TOP",
            "information",
        )

        await pilot.press("N")
        await pilot.pause()
        assert modal._zoom_search_current_selection is not None
        assert modal._zoom_search_current_selection.index == 2
        assert modal.notifications[-1] == (
            "search hit TOP, continuing at BOTTOM",
            "information",
        )


async def test_zoom_search_uses_full_static_file_content(
    tmp_path: Any,
) -> None:
    content = "\n".join(f"line {index}" for index in range(160))
    content += "\nneedle below trim\n"
    path = tmp_path / "large.md"
    path.write_text(content, encoding="utf-8")
    modal = _seeded_files_modal([str(path)])

    async with _ModalTestApp().run_test(size=(90, 16)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "line 0")
        assert panel._visible_line_count == panel._total_line_count
        assert "needle below trim" in (_renderable_to_text(panel.content) or "")

        await pilot.press("slash", "n", "e", "e", "d", "l", "e")
        await pilot.pause()

        assert "needle below trim" in modal._zoom_search_corpus
        assert modal._zoom_search_current_selection is not None


async def test_zoom_search_structural_key_exits_and_then_pages_file(
    tmp_path: Any,
) -> None:
    first = tmp_path / "first.md"
    first.write_text("first alpha\n", encoding="utf-8")
    second = tmp_path / "second.md"
    second.write_text("second beta\n", encoding="utf-8")
    modal = _seeded_files_modal([str(first), str(second)])

    async with _ModalTestApp().run_test(size=(100, 30)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "first alpha")

        await pilot.press("slash", "f", "i", "r", "s", "t", "enter")
        await pilot.pause()
        assert modal._zoom_search_mode == "committed"
        assert modal.query_one("#zoom-file-view").has_class("hidden")

        await pilot.press("ctrl+n")
        await _wait_for_file_content(pilot, panel, "second beta")

        assert modal._zoom_search_mode == "off"
        assert panel.current_file_index == 1
        assert _search_scroll(modal).has_class("hidden")
        assert not modal.query_one("#zoom-file-view").has_class("hidden")


async def test_zoom_search_empty_file_panel_notifies_without_state_change() -> None:
    modal = _RecordingZoomPanelModal(
        agent_provider=lambda: None,
        initial_agent=_make_agent(status="DONE"),
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(has_file_content=True),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(100, 30)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("slash")
        await pilot.pause()

        assert modal._zoom_search_mode == "off"
        assert _search_scroll(modal).has_class("hidden")
        assert modal.notifications == [("Nothing to search", "information")]
