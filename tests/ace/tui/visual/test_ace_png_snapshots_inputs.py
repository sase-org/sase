"""ACE PNG visual snapshot coverage for the Input Collection Modal (sase-4r.5).

Captures the modal in two states: freshly opened (required + collapsed optional
inputs, confirm disabled) and an error state (an invalid value showing inline
core guidance with the optional section revealed). Goldens live in
``tests/ace/tui/visual/snapshots/png/``.
"""

from __future__ import annotations

import pytest
from textual.widgets import Button, Label

from sase.ace.testing import AcePage
from sase.ace.tui.modals.input_collection_modal import InputCollectionModal
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.agent.prompt_inputs import parse_prompt_input_request
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

_PROMPT = (
    "---\n"
    "input:\n"
    "  service:\n"
    "    type: word\n"
    "    description: target service to refactor\n"
    "  retries:\n"
    "    type: int\n"
    "    description: how many times to retry\n"
    "  dry_run:\n"
    "    type: bool\n"
    "    default: false\n"
    "---\n"
    "Refactor {{ service }} ({{ retries }} retries, dry_run={{ dry_run }})."
)


def _push_modal(page: AcePage) -> InputCollectionModal:
    request = parse_prompt_input_request(_PROMPT)
    assert request is not None
    modal = InputCollectionModal(request, agent_count=3)
    page.app.push_screen(modal)
    return modal


async def test_input_collection_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        modal = _push_modal(page)
        await page.expect_modal("InputCollectionModal")
        await wait_for_svg_contains(page, "target service to refactor")
        first_input = modal.query_one("#field-input-0", SingleLineVimTextArea)
        await wait_for_state(
            page,
            lambda: first_input.has_focus,
            description="first required prompt input focus",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "input_collection_modal_120x40",
            title="ACE input collection modal",
        )


async def test_input_collection_modal_error_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("4")
        await page.expect_state("artifacts_subtab", "prs")
        await page.expect_state("tab", "changespecs")
        modal = _push_modal(page)
        await page.expect_modal("InputCollectionModal")
        await wait_for_svg_contains(page, "target service to refactor")
        first_input = modal.query_one("#field-input-0", SingleLineVimTextArea)
        await wait_for_state(
            page,
            lambda: first_input.has_focus,
            description="first required prompt input focus",
        )
        await wait_for_visual_idle(page)

        modal.query_one("#field-input-0", SingleLineVimTextArea).text = "billing"
        modal.query_one(
            "#field-input-1", SingleLineVimTextArea
        ).text = "three"  # invalid int
        modal.query_one("#toggle-optional", Button).press()
        error = modal.query_one("#field-error-1", Label)
        await wait_for_state(
            page,
            lambda: (
                modal._optional_revealed
                and error.display
                and bool(error.render().plain)
            ),
            description="invalid retries guidance with optional inputs revealed",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "input_collection_modal_error_120x40",
            title="ACE input collection modal error",
        )
