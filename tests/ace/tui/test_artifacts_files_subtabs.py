"""Flattened Files pane lifecycle and pane-key state coverage."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import ArtifactsFilesPane


async def test_parenthesis_keys_only_apply_inside_files() -> None:
    async with AcePage(initial_tab="patches") as page:
        assert page.app.current_artifacts_subtab == "stitches"
        assert page.app.current_files_subtab == "files"

        await page.press(")", "(")
        assert page.app.current_artifacts_subtab == "stitches"
        assert page.app.current_files_subtab == "files"

        await page.press(page.artifacts_digit("files"), ")")
        await page.expect_state("artifacts_subtab", "files")
        await page.expect_state("files_subtab", "files")
        await page.press("(")
        await page.expect_state("artifacts_subtab", "files")
        await page.expect_state("files_subtab", "files")


async def test_files_pane_activation_is_preserved_across_top_level_switches() -> None:
    async with AcePage(initial_tab="patches") as page:
        files = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)

        await page.press(page.artifacts_digit("files"))
        assert files.artifacts_active is True
        assert files.first_activation_count == 1

        await page.press("1")
        assert files.artifacts_active is False

        await page.press(page.artifacts_digit("files"))
        assert files.artifacts_active is True
        assert files.activation_count == 2
        assert files.first_activation_count == 1


async def test_marks_and_jump_history_are_isolated_by_top_level_pane_key() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press(page.artifacts_digit("files"))
        file_target = ("file", "artifact")
        bead_target = ("bead", "sase", "task", "abc")
        page.app._artifacts_marked_targets["files"] = {file_target}
        page.app._artifacts_marked_targets["beads"] = {bead_target}
        page.app._artifacts_jump_history["files"] = file_target
        page.app._artifacts_jump_history["beads"] = bead_target

        assert page.app.current_artifacts_pane_key == "files"
        assert page.app._active_artifacts_marks() == {file_target}
        assert page.app._artifacts_jump_history["files"] == file_target

        await page.press("3")
        assert page.app.current_artifacts_pane_key == "beads"
        assert page.app._active_artifacts_marks() == {bead_target}
        assert page.app._artifacts_jump_history["beads"] == bead_target
        assert page.app._artifacts_jump_history["files"] == file_target
