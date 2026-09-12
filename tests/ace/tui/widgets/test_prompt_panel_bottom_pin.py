"""Mounted metadata bottom-follow behavior for the prompt panel."""

from __future__ import annotations

import pytest
from rich.console import Group
from rich.text import Text
from textual.containers import VerticalScroll

from sase.ace.testing.wait import wait_for
from sase.ace.tui.widgets.prompt_panel import AgentPromptPanel
from tests.ace.tui.widgets._prompt_panel_section_navigation_helpers import (
    _MetadataNavigationApp,
    section,
)


def _document(label: str, lines: int) -> Text:
    text = Text(f"{label}\n")
    for index in range(lines):
        text.append(f"{label} line {index}\n")
    return text


def _section_document(*, extra_middle_lines: int = 0) -> Group:
    return Group(
        Text("Name: demo-agent\nStatus: RUNNING\nUnmarked preamble\n"),
        section("ONE", "one\n" * 8),
        section("TWO", "two\n" * (8 + extra_middle_lines)),
        section("THREE", "short final body\n"),
    )


async def _mount_document(
    pilot: object,
    app: _MetadataNavigationApp,
    content: object,
    *,
    identity: str = "document",
) -> tuple[AgentPromptPanel, VerticalScroll]:
    panel = app.query_one("#agent-prompt-panel", AgentPromptPanel)
    scroll = app.query_one("#agent-prompt-scroll", VerticalScroll)
    panel.prepare_section_document(identity)
    panel.update(content)
    await wait_for(pilot, lambda: int(scroll.max_scroll_y) > 0)
    return panel, scroll


async def _press_bottom(
    pilot: object,
    panel: AgentPromptPanel,
    scroll: VerticalScroll,
) -> None:
    await pilot.press("G")  # type: ignore[attr-defined]
    await wait_for(
        pilot,
        lambda: (
            panel.is_pinned_to_bottom
            and int(scroll.scroll_y) == panel.bottom_scroll_target(scroll)
        ),
    )


async def test_growth_keeps_view_at_end() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel, scroll = await _mount_document(pilot, app, _document("base", 20))
        await _press_bottom(pilot, panel, scroll)
        previous_target = panel.bottom_scroll_target(scroll)

        panel.update(_document("grown", 34))

        await wait_for(
            pilot,
            lambda: (
                panel.bottom_scroll_target(scroll) > previous_target
                and int(scroll.scroll_y) == panel.bottom_scroll_target(scroll)
            ),
        )


async def test_shrink_then_regrow_does_not_strand_viewport() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel, scroll = await _mount_document(pilot, app, _document("base", 34))
        await _press_bottom(pilot, panel, scroll)

        panel.update(_document("short", 1))
        await wait_for(
            pilot,
            lambda: (
                panel.is_pinned_to_bottom
                and int(scroll.max_scroll_y) == 0
                and int(scroll.scroll_y) == 0
            ),
        )

        panel.update(_document("regrown", 34))
        await wait_for(
            pilot,
            lambda: (
                int(scroll.max_scroll_y) > 0
                and int(scroll.scroll_y) == panel.bottom_scroll_target(scroll)
            ),
        )


async def test_unchanged_document_does_no_pin_work() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        content = _document("same", 24)
        panel, _scroll = await _mount_document(pilot, app, content)
        await _press_bottom(pilot, panel, _scroll)
        generation = panel._section_generation  # noqa: SLF001
        assert panel._bottom_pin_reapply_scheduled is False  # noqa: SLF001

        panel.update(content)

        assert panel._section_generation == generation  # noqa: SLF001
        assert panel._bottom_pin_reapply_scheduled is False  # noqa: SLF001


async def test_scroll_to_top_releases_pin() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel, scroll = await _mount_document(pilot, app, _document("base", 24))
        await _press_bottom(pilot, panel, scroll)

        await pilot.press("g")
        await wait_for(
            pilot,
            lambda: not panel.is_pinned_to_bottom and int(scroll.scroll_y) == 0,
        )

        previous_target = panel.bottom_scroll_target(scroll)
        panel.update(_document("grown", 38))
        await wait_for(
            pilot, lambda: panel.bottom_scroll_target(scroll) > previous_target
        )
        assert int(scroll.scroll_y) == 0


@pytest.mark.parametrize("key", ["ctrl+u", "ctrl+d", "ctrl+f", "ctrl+b"])
async def test_relative_scrolls_release_pin(key: str) -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel, scroll = await _mount_document(pilot, app, _document("base", 28))
        await _press_bottom(pilot, panel, scroll)
        previous_target = panel.bottom_scroll_target(scroll)

        await pilot.press(key)
        await wait_for(pilot, lambda: not panel.is_pinned_to_bottom)
        await pilot.pause()
        released_y = int(scroll.scroll_y)

        panel.update(_document("grown", 42))
        await wait_for(
            pilot, lambda: panel.bottom_scroll_target(scroll) > previous_target
        )
        assert int(scroll.scroll_y) == released_y
        assert released_y != panel.bottom_scroll_target(scroll)


async def test_direct_container_scroll_releases_pin() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel, scroll = await _mount_document(pilot, app, _document("base", 28))
        await _press_bottom(pilot, panel, scroll)

        scroll.scroll_to(y=0, animate=False, immediate=True)
        panel.update(_document("grown", 42))

        await wait_for(pilot, lambda: not panel.is_pinned_to_bottom)
        assert int(scroll.scroll_y) == 0


async def test_clamp_does_not_release_pin() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel, scroll = await _mount_document(pilot, app, _document("base", 28))
        await _press_bottom(pilot, panel, scroll)

        panel.update(_document("short", 1))

        await wait_for(
            pilot,
            lambda: (
                panel.is_pinned_to_bottom
                and int(scroll.max_scroll_y) == 0
                and int(scroll.scroll_y) == 0
            ),
        )


async def test_new_document_releases_pin() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel, scroll = await _mount_document(pilot, app, _document("base", 28))
        await _press_bottom(pilot, panel, scroll)

        panel.prepare_section_document("other")
        panel.update(_document("other", 1))

        await wait_for(
            pilot,
            lambda: not panel.is_pinned_to_bottom and int(scroll.scroll_y) == 0,
        )


async def test_pin_respects_section_reserve() -> None:
    app = _MetadataNavigationApp()
    async with app.run_test(size=(50, 16)) as pilot:
        panel, scroll = await _mount_document(
            pilot,
            app,
            _section_document(),
            identity="sections",
        )
        await pilot.press("ctrl+j")
        await wait_for(pilot, lambda: panel.section_layout_reserve > 0)

        await _press_bottom(pilot, panel, scroll)
        panel.update(_section_document(extra_middle_lines=10))

        await wait_for(
            pilot,
            lambda: (
                panel.section_layout_reserve > 0
                and int(scroll.scroll_y) == panel.bottom_scroll_target(scroll)
            ),
        )
        assert (
            int(scroll.scroll_y)
            == int(scroll.max_scroll_y) - panel.section_layout_reserve
        )
        assert int(scroll.scroll_y) < int(scroll.max_scroll_y)
