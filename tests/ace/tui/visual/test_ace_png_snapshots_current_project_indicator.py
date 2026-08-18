"""ACE TUI PNG visual snapshot coverage for the current-project chip.

Phase polish (epic sase-pw): pin how the top-bar ``CurrentProjectIndicator``
renders a resolved ``+<project>`` chip beside the gold default-model pill.

The empty state (no current project) is the baseline pinned by every other
top-bar snapshot, so it needs no dedicated frame here.
"""

from __future__ import annotations

import pytest

import sase.ace.tui.widgets.current_project_indicator as current_project_indicator
from sase.ace.testing import AcePage
from sase.ace.tui.project_styles import project_accent
from sase.ace.tui.widgets import CurrentProjectIndicator
from sase.ace.tui.widgets.current_project_indicator import _CurrentProjectSnapshot
from sase.current_project import CurrentProject
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_state,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _current_project() -> CurrentProject:
    return CurrentProject(
        project_key="gh_sase-org__sase",
        display_name="sase",
        origin="project",
        origin_ref="sase",
        workflow_type="gh",
    )


def _paint_current_project_chip(page: AcePage) -> CurrentProjectIndicator:
    """Force the chip visible so the snapshot does not wait on the worker."""

    project = _current_project()
    indicator = page.app.query_one(
        "#current-project-indicator",
        CurrentProjectIndicator,
    )
    indicator._cached_snapshot = _CurrentProjectSnapshot(
        project=project,
        accent=project_accent(project.project_key, among=(project.project_key,)),
    )
    indicator._cached_token = ("visual-current-project",)
    indicator._cached_failed = False
    indicator._apply_content()
    return indicator


async def test_current_project_indicator_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    project = _current_project()
    monkeypatch.setattr(
        current_project_indicator,
        "resolve_current_project",
        lambda **_kwargs: project,
    )
    monkeypatch.setattr(
        current_project_indicator,
        "peek_current_project_change_token",
        lambda: ("visual-current-project",),
    )
    monkeypatch.setattr(
        current_project_indicator,
        "_enabled_project_keys",
        lambda: (project.project_key,),
    )

    async with AcePage(query='"visual"', patches=patches()) as page:
        await wait_for_startup(page)
        await page.press("2")
        await page.expect_state("artifacts_subtab", "patches")
        await page.expect_state("tab", "patches")
        indicator = _paint_current_project_chip(page)
        page.app.refresh(layout=True)
        await page.app.wait_for_refresh()
        await wait_for_state(
            page,
            lambda: indicator.render().plain == " ▏+sase▕ ",
            description="current-project chip",
        )
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "current_project_indicator_120x40",
            title="ACE +sase current-project chip",
        )
