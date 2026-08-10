"""Nested Files sub-tab lifecycle and pane-key state coverage."""

from __future__ import annotations

from sase.ace.testing import AcePage
from sase.ace.tui.widgets import (
    ArtifactsChatsPane,
    ArtifactsFilesPane,
    ArtifactsFilesView,
    ArtifactsPlansPane,
)


async def test_parenthesis_keys_cycle_only_inside_files_with_wraparound() -> None:
    async with AcePage(initial_tab="patches") as page:
        assert page.app.current_artifacts_subtab == "stitches"
        assert page.app.current_files_subtab == "plans"

        await page.press(")", "(")
        assert page.app.current_artifacts_subtab == "stitches"
        assert page.app.current_files_subtab == "plans"

        await page.press("5", ")")
        await page.expect_state("files_subtab", "chats")
        await page.press(")")
        await page.expect_state("files_subtab", "other")
        await page.press(")")
        await page.expect_state("files_subtab", "plans")
        await page.press("(")
        await page.expect_state("files_subtab", "other")


async def test_files_child_is_remembered_and_only_visible_child_is_active() -> None:
    async with AcePage(initial_tab="patches") as page:
        files_view = page.query_one_widget("#artifacts-files-view", ArtifactsFilesView)
        plans = page.query_one_widget("#artifacts-plans-pane", ArtifactsPlansPane)
        chats = page.query_one_widget("#artifacts-chats-pane", ArtifactsChatsPane)
        other = page.query_one_widget("#artifacts-files-pane", ArtifactsFilesPane)

        await page.press("5")
        assert files_view.artifacts_active is True
        assert plans.artifacts_active is True
        assert chats.artifacts_active is False
        assert other.artifacts_active is False

        await page.press(")")
        assert plans.artifacts_active is False
        assert chats.artifacts_active is True
        assert other.artifacts_active is False

        await page.press("1")
        assert files_view.artifacts_active is False
        assert plans.artifacts_active is False
        assert chats.artifacts_active is False
        assert other.artifacts_active is False

        await page.press("5")
        await page.expect_state("files_subtab", "chats")
        assert chats.artifacts_active is True
        assert chats.activation_count == 2
        assert chats.first_activation_count == 1


async def test_marks_and_jump_history_are_isolated_by_leaf_pane_key() -> None:
    async with AcePage(initial_tab="patches") as page:
        await page.press("5")
        plan_target = ("plan", "sase", "archive", "one")
        chat_target = ("chat", "/tmp/chat.md")
        page.app._artifacts_marked_targets["plans"] = {plan_target}
        page.app._artifacts_marked_targets["chats"] = {chat_target}
        page.app._artifacts_jump_history["plans"] = plan_target
        page.app._artifacts_jump_history["chats"] = chat_target

        assert page.app.current_artifacts_pane_key == "plans"
        assert page.app._active_artifacts_marks() == {plan_target}
        assert page.app._artifacts_jump_history["plans"] == plan_target

        await page.press(")")
        assert page.app.current_artifacts_pane_key == "chats"
        assert page.app._active_artifacts_marks() == {chat_target}
        assert page.app._artifacts_jump_history["chats"] == chat_target
        assert page.app._artifacts_jump_history["plans"] == plan_target
