"""Tests for Agents-tab zoom panel file navigation."""

from __future__ import annotations

from typing import Any

from rich.text import Text

from sase.ace.tui.modals import ZoomPanelModal, ZoomPanelSeed, ZoomPanelTarget
from sase.ace.tui.modals.zoom_panel_modal import _renderable_to_text
from sase.ace.tui.widgets.file_panel import _LIVE_DIFF_SENTINEL

from tests.ace.tui._agents_zoom_panel_helpers import (
    _ModalTestApp,
    _RecordingZoomPanelModal,
    _collapsed_file_modal,
    _make_agent,
    _seeded_files_modal,
    _wait_for_file_content,
    _write_named_files,
)


async def test_completed_agent_zoom_loads_seeded_file_list_without_refresh(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")
    second_path = tmp_path / "second.md"
    second_path.write_text("second file body\n", encoding="utf-8")

    agent = _make_agent(
        status="DONE",
        extra_files=[str(first_path), str(second_path)],
    )
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(
            file_list=tuple(agent.all_files),
            has_file_content=True,
        ),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert panel._full_content == "first file body\n"
        assert str(first_path) in rendered


async def test_zoom_next_file_shows_next_seeded_file(tmp_path: Any) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")
    second_path = tmp_path / "second.md"
    second_path.write_text("second file body\n", encoding="utf-8")

    agent = _make_agent(
        status="DONE",
        extra_files=[str(first_path), str(second_path)],
    )
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(
            file_list=tuple(agent.all_files),
            has_file_content=True,
        ),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "first file body")

        await pilot.press("ctrl+n")
        rendered = await _wait_for_file_content(pilot, panel, "second file body")

        assert panel.current_file_index == 1
        assert panel._full_content == "second file body\n"
        assert str(second_path) in rendered


async def test_zoom_prev_file_shows_previous_seeded_file(tmp_path: Any) -> None:
    paths = _write_named_files(tmp_path, ["first", "second", "third"])
    modal = _seeded_files_modal(paths, file_index=1)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "second file body")

        await pilot.press("ctrl+p")
        rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert panel.current_file_index == 0
        assert panel._full_content == "first file body\n"
        assert paths[0] in rendered


async def test_zoom_prev_file_wraps_first_to_last(tmp_path: Any) -> None:
    paths = _write_named_files(tmp_path, ["first", "second", "third"])
    modal = _seeded_files_modal(paths, file_index=0)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "first file body")

        await pilot.press("ctrl+p")
        rendered = await _wait_for_file_content(pilot, panel, "third file body")

        assert panel.current_file_index == 2
        assert panel._full_content == "third file body\n"
        assert paths[2] in rendered


async def test_zoom_next_file_wraps_last_to_first(tmp_path: Any) -> None:
    paths = _write_named_files(tmp_path, ["first", "second", "third"])
    modal = _seeded_files_modal(paths, file_index=2)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "third file body")

        await pilot.press("ctrl+n")
        rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert panel.current_file_index == 0
        assert panel._full_content == "first file body\n"
        assert paths[0] in rendered


async def test_zoom_seeded_file_list_freezes_across_terminal_refresh(
    tmp_path: Any,
) -> None:
    raw_diff = tmp_path / "raw.diff"
    raw_diff.write_text("raw diff body\n", encoding="utf-8")
    first = tmp_path / "first.md"
    first.write_text("first file body\n", encoding="utf-8")
    second = tmp_path / "second.md"
    second.write_text("second file body\n", encoding="utf-8")
    seed_list = (_LIVE_DIFF_SENTINEL, str(first), str(second))

    agent = _make_agent(
        status="DONE",
        diff_path=str(raw_diff),
        extra_files=[str(first), str(second)],
    )
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(
            file_list=seed_list,
            file_index=2,
            has_file_content=True,
        ),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "second file body")

        assert panel.is_file_list_frozen
        assert panel.current_file_slots == seed_list
        assert panel.current_file_index == 2

        modal._refresh_active_panel(force=False)
        await pilot.pause()

        assert panel.current_file_slots == seed_list
        assert panel.current_file_index == 2


async def test_zoom_next_file_wrap_survives_refresh_tick(tmp_path: Any) -> None:
    paths = _write_named_files(tmp_path, ["first", "second", "third"])
    modal = _seeded_files_modal(paths, file_index=2)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        await _wait_for_file_content(pilot, panel, "third file body")

        modal._refresh_active_panel(force=False)
        await pilot.pause()
        await pilot.press("ctrl+n")
        rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert panel.current_file_index == 0
        assert paths[0] in rendered


async def test_zoom_file_rail_lists_files_and_tracks_active(
    tmp_path: Any,
) -> None:
    paths = _write_named_files(tmp_path, ["first", "second", "third"])
    modal = _seeded_files_modal(paths)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel, _ZoomFileRail

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        rail = modal.query_one("#zoom-file-rail", _ZoomFileRail)
        await _wait_for_file_content(pilot, panel, "first file body")

        plain = _renderable_to_text(rail.render()) or ""
        assert not rail.has_class("collapsed")
        assert "first.md" in plain
        assert "second.md" in plain
        assert "third.md" in plain
        assert "● file first.md" in plain

        await pilot.press("ctrl+n")
        await _wait_for_file_content(pilot, panel, "second file body")
        plain = _renderable_to_text(rail.render()) or ""

        assert "● file second.md" in plain


async def test_zoom_file_rail_collapses_for_single_file(tmp_path: Any) -> None:
    paths = _write_named_files(tmp_path, ["first"])
    modal = _seeded_files_modal(paths)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel, _ZoomFileRail

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        rail = modal.query_one("#zoom-file-rail", _ZoomFileRail)
        await _wait_for_file_content(pilot, panel, "first file body")

        assert rail.has_class("collapsed")


async def test_zoom_next_file_reveals_file_panel_from_metadata(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")

    agent = _make_agent(status="DONE", extra_files=[str(first_path)])
    modal = _collapsed_file_modal(agent)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        assert modal._target == ZoomPanelTarget.METADATA
        assert ZoomPanelTarget.FILE not in modal._available_targets()

        await pilot.press("ctrl+n")
        rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert modal._target == ZoomPanelTarget.FILE
        assert ZoomPanelTarget.FILE in modal._available_targets()
        assert panel._full_content == "first file body\n"
        assert str(first_path) in rendered


async def test_zoom_prev_file_reveals_file_panel_from_metadata(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")

    agent = _make_agent(status="DONE", extra_files=[str(first_path)])
    modal = _collapsed_file_modal(agent)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        assert modal._target == ZoomPanelTarget.METADATA

        await pilot.press("ctrl+p")
        rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert modal._target == ZoomPanelTarget.FILE
        assert ZoomPanelTarget.FILE in modal._available_targets()
        assert panel._full_content == "first file body\n"
        assert str(first_path) in rendered


async def test_zoom_revealed_file_panel_pages_after_first_press(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")
    second_path = tmp_path / "second.md"
    second_path.write_text("second file body\n", encoding="utf-8")

    agent = _make_agent(
        status="DONE",
        extra_files=[str(first_path), str(second_path)],
    )
    modal = _collapsed_file_modal(agent)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)

        await pilot.press("ctrl+n")
        first_rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert modal._target == ZoomPanelTarget.FILE
        assert panel.current_file_index == 0
        assert panel._full_content == "first file body\n"
        assert str(first_path) in first_rendered

        await pilot.press("ctrl+n")
        second_rendered = await _wait_for_file_content(
            pilot,
            panel,
            "second file body",
        )

        assert panel.current_file_index == 1
        assert panel._full_content == "second file body\n"
        assert str(second_path) in second_rendered


async def test_zoom_revealed_file_panel_reverse_pages_after_first_press(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")
    second_path = tmp_path / "second.md"
    second_path.write_text("second file body\n", encoding="utf-8")

    agent = _make_agent(
        status="DONE",
        extra_files=[str(first_path), str(second_path)],
    )
    modal = _collapsed_file_modal(agent)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        assert modal._target == ZoomPanelTarget.METADATA

        # First press only reveals the file panel; it must not skip a file.
        await pilot.press("ctrl+p")
        first_rendered = await _wait_for_file_content(pilot, panel, "first file body")

        assert modal._target == ZoomPanelTarget.FILE
        assert panel.current_file_index == 0
        assert panel._full_content == "first file body\n"
        assert str(first_path) in first_rendered

        # Second press reverse-pages, wrapping from the first file to the last.
        await pilot.press("ctrl+p")
        second_rendered = await _wait_for_file_content(
            pilot,
            panel,
            "second file body",
        )

        assert panel.current_file_index == 1
        assert panel._full_content == "second file body\n"
        assert str(second_path) in second_rendered


async def test_zoom_ctrl_p_returns_to_metadata_after_reveal_single_file(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")

    agent = _make_agent(status="DONE", extra_files=[str(first_path)])
    modal = _collapsed_file_modal(agent)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        assert modal._target == ZoomPanelTarget.METADATA

        # Ctrl-N reveals and populates the single file panel.
        await pilot.press("ctrl+n")
        await _wait_for_file_content(pilot, panel, "first file body")

        assert modal._target == ZoomPanelTarget.FILE
        assert not modal.query_one("#zoom-file-view").has_class("hidden")

        # Ctrl-P immediately after must undo the reveal and return to metadata,
        # not "page" the lone file (which would leave the UI stuck).
        await pilot.press("ctrl+p")
        await pilot.pause()

        assert modal._target == ZoomPanelTarget.METADATA
        assert modal.query_one("#zoom-file-view").has_class("hidden")
        assert not modal.query_one("#zoom-metadata-scroll").has_class("hidden")


async def test_zoom_same_direction_paging_survives_reveal_undo(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")
    second_path = tmp_path / "second.md"
    second_path.write_text("second file body\n", encoding="utf-8")

    agent = _make_agent(
        status="DONE",
        extra_files=[str(first_path), str(second_path)],
    )
    modal = _collapsed_file_modal(agent)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)

        # First Ctrl-N reveals the first file.
        await pilot.press("ctrl+n")
        await _wait_for_file_content(pilot, panel, "first file body")
        assert panel.current_file_index == 0

        # Second Ctrl-N (same direction) must still page to the second file.
        await pilot.press("ctrl+n")
        await _wait_for_file_content(pilot, panel, "second file body")

        assert modal._target == ZoomPanelTarget.FILE
        assert panel.current_file_index == 1


async def test_zoom_ctrl_n_returns_to_metadata_after_prev_reveal(
    tmp_path: Any,
) -> None:
    first_path = tmp_path / "first.md"
    first_path.write_text("first file body\n", encoding="utf-8")

    agent = _make_agent(status="DONE", extra_files=[str(first_path)])
    modal = _collapsed_file_modal(agent)

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        assert modal._target == ZoomPanelTarget.METADATA

        # Ctrl-P reveals the file panel.
        await pilot.press("ctrl+p")
        await _wait_for_file_content(pilot, panel, "first file body")
        assert modal._target == ZoomPanelTarget.FILE

        # The opposite key (Ctrl-N) immediately after must restore metadata.
        await pilot.press("ctrl+n")
        await pilot.pause()

        assert modal._target == ZoomPanelTarget.METADATA
        assert modal.query_one("#zoom-file-view").has_class("hidden")


async def test_zoom_next_file_warns_when_metadata_agent_has_no_files() -> None:
    agent = _make_agent(status="DONE")
    modal = _RecordingZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.METADATA,
        seed=ZoomPanelSeed(metadata_renderable=Text("seed metadata")),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("ctrl+n")
        await pilot.pause()

        assert modal._target == ZoomPanelTarget.METADATA
        assert modal.query_one("#zoom-file-view").has_class("hidden")
        assert modal.notifications == [("No files for this agent", "warning")]


async def test_zoom_file_full_content_survives_periodic_refresh(tmp_path: Any) -> None:
    content = "\n".join(f"line {i}" for i in range(200)) + "\n"
    file_path = tmp_path / "notes.md"
    file_path.write_text(content, encoding="utf-8")

    agent = _make_agent(status="DONE", extra_files=[str(file_path)])
    modal = ZoomPanelModal(
        agent_provider=lambda: agent,
        initial_agent=agent,
        initial_target=ZoomPanelTarget.FILE,
        seed=ZoomPanelSeed(has_file_content=True),
        refresh_interval=10,
    )

    async with _ModalTestApp().run_test(size=(120, 40)) as pilot:
        pilot.app.push_screen(modal)
        await pilot.pause()
        await pilot.pause()

        from sase.ace.tui.modals.zoom_panel_modal import _ZoomFilePanel

        panel = modal.query_one("#zoom-file-panel", _ZoomFilePanel)
        assert panel._total_line_count == 200
        assert panel._visible_line_count == 200
        assert not panel._is_content_capped

        # A periodic refresh tick keeps the complete body rendered.
        modal._refresh_active_panel(force=False)
        await pilot.pause()
        await pilot.pause()
        assert panel._visible_line_count == 200
        assert not panel._is_content_capped
