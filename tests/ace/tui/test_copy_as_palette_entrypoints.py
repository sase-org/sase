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
    ["stitches", "beads", "ref:plan", "files"],
)
async def test_percent_opens_palette_for_each_live_artifacts_subtab(
    subtab: Literal["stitches", "beads", "ref:plan", "files"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pane = controlled_artifact_pane(subtab)
    async with AcePage() as page:
        if subtab.startswith("ref:"):
            view = page.query_one_widget("#artifacts-view")
            if subtab not in {descriptor.id for descriptor in view.descriptors}:
                pytest.skip(f"{subtab} provider is not configured in this test run")
        page.app.current_artifacts_subtab = subtab
        await page.expect_state("artifacts_subtab", subtab)
        if subtab == "files":
            pane_resolver = "_files_pane"
        elif subtab == "stitches":
            pane_resolver = "_commits_pane"
        elif subtab == "ref:plan":
            pane_resolver = "_active_documents_pane"
        else:
            pane_resolver = f"_{subtab}_pane"
        monkeypatch.setattr(page.app, pane_resolver, lambda: pane)
        page.app._artifacts_marked_targets.clear()
        await page.pause()

        await page.press("%")
        await page.expect_modal("CopyAsModal")

        modal = page.app.screen_stack[-1]
        assert isinstance(modal, CopyAsModal)
        expected_group = (
            "artifacts_plans"
            if subtab == "ref:plan"
            else "artifacts_other"
            if subtab == "files"
            else f"artifacts_{subtab}"
        )
        assert modal.context.group == expected_group


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
