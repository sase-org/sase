"""ACE TUI PNG visual snapshots for the prompt Frontmatter Panel (Phase 3).

Pin how :class:`FrontmatterPanel` renders above the prompt stack in three states
the design calls out: a populated panel (scalar rows, the status chip, and the
read-only ``input`` / ``xprompts`` sub-trees), the just-triggered empty panel,
and an error state where a bad ``input`` type surfaces the core ``⟨! N⟩`` chip
plus the inline red diagnostic.  The bar is mounted directly over the Patches
tab so the full ``styles.tcss`` styling applies exactly as it does at runtime.
"""

from __future__ import annotations

import pytest
from textual.widgets import Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.input_item_modal import InputItemModal
from sase.ace.tui.modals.xprompt_item_modal import XPromptItemModal
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.vim_text_area import VimTextArea
from sase.xprompt.models import InputArg, InputType, XPrompt
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


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
    await wait_for_state(
        page,
        lambda: bar.active_text_area().has_focus,
        description="mounted frontmatter prompt-bar focus",
    )
    await wait_for_visual_idle(page)
    return bar


async def _focus_frontmatter_panel(
    page: AcePage,
    bar: PromptInputBar,
) -> FrontmatterPanel:
    bar.focus_frontmatter_panel()
    panel = bar.query_one("#frontmatter-panel", FrontmatterPanel)
    await wait_for_state(
        page,
        lambda: panel.has_focus and not panel.has_class("hidden"),
        description="visible, focused frontmatter panel",
    )
    await wait_for_visual_idle(page)
    return panel


async def test_frontmatter_panel_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, _POPULATED_PROMPT)

        # Focus the panel so its accent border + selected row are pinned too.
        await _focus_frontmatter_panel(page, bar)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_populated_120x40",
            title="ACE frontmatter panel — populated",
        )


async def test_frontmatter_panel_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, "")

        # An empty prompt + g= shows the just-triggered empty-state guidance.
        await _focus_frontmatter_panel(page, bar)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_empty_120x40",
            title="ACE frontmatter panel — empty",
        )


async def test_frontmatter_panel_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")
        bar = await _mount_prompt_bar(page, _ERROR_PROMPT)

        # An invalid input type drives the ⟨! N⟩ chip + the inline red message.
        await _focus_frontmatter_panel(page, bar)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_error_120x40",
            title="ACE frontmatter panel — error state",
        )


async def test_frontmatter_panel_cell_edit_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        bar = await _mount_prompt_bar(page, _POPULATED_PROMPT)
        panel = await _focus_frontmatter_panel(page, bar)
        panel._select_nav(("input", "service"))
        panel._edit_selected()
        editor = panel.query_one("#frontmatter-inline")
        await wait_for_state(
            page,
            lambda: panel._edit_mode == "cell" and editor.has_focus,
            description="frontmatter input cell editor",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_cell_edit_120x40",
            title="ACE frontmatter panel — cell edit",
        )


async def test_frontmatter_panel_ghost_row_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        bar = await _mount_prompt_bar(page, _POPULATED_PROMPT)
        panel = await _focus_frontmatter_panel(page, bar)
        panel._select_nav(("field", "input"))
        panel._add_item_at_selection()
        editor = panel.query_one("#frontmatter-inline")
        await wait_for_state(
            page,
            lambda: (
                panel._cell_edit is not None
                and panel._cell_edit.field == "input"
                and panel._cell_edit.ghost
                and editor.has_focus
            ),
            description="frontmatter input ghost-row editor",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_ghost_row_120x40",
            title="ACE frontmatter panel — ghost row",
        )


async def test_frontmatter_panel_raw_diagnostics_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        bar = await _mount_prompt_bar(page, _POPULATED_PROMPT)
        panel = await _focus_frontmatter_panel(page, bar)
        panel._begin_raw()
        generation = panel._raw_diagnostics_generation
        panel.query_one(
            "#frontmatter-raw", VimTextArea
        ).text = "---\ninput:\n  service: wordd\n---"
        feedback = panel.query_one("#frontmatter-feedback", Static)
        await wait_for_state(
            page,
            lambda: (
                panel._raw_diagnostics_generation > generation
                and not feedback.has_class("hidden")
                and bool(feedback.render().plain)
            ),
            description="frontmatter raw validation diagnostic",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_raw_diagnostics_120x40",
            title="ACE frontmatter panel — raw diagnostics",
        )


async def test_frontmatter_panel_saved_feedback_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the saved feedback row with a still-visible prompt pane below it."""
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        bar = await _mount_prompt_bar(page, _POPULATED_PROMPT)
        panel = await _focus_frontmatter_panel(page, bar)
        panel._select_nav(("input", "service"))
        panel._edit_selected()
        panel._commit_cell_edit()
        feedback = panel.query_one("#frontmatter-feedback", Static)
        await wait_for_state(
            page,
            lambda: (
                panel._feedback == "Saved"
                and not feedback.has_class("hidden")
                and bar.active_text_area().region.height >= 1
            ),
            description="saved feedback with visible prompt pane",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_panel_saved_feedback_120x40",
            title="ACE frontmatter panel — saved feedback",
        )


async def test_frontmatter_input_item_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")

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
        await wait_for_svg_contains(page, "how many times to retry")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_input_item_modal_120x40",
            title="ACE frontmatter input item editor",
        )


async def test_frontmatter_xprompt_item_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "patches")

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
        await wait_for_svg_contains(page, "team review rules")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "frontmatter_xprompt_item_modal_120x40",
            title="ACE frontmatter xprompt item editor",
        )
