"""ACE TUI PNG visual snapshots for prompt syntax and annotation highlights."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import (
    CODEBLOCK_HIGHLIGHT_SOLO,
    CODEBLOCK_HIGHLIGHT_STACK,
    SEARCH_PROMPT,
    TODO_HIGHLIGHT_STACK,
    TODO_RESTORED_PROMPT,
    XPROMPT_HIGHLIGHT_SOLO,
    XPROMPT_HIGHLIGHT_STACK,
    mount_prompt_bar,
    patch_visual_skill_catalog,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_todo_restored_dark_120x40",
            "ACE restored prompt TODO annotations — dark theme",
        ),
        (
            "textual-light",
            "prompt_todo_restored_light_120x40",
            "ACE restored prompt TODO annotations — light theme",
        ),
    ],
)
async def test_prompt_todo_restored_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await mount_prompt_bar(page, TODO_RESTORED_PROMPT)

        assert "TODO 5" in str(bar.border_title)
        assert bar.active_text_area().cursor_location[0] == 32
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_prompt_todo_stack_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await mount_prompt_bar(page, TODO_HIGHLIGHT_STACK)

        assert "TODO 3" in str(bar.border_title)
        assert bar._stack.selected_index == 1
        assert (
            bar.query_one(".prompt-pane.inactive", PromptTextArea).todo_annotation_count
            == 2
        )
        ace_png_visual.assert_page_png(
            page,
            "prompt_todo_stack_120x40",
            title="ACE prompt TODO annotations — inactive pane count",
        )


async def test_prompt_search_highlight_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await mount_prompt_bar(page, SEARCH_PROMPT)

        await page.press("escape", "slash", "a", "l", "p", "h", "a")
        text_area = bar.active_text_area()
        await wait_for_state(
            page,
            lambda: (
                text_area._search_active
                and text_area._search_query == "alpha"
                and bar._search_command_visible
            ),
            description="active alpha prompt search and highlights",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_search_highlight_120x40",
            title="ACE prompt input - active search highlight",
        )


async def test_prompt_xprompt_highlight_solo_light_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_skill_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        page.app.theme = "textual-light"
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await mount_prompt_bar(page, XPROMPT_HIGHLIGHT_SOLO)

        ace_png_visual.assert_page_png(
            page,
            "prompt_xprompt_highlight_solo_light_120x40",
            title="ACE prompt input — xprompt highlighting, light theme",
        )


async def test_prompt_xprompt_highlight_stack_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    patch_visual_skill_catalog(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await mount_prompt_bar(page, XPROMPT_HIGHLIGHT_STACK)

        ace_png_visual.assert_page_png(
            page,
            "prompt_xprompt_highlight_stack_120x40",
            title="ACE prompt stack — xprompt highlighting",
        )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_codeblock_highlight_solo_dark_120x40",
            "ACE prompt input — code highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_codeblock_highlight_solo_light_120x40",
            "ACE prompt input — code highlighting, light theme",
        ),
    ],
)
async def test_prompt_codeblock_highlight_solo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await mount_prompt_bar(page, CODEBLOCK_HIGHLIGHT_SOLO)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_codeblock_highlight_stack_dark_120x40",
            "ACE prompt stack — code highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_codeblock_highlight_stack_light_120x40",
            "ACE prompt stack — code highlighting, light theme",
        ),
    ],
)
async def test_prompt_codeblock_highlight_stack_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        startup_policy="real",
    ) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await mount_prompt_bar(page, CODEBLOCK_HIGHLIGHT_STACK)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
