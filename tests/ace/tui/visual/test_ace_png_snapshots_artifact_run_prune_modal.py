"""PNG snapshots for the prune review at regular and narrow widths."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.modals.artifact_run_prune_modal import ArtifactRunPruneModal
from sase.core.agent_artifact_run_prune_review import (
    RunPruneProjectAggregate,
    RunPruneReview,
    RunPruneReviewCounts,
    RunPruneSnapshot,
    RunPruneSnapshotItem,
)
from sase.notifications import Notification
from tests.ace.tui.visual._ace_agents_png_snapshot_helpers import (
    assert_page_svg_contains,
)
from tests.ace.tui.visual._ace_png_snapshot_helpers import (
    patches,
    patch_startup_loaders,
    wait_for_startup,
    wait_for_visual_idle,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

pytestmark = pytest.mark.visual

_NOW = datetime(2026, 11, 6, 10, 33, tzinfo=UTC)
_CAPTURED_AT = "2026-11-06T10:00:00+00:00"


def _review(*, blocked: bool = False) -> RunPruneReview:
    projects = (
        RunPruneProjectAggregate(
            project="sase-key",
            runs=2_326,
            bytes=1_180_000_000,
            oldest="20260707000000",
            newest="20260831000000",
        ),
        RunPruneProjectAggregate(
            project="bob-cli-key",
            runs=199,
            bytes=56_833_740,
            oldest="20260707000000",
            newest="20260829000000",
        ),
        RunPruneProjectAggregate(
            project="proj-key",
            runs=68,
            bytes=22_020_096,
            oldest="20260709000000",
            newest="20260830000000",
        ),
        RunPruneProjectAggregate(
            project="home-key",
            runs=38,
            bytes=9_856_205,
            oldest="20260708000000",
            newest="20260827000000",
        ),
        RunPruneProjectAggregate(
            project="actstat-key",
            runs=3,
            bytes=1_258_291,
            oldest="20260707000000",
            newest="20260711000000",
        ),
    )
    return RunPruneReview(
        fingerprint="0123456789abcdef",
        captured_at=_CAPTURED_AT,
        keep_recent_months=2,
        first_kept_month="2026-09",
        counts=RunPruneReviewCounts(
            candidates=23_434,
            selected=2_634,
            protected=20_800,
            empty_shards=0,
        ),
        reclaimable_bytes=sum(project.bytes for project in projects),
        projects=projects,
        unavailable_sources=(
            "beads sidecar",
            "plans sidecar",
            "artifact index",
            "continuation ledger",
            "bead references",
            "active run markers",
        )
        if blocked
        else (),
        unavailable_source_count=6 if blocked else 0,
    )


def _snapshot(review: RunPruneReview) -> RunPruneSnapshot:
    items: list[RunPruneSnapshotItem] = []
    for project in review.projects:
        base_size, extra_bytes = divmod(project.bytes, project.runs)
        for index in range(project.runs):
            timestamp = (
                project.oldest
                if index == 0
                else project.newest
                if index == project.runs - 1
                else project.oldest
            )
            items.append(
                RunPruneSnapshotItem(
                    project=project.project,
                    timestamp=timestamp,
                    artifact_dir=f"/fixture/{project.project}/{index}/{timestamp}",
                    size_bytes=base_size + int(index < extra_bytes),
                )
            )
    return RunPruneSnapshot(
        fingerprint=review.fingerprint,
        captured_at=review.captured_at,
        keep_recent_months=review.keep_recent_months,
        items=tuple(items),
        empty_shard_count=review.counts.empty_shards,
        sources_unavailable=review.unavailable_sources,
    )


def _notification() -> Notification:
    return Notification(
        id="visual-prune-review",
        timestamp=_CAPTURED_AT,
        sender="axe",
        icon="🧹",
        notes=["2,634 old ACE runs can be pruned"],
        action="ViewReport",
        action_data={"report_title": "ACE run pruning preview"},
    )


def _patch_review_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.core.agent_artifact_run_prune_review.load_snapshot",
        lambda _fingerprint: _snapshot(_review()),
    )
    monkeypatch.setattr(
        "sase.project_display_names.cached_project_display_snapshot",
        lambda: {
            "sase-key": "sase",
            "bob-cli-key": "bob-cli",
            "proj-key": "proj",
            "home-key": "home",
            "actstat-key": "actstat",
        },
    )


async def _capture(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    size: tuple[int, int],
    blocked: bool = False,
) -> None:
    _patch_review_loader(monkeypatch)
    patch_startup_loaders(monkeypatch, agents=[])

    async with AcePage(query='"visual"', size=size, patches=patches()) as page:
        await wait_for_startup(page)
        modal = ArtifactRunPruneModal(
            _review(blocked=blocked), _notification(), now=_NOW
        )
        page.app.push_screen(modal)
        await page.expect_modal("ArtifactRunPruneModal")
        await page.wait_for(lambda _state: modal._view.state != "CHECKING")
        await wait_for_visual_idle(page)

        assert_page_svg_contains(page, "Prune old ACE runs")
        assert_page_svg_contains(page, "snapshot · 33m ago")
        if blocked:
            assert_page_svg_contains(page, "Protection sources are unreadable")
        else:
            assert_page_svg_contains(page, "Move 2,634 runs to trash")
            assert_page_svg_contains(page, "sase")

        ace_png_visual.assert_page_png(
            page,
            name,
            title="ACE run prune review" + (" · blocked" if blocked else ""),
        )


async def test_artifact_run_prune_review_ready_120x40_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture(
        ace_png_visual,
        monkeypatch,
        name="artifact_run_prune_review_ready_120x40",
        size=(120, 40),
    )


async def test_artifact_run_prune_review_blocked_120x40_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture(
        ace_png_visual,
        monkeypatch,
        name="artifact_run_prune_review_blocked_120x40",
        size=(120, 40),
        blocked=True,
    )


async def test_artifact_run_prune_review_ready_narrow_png_snapshot(
    ace_png_visual: AcePngSnapshotFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _capture(
        ace_png_visual,
        monkeypatch,
        name="artifact_run_prune_review_ready_narrow_80x24",
        size=(80, 24),
    )
