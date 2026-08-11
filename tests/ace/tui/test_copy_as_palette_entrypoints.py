"""Live entry-point coverage for the registry-driven Copy as palette."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Literal

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.copy_as_modal import CopyAsModal
from tests.ace.tui._copy_as_palette_helpers import controlled_artifact_pane


@pytest.mark.parametrize(
    "subtab",
    ["stitches", "beads", "plans", "chats", "other"],
)
async def test_percent_opens_palette_for_each_live_artifacts_subtab(
    subtab: Literal["stitches", "beads", "plans", "chats", "other"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = controlled_artifact_pane(subtab)
    async with AcePage() as page:
        if subtab in {"plans", "chats", "other"}:
            page.app.current_artifacts_subtab = "files"
            page.app.current_files_subtab = subtab
            await page.expect_state("artifacts_subtab", "files")
            await page.expect_state("files_subtab", subtab)
        else:
            page.app.current_artifacts_subtab = subtab
            await page.expect_state("artifacts_subtab", subtab)
        if subtab == "other":
            pane_resolver = "_files_pane"
        elif subtab == "stitches":
            pane_resolver = "_commits_pane"
        else:
            pane_resolver = f"_{subtab}_pane"
        monkeypatch.setattr(page.app, pane_resolver, lambda: pane)
        page.app._artifacts_marked_targets.clear()

        await page.press("%")
        await page.expect_modal("CopyAsModal")

        modal = page.app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        assert modal.context.group == f"artifacts_{subtab}"


@pytest.mark.parametrize("tab", ["agents", "axe"])
async def test_percent_opens_palette_for_agent_and_axe_selection(
    tab: Literal["agents", "axe"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage(initial_tab=tab) as page:
        if tab == "agents":
            agent = SimpleNamespace(
                response_path="/workspace/chats/copy-worker.md",
                presented_agent_name="copy-worker",
                project_display_name="SASE",
                status="DONE",
            )
            monkeypatch.setattr(page.app, "_get_selected_agent", lambda: agent)
        else:
            page.app._axe_items = [SimpleNamespace(name="Copy palette")]
            page.app.current_idx = 0

        await page.press("%")
        await page.expect_modal("CopyAsModal")

        modal = page.app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        assert modal.context.group == tab
