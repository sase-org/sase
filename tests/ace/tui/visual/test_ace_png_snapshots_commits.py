"""PNG visual coverage for the Artifacts Commits timeline and detail."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.actions.artifacts import _ArtifactsProjectChoices
from sase.ace.tui.widgets.artifacts import CommitsPane
import sase.ace.tui.widgets.artifacts.commits as commits_module
from tests.ace.tui.test_commits_pane import _DIFF, _result
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    changespecs,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


async def test_commits_timeline_and_detail_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    timestamp = int(datetime(2026, 7, 6, 14, 30, tzinfo=UTC).timestamp())
    result = _result(timestamp)
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(
        commits_module,
        "load_commit_diff_text",
        lambda _spec: _DIFF,
    )
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: _ArtifactsProjectChoices((), (), {}),
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await wait_for_svg_contains(page, "feat: interactive timeline")
        await wait_for_svg_contains(page, "Changes:")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_timeline_detail_120x40",
            title="ACE Artifacts Commits timeline",
        )


async def test_commits_empty_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    result = commits_module.VcsLogResult((), (), ())
    monkeypatch.setattr(commits_module, "run_vcs_log", lambda **_kwargs: result)
    monkeypatch.setattr(
        "sase.ace.tui.actions.artifacts._collect_artifacts_project_choices",
        lambda: _ArtifactsProjectChoices((), (), {}),
    )

    async with AcePage(
        query='"visual"',
        changespecs=changespecs(),
        initial_tab="changespecs",
    ) as page:
        await wait_for_startup(page)
        await page.press("]")
        await page.expect_state("artifacts_subtab", "commits")
        pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
        await page.wait_for(lambda _state: pane.result is result)
        await wait_for_svg_contains(page, "No commits match")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_commits_empty_120x40",
            title="ACE Artifacts Commits empty",
        )
