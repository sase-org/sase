"""ACE TUI PNG visual snapshots for the prompt preview panel."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.commit_view_modal import CommitViewModal
from sase.ace.tui.modals.preview_panel_modal import PreviewPanelModal
from sase.ace.tui.widgets._prompt_preview_target import PreviewPayload
from sase.ace.tui.widgets.prompt_panel._agent_display_state import CommitViewSpec
from sase.plan_documents import PlanDocument
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
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PreviewPanelModal(payload))
        await page.expect_modal("PreviewPanelModal")
        await wait_for_svg_contains(page, "Review Checklist")
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
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PreviewPanelModal(payload))
        await page.expect_modal("PreviewPanelModal")
        await wait_for_svg_contains(page, "Prompt text area preview fixture")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "preview_panel_file_120x40",
            title="ACE prompt preview panel - file",
        )


async def test_preview_panel_reference_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)

    payload = PreviewPayload(
        kind_label="epic plan",
        icon="▤",
        title="Make PreviewPanelModal a real reader",
        source_path="/workspace/sase/sase/repos/plans/202607/preview_panel_reader.md",
        reference="plans:202607/preview_panel_reader.md",
        lexer="markdown",
        content=(
            "---\n"
            "tier: epic\n"
            "title: Make PreviewPanelModal a real reader\n"
            "status: wip\n"
            "---\n\n"
            "# Reader Core\n\n"
            "The preview modal supports copying, editor hand-off, and a rich viewer.\n"
        ),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        page.app.push_screen(PreviewPanelModal(payload))
        await page.expect_modal("PreviewPanelModal")
        await wait_for_svg_contains(page, "Reader Core")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "preview_panel_reference_120x40",
            title="ACE preview panel - reference and resolved path",
        )


async def test_commit_view_modal_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    diff_path = "/workspace/sase/.sase/diffs/52c99ca5d123.diff"
    diff_text = """diff --git a/src/sase/ace/tui/widgets/prompt_panel.py b/src/sase/ace/tui/widgets/prompt_panel.py
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
"""
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
        diff_path=diff_path,
        is_primary=True,
    )
    second_diff_path = "/workspace/sase/.sase/diffs/8ed4cc91a777.diff"
    second_diff_text = """diff --git a/src/sase/ace/tui/modals/commit_view_modal.py b/src/sase/ace/tui/modals/commit_view_modal.py
--- a/src/sase/ace/tui/modals/commit_view_modal.py
+++ b/src/sase/ace/tui/modals/commit_view_modal.py
@@ -55,6 +55,8 @@ class CommitViewModal:
         self._commit_specs = specs
+        self._current_index = initial_index
+        self._diff_text_by_index = {}
"""
    second_spec = CommitViewSpec(
        short_sha="8ed4cc91a777",
        sha="8ed4cc91a7774567890abcdef",
        repo_name="sase",
        cwd="/workspace/sase",
        subject="feat(tui): navigate selected commits",
        message=(
            "feat(tui): navigate selected commits\n\n"
            "Keep the selected commit set inside the modal and switch between "
            "loaded diffs with ctrl+n and ctrl+p."
        ),
        diff_path=second_diff_path,
        is_primary=True,
    )
    diff_text_by_path = {
        diff_path: diff_text,
        second_diff_path: second_diff_text,
    }
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.load_commit_diff_text",
        lambda spec: diff_text_by_path.get(spec.diff_path or ""),
    )
    monkeypatch.setattr(
        "sase.ace.tui.modals.commit_view_modal.load_commit_plan_document",
        lambda *_args, **_kwargs: PlanDocument(
            "success",
            reference="202607/commit_view_plan_toggle.md",
            path="/workspace/sase/sase/repos/plans/202607/commit_view_plan_toggle.md",
            content=(
                "---\n"
                "title: View associated plans from the commit panel\n"
                "tier: tale\n"
                "---\n\n"
                "# Plan\n\n"
                "## Modal behavior\n\n"
                "- Press `p` to restore the same commit and cached diff.\n"
                "- Keep plan loading off the Textual event loop.\n"
            ),
        ),
    )

    async with AcePage(query='"visual"', changespecs=changespecs()) as page:
        await wait_for_startup(page)
        await page.press("5")
        await page.expect_state("artifacts_subtab", "prs")
        modal = CommitViewModal([spec, second_spec], initial_index=1)
        page.app.push_screen(modal)
        await page.expect_modal("CommitViewModal")
        await wait_for_state(
            page,
            lambda: modal._diff_loaded,
            description="commit-view diff to finish loading",
        )
        await wait_for_svg_contains(page, "navigate selected commits")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "commit_view_modal_120x40",
            title="ACE commit view modal",
        )

        await page.press("p")
        await wait_for_state(
            page,
            lambda: modal._display_mode == "plan",
            description="commit plan view to finish loading",
        )
        await wait_for_svg_contains(page, "View associated plans")
        await wait_for_visual_idle(page)
        ace_png_visual.assert_page_png(
            page,
            "commit_plan_view_modal_120x40",
            title="ACE commit plan view modal",
        )
