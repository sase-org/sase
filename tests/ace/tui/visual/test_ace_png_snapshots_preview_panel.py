"""ACE TUI PNG visual snapshots for the prompt preview panel."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


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
        )


async def test_commit_view_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    diff_path = tmp_path / "commit.diff"
    diff_path.write_text(
        """diff --git a/src/sase/ace/tui/widgets/prompt_panel.py b/src/sase/ace/tui/widgets/prompt_panel.py
--- a/src/sase/ace/tui/widgets/prompt_panel.py
+++ b/src/sase/ace/tui/widgets/prompt_panel.py
@@ -12,7 +12,11 @@ class AgentPromptPanel:
     def render_commit(self, commit):
-        return commit.subject
+        return CommitView(
+            subject=commit.subject,
+            body=commit.message,
+            diff=commit.diff_text,
+        )
diff --git a/tests/ace/tui/widgets/test_commit_view.py b/tests/ace/tui/widgets/test_commit_view.py
new file mode 100644
--- /dev/null
+++ b/tests/ace/tui/widgets/test_commit_view.py
@@ -0,0 +1,4 @@
+def test_commit_view_opens_modal():
+    assert True
""",
        encoding="utf-8",
    )
    spec = CommitViewSpec(
        short_sha="52c99ca5d123",
        sha="52c99ca5d1234567890abcdef",
        repo_name="sase",
        cwd="/workspace/sase",
        subject="fix(tui): show commit details from hints",
        message=(
            "fix(tui): show commit details from hints\n\n"
            "Register COMMITS entries as view targets and render the full "
            "commit message with the captured patch."
        ),
        diff_path=str(diff_path),
        is_primary=True,
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        page.app.push_screen(CommitViewModal(spec))
        await page.expect_modal("CommitViewModal")
        for _ in range(20):
            modal = page.app.screen_stack[-1]
            if isinstance(modal, CommitViewModal) and modal._diff_loaded:
                break
            await page.pause()
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "commit_view_modal_120x40",
            title="ACE commit view modal",
        )
