"""PNG visual regression coverage for the Artifacts Bugs pane."""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.testing import AcePage, make_changespec
from sase.ace.tui.artifacts_bugs import BugSnapshot
from sase.ace.tui.widgets import ArtifactsBugsPane
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bug_links import BugLinks
from sase.vcs_provider import IssueWire
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patch_startup_loaders,
    wait_for_startup,
    wait_for_svg_contains,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual


def _issue() -> IssueWire:
    return IssueWire(
        number=42,
        title="Login fails after rotating an access token",
        state="open",
        body=(
            "## Reproduction steps\n\n"
            "1. Rotate the access token.\n"
            "2. Sign in from an existing session.\n\n"
            "**Expected:** the session refreshes without an error."
        ),
        labels=("bug", "priority:high"),
        assignees=("octocat",),
        author="reporter",
        updated_at="2026-07-06T10:00:00Z",
        url="https://example.test/issues/42",
        comment_count=3,
    )


def _snapshot(*, supported: bool = True) -> BugSnapshot:
    linked_pr = make_changespec(name="fix_rotated_token")
    linked_pr.bug = "42"
    epic = Issue(
        id="sase-69",
        title="Artifacts tab epic",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        changespec_name="fix_rotated_token",
        changespec_bug_id="42",
    )
    issue = _issue()
    return BugSnapshot(
        project_key="alpha",
        display_name="Alpha",
        project_file="/state/alpha/alpha.sase",
        cwd="/repos/alpha",
        state_filter="open",
        issues=(issue,) if supported else (),
        links=((42, BugLinks("42", (epic,), (linked_pr,))),) if supported else (),
        supported=supported,
    )


async def _open_bugs(page: AcePage) -> ArtifactsBugsPane:
    page.app._set_artifacts_project_scope("alpha", picked=True)
    page.app.current_artifacts_subtab = "bugs"
    await page.expect_state("artifacts_subtab", "bugs")
    return page.query_one_widget("#artifacts-bugs-pane", ArtifactsBugsPane)


async def test_artifacts_bugs_populated_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_a, **_kw: _snapshot(),
    )
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs_rendering.local_now",
        lambda: datetime(2026, 7, 6, 12, 0, 0),
    )

    async with AcePage(query='"visual"') as page:
        await wait_for_startup(page)
        pane = await _open_bugs(page)
        await page.wait_for(lambda _state: pane.selected_issue == _issue())
        await wait_for_svg_contains(page, "Reproduction steps")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_bugs_populated_120x40",
            title="ACE Artifacts Bugs populated",
        )


async def test_artifacts_bugs_unsupported_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_startup_loaders(monkeypatch)
    monkeypatch.setattr(
        "sase.ace.tui.widgets.artifacts.bugs.collect_bug_snapshot",
        lambda *_a, **_kw: _snapshot(supported=False),
    )

    async with AcePage(query='"visual"') as page:
        await wait_for_startup(page)
        await _open_bugs(page)
        await wait_for_svg_contains(page, "tracker-capable provider")
        await wait_for_svg_contains(page, "sase ace")
        await wait_for_visual_idle(page)

        ace_png_visual.assert_page_png(
            page,
            "artifacts_bugs_unsupported_120x40",
            title="ACE Artifacts Bugs unsupported",
        )
