"""ACE TUI PNG visual snapshots for multi-agent prompt stack layout."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.prompt_submit_choice_modal import PromptSubmitChoiceModal
from sase.ace.tui.widgets import StashedPromptsIndicator
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual._ace_prompt_png_snapshot_helpers import (
    COMPACT_PROMPT,
    TWO_PANE_PROMPT,
    XPROMPT_COMPLETION_ROWS,
    mount_prompt_bar,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_prompt_stack_two_panes_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await mount_prompt_bar(page, TWO_PANE_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_two_panes_120x40",
            title="ACE prompt stack — active lower pane",
        )


async def test_prompt_stack_active_upper_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        # Focus the top pane so the accent border moves up and the bottom pane
        # dims — the mirror image of the default active-lower snapshot.
        bar.focus_item(0)
        await wait_for_state(
            page,
            lambda: bar._stack.selected_index == 0 and bar.active_text_area().has_focus,
            description="upper prompt pane focus",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_active_upper_120x40",
            title="ACE prompt stack — active upper pane",
        )


async def test_prompt_submit_choice_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await mount_prompt_bar(page, TWO_PANE_PROMPT)

        page.app.push_screen(PromptSubmitChoiceModal(prompt_count=2))
        await page.expect_modal("PromptSubmitChoiceModal")
        await wait_for_svg_contains(page, "Launch all 2 prompts")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_submit_choice_modal_120x40",
            title="ACE prompt stack — submit chooser",
        )


async def test_prompt_stack_compact_inactive_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(
        query='"visual"', changespecs=changespecs(), size=(80, 30)
    ) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await mount_prompt_bar(page, COMPACT_PROMPT)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_compact_inactive_80x30",
            title="ACE prompt stack — compact inactive panes",
        )


async def test_prompt_stack_completion_panel_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        # The completion panel is scoped to the active pane; render a
        # deterministic xprompt completion to pin its in-stack styling.
        bar.show_file_completions(
            "fo",
            XPROMPT_COMPLETION_ROWS,
            selected_index=1,
            completion_kind="xprompt",
        )
        await wait_for_state(
            page,
            lambda: (
                bar._completion_visible and bar._completion_panel_kind == "completion"
            ),
            description="xprompt completion panel visibility",
        )
        await wait_for_svg_contains(page, "followup")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_completion_panel_120x40",
            title="ACE prompt stack — completion panel in active pane",
        )


async def test_prompt_stack_g_prefix_hints_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        indicator = page.app.query_one(
            "#stashed-prompts-indicator", StashedPromptsIndicator
        )
        indicator.set_count(2)
        bar = await mount_prompt_bar(page, TWO_PANE_PROMPT)

        await page.press("escape", "g")
        text_area = bar.active_text_area()
        await wait_for_state(
            page,
            lambda: (
                text_area._vim_mode == "normal"
                and text_area._pending_keys == "g"
                and bar._g_prefix_hints_visible
            ),
            description="NORMAL-mode g-prefix hint panel",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_stack_g_prefix_hints_120x40",
            title="ACE prompt stack — g prefix hints",
        )
