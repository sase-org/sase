"""Mounted prompt panel section navigation actions."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.containers import VerticalScroll

from sase.ace.testing.wait import wait_for
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    _MetadataNavigationApp,
    section,
)


async def test_mounted_actions_cycle_through_top_and_align_every_title() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        scroll = app.query_one("#agent-prompt-scroll", VerticalScroll)
        content = Group(
            Text("Name: demo-agent\nStatus: DONE\nUnmarked preamble\n"),
            section("ONE", "one\n" * 8),
            section("TWO", "two\n" * 8),
            section("THREE", "short final body\n"),
        )
        panel.prepare_section_document("forward")
        panel.update(content)
        await pilot.pause()

        anchors = {anchor.identity: anchor.row for anchor in panel._section_anchors}  # noqa: SLF001
        assert anchors["one"] > 0
        for expected in ("one", "two", "three"):
            await pilot.press("ctrl+j")
            await pilot.pause()
            assert panel.active_section_identity == expected
            assert int(scroll.scroll_y) == panel.virtual_region.y + anchors[expected]
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert panel.active_section_identity is None
        assert int(scroll.scroll_y) == 0
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert panel.active_section_identity == "one"
        assert int(scroll.scroll_y) == panel.virtual_region.y + anchors["one"]

        panel.prepare_section_document("reverse")
        panel.update(content)
        await pilot.pause()
        for expected in ("three", "two", "one"):
            await pilot.press("ctrl+k")
            await pilot.pause()
            assert panel.active_section_identity == expected
            assert int(scroll.scroll_y) == panel.virtual_region.y + anchors[expected]
        await pilot.press("ctrl+k")
        await pilot.pause()
        assert panel.active_section_identity is None
        assert int(scroll.scroll_y) == 0
        await pilot.press("ctrl+k")
        await pilot.pause()
        assert panel.active_section_identity == "three"
        assert int(scroll.scroll_y) == panel.virtual_region.y + anchors["three"]

        # The trailing reserve makes the final title alignable, but ordinary
        # bottom scrolling still stops at the end of real metadata.
        assert (
            int(scroll.scroll_y)
            > int(scroll.max_scroll_y) - panel.section_layout_reserve
        )
        await pilot.press("G")
        await pilot.pause()
        assert int(scroll.scroll_y) == panel.bottom_scroll_target(scroll)


async def test_zero_sections_noop_and_reflow_preserves_active_identity() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(60, 18)) as pilot:
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        scroll = app.query_one("#agent-prompt-scroll", VerticalScroll)
        panel.prepare_section_document("empty")
        panel.update(Text("No marked titles\n" * 20))
        await pilot.pause()
        initial_scroll = scroll.scroll_y
        await pilot.press("ctrl+j", "ctrl+k")
        await pilot.pause()
        assert panel.active_section_identity is None
        assert scroll.scroll_y == initial_scroll

        panel.prepare_section_document("reflow")
        panel.update(
            Group(
                section("FIRST", "wrapped words " * 20),
                section("SECOND", "tail\n"),
            )
        )
        await pilot.pause()
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert panel.active_section_identity == "first"

        old_second_row = panel._section_anchors[-1].row  # noqa: SLF001
        await pilot.resize_terminal(34, 18)
        await wait_for(
            pilot,
            lambda: panel._section_anchors[-1].row > old_second_row,  # noqa: SLF001
        )
        assert panel.active_section_identity == "first"
        await pilot.press("ctrl+j")
        await pilot.pause()
        assert panel.active_section_identity == "second"
        assert int(scroll.scroll_y) == (
            panel.virtual_region.y + panel._section_anchors[-1].row  # noqa: SLF001
        )


async def test_key_during_layout_invalidation_gets_one_after_refresh_retry() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
        panel.prepare_section_document("retry")
        panel.update(Group(section("FIRST", "body\n"), section("LAST", "tail\n")))

        app.action_next_agent_metadata_section()
        assert panel.active_section_identity is None
        await pilot.pause()

        assert panel.active_section_identity == "first"
        assert app._agent_metadata_section_retry_scheduled is False  # noqa: SLF001

        await pilot.press("ctrl+j")
        await pilot.pause()
        assert panel.active_section_identity == "last"

        panel.update(
            Group(
                section("FIRST", "body now wraps " * 8 + "\n"),
                section("LAST", "tail\n"),
            )
        )
        app.action_next_agent_metadata_section()
        assert panel.active_section_identity == "last"
        await pilot.pause()

        assert panel.active_section_identity is None
        assert app._agent_metadata_section_retry_scheduled is False  # noqa: SLF001
