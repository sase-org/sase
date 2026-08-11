"""PNG snapshot for the snippet save confirmation's diff view."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.snippet_save_confirm_modal import (
    SnippetSaveConfirmModal,
    SnippetSaveConfirmState,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

EXISTING_BODY = "- [ ] $1\n"
DRAFT_BODY = "- [ ] $1 (owner: $2)\n"


async def test_snippet_save_confirm_diff_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    modal = SnippetSaveConfirmModal(
        SnippetSaveConfirmState(
            trigger="todo",
            display_path="~/.config/sase/sase.yml",
            body=DRAFT_BODY,
            exists=True,
            existing_body=EXISTING_BODY,
        )
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        page.app.push_screen(modal)
        await page.expect_modal("SnippetSaveConfirmModal")
        await wait_for_svg_contains(page, "Overwrite")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "snippet_save_confirm_diff_120x40",
            title="ACE snippet save confirmation — diff view",
        )
