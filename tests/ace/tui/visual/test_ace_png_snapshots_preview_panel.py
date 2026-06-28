"""ACE TUI PNG visual snapshots for the prompt preview panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

BROAD_SCREENSHOT_MAX_DIFF_RATIO = 0.03


async def test_preview_panel_xprompt_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    payload = PreviewPayload(
        kind_label="xprompt",
        icon="#",
        title="#review",
        source_path="/workspace/sase/.xprompts/review.md",
        lexer="markdown",
        content=(
            "---\n"
            "description: Review the current patch\n"
            "inputs:\n"
            "  topic:\n"
            "    type: line\n"
            "---\n\n"
            "# Review Checklist\n\n"
            "- Summarize the behavioral change.\n"
            "- Call out regression risk and missing tests.\n"
            "- Keep the recommendation concise and actionable.\n"
        ),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        page.app.push_screen(PreviewPanelModal(payload))
        await page.expect_modal("PreviewPanelModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "preview_panel_xprompt_120x40",
            title="ACE prompt preview panel - xprompt",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )


async def test_preview_panel_file_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    payload = PreviewPayload(
        kind_label="file",
        icon="@",
        title="@src/sase/ace/tui/widgets/prompt_text_area.py",
        source_path="/workspace/sase/src/sase/ace/tui/widgets/prompt_text_area.py",
        lexer="python",
        content="\n".join(
            [
                '"""Prompt text area preview fixture."""',
                "",
                "from __future__ import annotations",
                "",
                "",
                "class PromptTextArea:",
                "    def preview_token_under_cursor(self) -> None:",
                "        token = self.detect_token()",
                "        if token is None:",
                "            self.notify('Move to a previewable token')",
                "            return",
                "        self.open_preview(token)",
                "",
                "    def open_preview(self, token: object) -> None:",
                "        self.app.push_screen(token)",
            ]
        ),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        page.app.push_screen(PreviewPanelModal(payload))
        await page.expect_modal("PreviewPanelModal")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "preview_panel_file_120x40",
            title="ACE prompt preview panel - file",
            max_diff_ratio=BROAD_SCREENSHOT_MAX_DIFF_RATIO,
        )
