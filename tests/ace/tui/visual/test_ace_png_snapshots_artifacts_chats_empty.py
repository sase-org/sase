"""Empty-state PNG coverage for the ACE Artifacts -> Chats pane."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import chats_pane
from sase.ace.tui.widgets.artifacts.chats_pane import ArtifactsChatsPane
from tests.ace.tui._artifacts_chats_helpers import catalog
from tests.ace.tui._artifacts_plans_helpers import _choices
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_artifacts_chats_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot = catalog(())
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        chats_pane,
        "load_chat_catalog",
        lambda **_kwargs: snapshot,
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("5", ")")
        await page.expect_state("files_subtab", "chats")
        pane = page.query_one_widget("#artifacts-chats-pane", ArtifactsChatsPane)
        await page.wait_for(
            lambda _state: pane.snapshot is not None and pane.snapshot.entries == ()
        )
        await wait_for_svg_contains(page, "No chat transcripts found.")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_chats_empty_120x40",
            title="ACE Artifacts - Chats empty",
        )
