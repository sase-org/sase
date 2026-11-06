"""Tests for the pure ACE-run prune review presentation model."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from sase.core.agent_artifact_run_prune_review import (
    RunPruneProjectAggregate,
    RunPruneReview,
    RunPruneReviewCounts,
)
from sase.ace.tui.models.artifact_run_prune_review_view import (
    _format_run_date,
    build_artifact_run_prune_review_view,
    human_size,
)


def _review(
    *,
    project_count: int = 10,
    unavailable_sources: tuple[str, ...] = (),
    unavailable_source_count: int = 0,
    captured_at: str = "2026-11-05T11:00:00+00:00",
) -> RunPruneReview:
    return RunPruneReview(
        fingerprint="0123456789abcdef",
        captured_at=captured_at,
        keep_recent_months=2,
        first_kept_month="2026-09",
        counts=RunPruneReviewCounts(
            candidates=20,
            selected=12_345,
            protected=20_800,
            empty_shards=0,
        ),
        reclaimable_bytes=1_287_700_000,
        projects=tuple(
            RunPruneProjectAggregate(
                project=f"project-{index}",
                runs=10 - index,
                bytes=(10 - index) * 1024,
                oldest="20260707000000",
                newest="20260831000000",
            )
            for index in range(project_count)
        ),
        unavailable_sources=unavailable_sources,
        unavailable_source_count=unavailable_source_count,
    )


def test_view_formats_summary_sorts_rows_and_limits_to_eight() -> None:
    display = {f"project-{index}": f"Project {index}" for index in range(10)}

    view = build_artifact_run_prune_review_view(
        _review(),
        display,
        now=datetime(2026, 11, 5, 11, 33, tzinfo=UTC),
        snapshot_exists=True,
    )

    assert view.state == "READY"
    assert view.freshness == "snapshot · 33m ago"
    assert view.stale is False
    assert view.run_count == "12,345"
    assert view.reclaimable_size == "1.2 GiB"
    assert view.project_count == "10"
    assert view.keep_window == ("Keep newest 2 months from Sep 2026 · 20,800 protected")
    assert [project.label for project in view.projects] == [
        f"Project {index}" for index in range(8)
    ]
    assert view.projects[0].span == "Jul 7 – Aug 31"
    assert view.projects[0].bar_fraction == 1.0
    assert view.projects[-1].bar_fraction == pytest.approx(0.3)
    assert view.more_projects == 2


@pytest.mark.parametrize(
    ("snapshot_exists", "is_running", "unavailable", "expected"),
    [
        (None, False, False, "CHECKING"),
        (True, False, False, "READY"),
        (False, False, False, "SNAPSHOT_MISSING"),
        (True, True, False, "RUNNING"),
        (True, True, True, "BLOCKED"),
    ],
)
def test_view_resolves_review_states(
    snapshot_exists: bool | None,
    is_running: bool,
    unavailable: bool,
    expected: str,
) -> None:
    view = build_artifact_run_prune_review_view(
        _review(
            unavailable_sources=("beads sidecar",) if unavailable else (),
            unavailable_source_count=1 if unavailable else 0,
        ),
        {},
        now=datetime(2026, 11, 5, 11, 33, tzinfo=UTC),
        snapshot_exists=snapshot_exists,
        is_running=is_running,
    )

    assert view.state == expected


def test_view_stale_warning_and_missing_project_labels() -> None:
    view = build_artifact_run_prune_review_view(
        _review(
            project_count=1,
            captured_at="2026-11-04T10:00:00+00:00",
        ),
        {},
        now=datetime(2026, 11, 5, 11, 0, tzinfo=UTC),
        snapshot_exists=True,
    )

    assert view.stale is True
    assert view.stale_warning == "This preview is older than 24 hours."
    assert view.projects[0].label == "Project unavailable"
    assert "project-0" not in view.projects[0].label


def test_view_keeps_a_registered_label_that_matches_its_storage_key() -> None:
    view = build_artifact_run_prune_review_view(
        _review(project_count=1),
        {"project-0": "project-0"},
        now=datetime(2026, 11, 5, 11, 33, tzinfo=UTC),
        snapshot_exists=True,
    )

    assert view.projects[0].label == "project-0"


def test_size_and_run_date_formatters() -> None:
    assert human_size(1024) == "1.0 KiB"
    assert human_size(1_048_576) == "1.0 MiB"
    assert _format_run_date("20260707000000") == "Jul 7"
    assert _format_run_date("not-a-run") == "not-a-run"
