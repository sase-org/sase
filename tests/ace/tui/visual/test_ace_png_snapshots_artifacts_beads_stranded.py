"""PNG coverage for stranded phase/task badges and epic breadcrumbs."""

from pathlib import Path

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts.beads_pane import ArtifactsBeadsPane
from sase.ace.tui.widgets.artifacts.entry_navigation import ArtifactEntryTarget
from tests.ace.tui._artifacts_beads_stranded_helpers import stranded_snapshot
from tests.ace.tui._artifacts_plans_helpers import _choices
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
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


async def test_artifacts_beads_stranded_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    patch_startup_loaders(monkeypatch)
    snapshot, _ = stranded_snapshot(tmp_path, monkeypatch)
    snapshot.tasks[0].issue.title = "Active work"
    snapshot.tasks[1].issue.title = "Fix crash"
    snapshot.epics[0].issue.title = "Release train"
    snapshot.phases_by_epic["alpha", "alpha-1"][0].issue.title = "Wait for release"
    snapshot.phases_by_epic["alpha", "alpha-1"][1].issue.title = "Release"
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        _choices,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_pane.load_beads_snapshot",
        lambda _project, **_kwargs: snapshot,
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.beads_stranded_refresh.warm_stranded_work_reports",
        lambda *_args, **_kwargs: {},
    )
    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press(page.artifacts_digit("beads"))
        await page.expect_state("artifacts_subtab", "beads")
        pane = page.query_one_widget("#artifacts-beads-pane", ArtifactsBeadsPane)
        await page.wait_for(lambda _state: pane.snapshot is snapshot)
        await page.wait_for(lambda _state: pane._project_display_name == "Alpha")
        assert pane.select_entry_target(
            ArtifactEntryTarget(pane_id="beads", parts=("alpha", "epic", "alpha-1"))
        )
        await page.press("l")
        await page.wait_for(
            lambda _state: (
                not pane._epic_fold_registry.is_collapsed(("alpha", "alpha-1"))
            )
        )
        assert pane.select_entry_target(
            ArtifactEntryTarget(
                pane_id="beads",
                parts=("alpha", "phase", "alpha-1.2"),
            )
        )
        await wait_for_svg_contains(page, "alpha-1.2--3")
        await wait_for_visual_idle(page)
        assert "⚐ 2 stranded" in pane._status_text().plain
        assert_page_svg_contains(page, "Stranded")
        assert_page_svg_contains(page, "nothing resumes it")
        ace_png_visual.assert_page_png(
            page,
            "artifacts_beads_stranded_120x40",
            title="ACE Artifacts - Stranded beads",
        )
