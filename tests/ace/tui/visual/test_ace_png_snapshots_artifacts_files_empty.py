"""Empty-state PNG coverage for the ACE Artifacts -> Files pane."""

from __future__ import annotations

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import files_pane
from sase.ace.tui.widgets.artifacts.files_pane import ArtifactsFilesPane
from tests.ace.tui._artifacts_files_helpers import snapshot
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


async def test_artifacts_files_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        files_pane,
        "load_files_snapshot",
        lambda project, _limit: snapshot((), project=project),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("files"), "(")
        await page.expect_state("artifacts_subtab", "files")
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()

        def _files_empty_ready(_state: object) -> bool:
            try:
                pane = page.query_one_widget(
                    "#artifacts-files-pane", ArtifactsFilesPane
                )
            except Exception:
                return False
            return (
                pane.snapshot is not None
                and pane.snapshot.rows == ()
                and pane.snapshot.project == "alpha"
                and getattr(pane, "_project_display_name", None) == "Alpha"
            )

        await page.wait_for(_files_empty_ready, timeout=15.0)
        await wait_for_svg_contains(page, "No artifact files")
        await wait_for_svg_contains(page, "Select an artifact file to inspect it.")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_files_empty_120x40",
            title="ACE Artifacts - Files empty",
        )
