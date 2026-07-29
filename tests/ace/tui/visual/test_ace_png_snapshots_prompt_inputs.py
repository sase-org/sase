"""ACE PNG snapshots for the unified Prompt Inputs panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.input_collection_modal import InputCollectionModal
from sase.agent.prompt_placeholder_inputs import build_prompt_input_plan
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_PLACEHOLDERS_ONLY = (
    "Implement <the plan> and report back.\n"
    "Confirm <service> owns the change, then revisit <the plan>."
)

_MIXED = (
    "---\n"
    "input:\n"
    "  retries:\n"
    "    type: int\n"
    "    description: maximum retry count\n"
    "  dry_run:\n"
    "    type: bool\n"
    "    default: false\n"
    "---\n"
    "Implement <the plan> in <service> and report back."
)

_LONG_VALUE = (
    "Make PreviewPanelModal a real reader — M, highest daily value per line changed"
)


async def _open_modal(page: AcePage, prompt: str) -> InputCollectionModal:
    modal = InputCollectionModal(build_prompt_input_plan(prompt), agent_count=2)
    page.app.push_screen(modal)
    await page.expect_modal("InputCollectionModal")
    await wait_for_svg_contains(page, "Fill in this prompt")
    await wait_for_state(
        page,
        lambda: modal.query_one("#field-input-0").has_focus,
        description="first prompt input focus",
    )
    return modal


async def test_prompt_inputs_placeholders_only_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        await _open_modal(page, _PLACEHOLDERS_ONLY)
        await wait_for_svg_contains(page, "Implement")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_inputs_placeholders_only_120x40",
            title="ACE Prompt Inputs - placeholders only",
        )


async def test_prompt_inputs_mixed_literal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        modal = await _open_modal(page, _MIXED)
        modal.action_toggle_literal()
        await wait_for_state(
            page,
            lambda: modal.query_one("#field-block-0").has_class("literal"),
            description="first placeholder marked literal",
        )
        await wait_for_svg_contains(page, "literal · will stay as")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_inputs_mixed_literal_120x40",
            title="ACE Prompt Inputs - placeholders and declared inputs",
        )


async def test_prompt_inputs_long_value_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        modal = await _open_modal(page, "Implement <the plan> and report back.")
        editor = modal.query_one("#field-input-0")
        editor.text = _LONG_VALUE
        editor.cursor_position = len(_LONG_VALUE)
        await wait_for_state(
            page,
            lambda: (
                editor.wrapped_document.height > 1
                and not editor.show_horizontal_scrollbar
                and not editor.show_vertical_scrollbar
            ),
            description="long prompt input wrapped without scrollbars",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "prompt_inputs_long_value_120x40",
            title="ACE Prompt Inputs - long wrapped value",
        )
