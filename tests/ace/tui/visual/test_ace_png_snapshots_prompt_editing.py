"""ACE TUI PNG visual snapshots for prompt editor states."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.xprompt import jinja_inspect
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import (
    CURSOR_PROMPT,
    JINJA_INVALID_PROMPT,
    JINJA_VALID_PROMPT,
    compute_jinja_now,
    mount_prompt_bar,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_prompt_vim_cursor_insert_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, CURSOR_PROMPT)
        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 9)
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "insert"
                and text_area.cursor_location == (0, 9)
                and text_area.has_focus
            ),
            description="INSERT-mode prompt cursor at fixture location",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_vim_cursor_insert_120x40",
            title="ACE prompt input - INSERT cursor",
        )


async def test_prompt_vim_cursor_normal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, CURSOR_PROMPT)
        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 9)
        text_area._enter_normal_mode()
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "normal"
                and text_area.cursor_location == (0, 9)
                and text_area.has_focus
            ),
            description="NORMAL-mode prompt cursor at fixture location",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_vim_cursor_normal_120x40",
            title="ACE prompt input - NORMAL cursor",
        )


async def test_prompt_vim_cursor_visual_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, CURSOR_PROMPT)
        text_area = bar.active_text_area()
        text_area.cursor_location = (0, 9)
        text_area._enter_visual_mode("charwise")
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "visual"
                and text_area._visual_cursor == (0, 9)
                and text_area.has_focus
            ),
            description="VISUAL-mode prompt cursor at fixture location",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_vim_cursor_visual_120x40",
            title="ACE prompt input - VISUAL cursor",
        )


async def test_prompt_jinja_valid_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(jinja_inspect, "known_toplevel_context", lambda: {"root"})

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, JINJA_VALID_PROMPT)
        compute_jinja_now(bar.active_text_area())
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_jinja_valid_120x40",
            title="ACE prompt input — Jinja valid state",
        )


async def test_prompt_jinja_invalid_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(jinja_inspect, "known_toplevel_context", lambda: {"root"})

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await mount_prompt_bar(page, JINJA_INVALID_PROMPT)
        compute_jinja_now(bar.active_text_area())
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_jinja_invalid_120x40",
            title="ACE prompt input — Jinja invalid state",
        )
