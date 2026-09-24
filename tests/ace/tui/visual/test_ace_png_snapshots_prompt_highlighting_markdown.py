"""sase's TUI PNG visual snapshots for prompt markdown highlighting."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import mount_prompt_bar
from tests.ace.tui.visual._ace_prompt_png_snapshot_prompts import (
    BULLET_HIGHLIGHT_SOLO,
    CODEBLOCK_HIGHLIGHT_SOLO,
    CODEBLOCK_HIGHLIGHT_STACK,
    ORDERED_HIGHLIGHT_SOLO,
    TODO_HIGHLIGHT_STACK,
    TODO_RESTORED_PROMPT,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

PLACEHOLDER_RAW_ONLY_PROMPT = (
    "Fill <service> before launch\n"
    "Keep `<literal>` as documentation\n"
    "```text\n"
    "<code> stays literal too\n"
    "```"
)


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

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TODO_RESTORED_PROMPT)

        assert "TODO 4" in str(bar.border_title)
        assert bar.active_text_area().cursor_location[0] == 32
        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_prompt_todo_stack_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, TODO_HIGHLIGHT_STACK)

        assert "TODO 2" in str(bar.border_title)
        assert bar._stack.selected_index == 1
        assert (
            bar.query_one(".prompt-pane.inactive", PromptTextArea).todo_annotation_count
            == 1
        )
        ace_png_visual.assert_page_png(
            page,
            "prompt_todo_stack_120x40",
            title="ACE prompt TODO annotations — inactive pane count",
        )


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_bullet_highlight_solo_dark_120x40",
            "ACE prompt input — bullet-dash highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_bullet_highlight_solo_light_120x40",
            "ACE prompt input — bullet-dash highlighting, light theme",
        ),
    ],
)
async def test_prompt_bullet_highlight_solo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, BULLET_HIGHLIGHT_SOLO)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


@pytest.mark.parametrize(
    ("theme", "snapshot_name", "title"),
    [
        (
            "textual-dark",
            "prompt_ordered_highlight_solo_dark_120x40",
            "ACE prompt input — ordered-marker highlighting, dark theme",
        ),
        (
            "textual-light",
            "prompt_ordered_highlight_solo_light_120x40",
            "ACE prompt input — ordered-marker highlighting, light theme",
        ),
    ],
)
async def test_prompt_ordered_highlight_solo_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
    snapshot_name: str,
    title: str,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, ORDERED_HIGHLIGHT_SOLO)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)


async def test_prompt_placeholder_raw_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, PLACEHOLDER_RAW_ONLY_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "placeholder_raw_only_highlight_120x40",
            title="ACE prompt input - raw placeholder highlighting",
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
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

    async with AcePage(query='"visual"', patches=patches()) as page:
        page.app.theme = theme
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("patches"))
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        await mount_prompt_bar(page, CODEBLOCK_HIGHLIGHT_STACK)

        ace_png_visual.assert_page_png(page, snapshot_name, title=title)
