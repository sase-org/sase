"""ACE TUI PNG visual snapshots for the prompt Frontmatter Panel (Phase 3).

Pin how :class:`FrontmatterPanel` renders above the prompt stack in three states
the design calls out: a populated panel (scalar rows, the status chip, and the
read-only ``input`` / ``xprompts`` sub-trees), the just-triggered empty panel,
and an error state where a bad ``input`` type surfaces the core ``⟨! N⟩`` chip
plus the inline red diagnostic.  The bar is mounted directly over the ChangeSpecs
tab so the full ``styles.tcss`` styling applies exactly as it does at runtime.
"""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.input_item_modal import InputItemModal
from sase.ace.tui.modals.xprompt_item_modal import XPromptItemModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.xprompt.models import InputArg, InputType, XPrompt
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03

_POPULATED_PROMPT = (
    "---\n"
    "description: Refactor the auth module across services\n"
    "tags: refactor, backend\n"
    "input:\n"
    "  service: word\n"
    "  dry_run:\n"
    "    type: bool\n"
    "    default: false\n"
    "    description: skip writes\n"
    "xprompts:\n"
    "  _rules: Follow the team review checklist\n"
    "skill: false\n"
    "---\n"
    "Refactor the billing service end to end\n"
    "---\n"
    "Harden the missing-checkout failure path"
)

_ERROR_PROMPT = (
    "---\n"
    "description: Tidy the loader\n"
    "input:\n"
    "  retries:\n"
    "    type: int\n"
    "    default: notanumber\n"
    "    description: how many times to retry\n"
    "---\n"
    "First agent prompt body\n"
    "---\n"
    "Second agent prompt body"
)


async def _mount_prompt_bar(page: AcePage, initial_value: str) -> PromptInputBar:
    """Mount a prompt bar over the running app and wait for it to settle."""
    await page.app.mount(
        PromptInputBar(initial_value=initial_value, id="prompt-input-bar")
    )
    bar = page.app.query_one("#prompt-input-bar", PromptInputBar)
    await wait_for_visual_idle(page)
    return bar


async def test_frontmatter_panel_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _POPULATED_PROMPT)

        # Focus the panel so its accent border + selected row are pinned too.
        bar.focus_frontmatter_panel()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_populated_120x40",
            title="ACE frontmatter panel — populated",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_frontmatter_panel_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, "")

        # An empty prompt + g= shows the just-triggered empty-state guidance.
        bar.focus_frontmatter_panel()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_empty_120x40",
            title="ACE frontmatter panel — empty",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_frontmatter_panel_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")
        bar = await _mount_prompt_bar(page, _ERROR_PROMPT)

        # An invalid input type drives the ⟨! N⟩ chip + the inline red message.
        bar.focus_frontmatter_panel()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_error_120x40",
            title="ACE frontmatter panel — error state",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_frontmatter_input_item_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")

        # The structured ``input`` editor, prefilled from an existing input so
        # the type rule + the four fields are all pinned.
        modal = InputItemModal(
            existing=InputArg(
                name="retries",
                type=InputType.INT,
                default=3,
                description="how many times to retry",
            ),
            used_names=["service"],
        )
        page.app.push_screen(modal)
        await page.expect_modal("InputItemModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_input_item_modal_120x40",
            title="ACE frontmatter input item editor",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_frontmatter_xprompt_item_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.expect_state("tab", "changespecs")

        # The structured ``xprompts`` editor, prefilled with a local helper that
        # declares an input, so the compact inputs field is pinned too.
        modal = XPromptItemModal(
            existing=(
                "_rules",
                XPrompt(
                    name="_rules",
                    content="Follow the team review checklist",
                    inputs=[InputArg(name="service", type=InputType.WORD)],
                    description="team review rules",
                ),
            )
        )
        page.app.push_screen(modal)
        await page.expect_modal("XPromptItemModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_xprompt_item_modal_120x40",
            title="ACE frontmatter xprompt item editor",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
