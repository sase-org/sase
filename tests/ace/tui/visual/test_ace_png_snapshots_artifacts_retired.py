"""ACE PNG goldens for the retired Artifacts Agent pane strip and toast."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.widgets._toast import Toast

from sase.ace.testing import AcePage
from sase.ace.tui import artifact_tabs
from sase.ace.tui._artifact_tab_model import ProviderLoadResult
from sase.feature_flags import override_flags
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    stabilize_toast_frame,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _use_production_strip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mount the production strip with an empty provider set.

    Both ``patch_startup_loaders`` and the mount-time fast startup patch
    point ``resolve_artifacts_subtabs`` at the deterministic fixture;
    repoint the fixture at the production resolver and feed it an empty
    provider set, as the conformance test does, so the golden captures
    the real retired strip.
    """
    from sase.ace.testing import _startup as ace_startup

    # Capture the raw production resolver before the fixture patches it:
    # calling back through the module attribute would recurse through the
    # fixture the loaders install below.
    production_resolve = artifact_tabs.resolve_artifacts_subtabs

    def _production_artifacts_subtabs() -> tuple[object, ...]:
        return production_resolve()

    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        ace_startup, "_fast_artifacts_subtabs", _production_artifacts_subtabs
    )
    monkeypatch.setattr(
        artifact_tabs,
        "load_project_provider_records",
        lambda *, project: ProviderLoadResult(records=(), issues=()),
    )
    artifact_tabs.reset_artifacts_subtabs_cache()


async def test_artifacts_retired_strip_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retired strip opens on Commits at digit 1 with no Agent pane."""
    with override_flags(artifacts_agent_pane_retired=True):
        _use_production_strip(monkeypatch)

        async with AcePage(query='"visual"', patches=patches()) as page:
            await wait_for_startup(page)
            await page.press(page.artifacts_digit("stitches"))
            await page.expect_state("artifacts_subtab", "stitches")
            assert page.artifacts_digit("stitches") == "1"
            await wait_for_svg_contains(page, "Commits")
            await wait_for_visual_idle(page)

            ace_png_visual.assert_page_png(
                page,
                "artifacts_retired_strip_120x40",
                title="ACE Artifacts - retired Agent pane strip",
            )
    artifact_tabs.reset_artifacts_subtabs_cache()


def _toast_is_mounted(page: AcePage) -> bool:
    return bool(list(page.app.screen.query(Toast)))


async def test_artifacts_agent_pane_retired_toast_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The one-time retirement toast points at the Agents tab Archive."""
    from sase.ace.tui import _artifacts_agent_pane_notice as notice

    patch_startup_loaders(monkeypatch)
    marker = tmp_path / "artifacts_agent_pane_retired_notice_shown"
    monkeypatch.setattr(notice, "_marker_path", lambda: marker)

    with override_flags(artifacts_agent_pane_retired=True):
        async with AcePage(
            query='"visual"',
            patches=patches(),
            notifications=True,
        ) as page:
            await wait_for_startup(page)
            await page.press(page.artifacts_digit("patches"))
            await page.expect_state("artifacts_subtab", "patches")
            page.app._maybe_show_artifacts_agent_pane_toast()
            await page.wait_for(lambda _s: bool(list(page.app._notifications)))
            await page.wait_for(lambda _s: _toast_is_mounted(page))
            page.app.screen.set_focus(None)
            await wait_for_visual_idle(page)
            await stabilize_toast_frame(page)

            assert_page_svg_contains(page, "Agents tab")

            ace_png_visual.assert_page_png(
                page,
                "artifacts_agent_pane_retired_toast_120x40",
                title="ACE Artifacts Agent pane retirement toast",
            )
