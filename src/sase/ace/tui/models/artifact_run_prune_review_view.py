"""Pure presentation model for the ACE-run prune review modal."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sase.core.agent_artifact_run_prune_review import RunPruneReview

_ReviewState = Literal["CHECKING", "READY", "BLOCKED", "SNAPSHOT_MISSING", "RUNNING"]


@dataclass(frozen=True)
class _PruneReviewProjectRow:
    """One display-ready project aggregate."""

    label: str
    runs: int
    size_bytes: int
    size_label: str
    span: str
    bar_fraction: float


@dataclass(frozen=True)
class _ArtifactRunPruneReviewView:
    """Text and rows needed to render a prune review without I/O."""

    state: _ReviewState
    freshness: str
    stale: bool
    stale_warning: str | None
    run_count: str
    reclaimable_size: str
    project_count: str
    keep_window: str
    projects: tuple[_PruneReviewProjectRow, ...]
    more_projects: int
    unavailable_sources: tuple[str, ...]
    unavailable_source_count: int


def build_artifact_run_prune_review_view(
    review: RunPruneReview,
    display_snapshot: Mapping[str, str],
    *,
    now: datetime,
    snapshot_exists: bool | None,
    is_running: bool = False,
) -> _ArtifactRunPruneReviewView:
    """Project a review payload and cached project labels into modal content."""
    freshness, stale = _freshness(review.captured_at, now)
    if review.unavailable_source_count > 0:
        state: _ReviewState = "BLOCKED"
    elif is_running:
        state = "RUNNING"
    elif snapshot_exists is None:
        state = "CHECKING"
    elif not snapshot_exists:
        state = "SNAPSHOT_MISSING"
    else:
        state = "READY"

    named = [
        (
            _project_label(project.project, display_snapshot),
            project.project,
            project,
        )
        for project in review.projects
    ]
    named.sort(key=lambda item: (-item[2].bytes, item[0].casefold(), item[1]))
    shown = named[:8]
    largest = max((item[2].bytes for item in shown), default=0)
    projects = tuple(
        _PruneReviewProjectRow(
            label=label,
            runs=project.runs,
            size_bytes=project.bytes,
            size_label=human_size(project.bytes),
            span=f"{_format_run_date(project.oldest)} – {_format_run_date(project.newest)}",
            bar_fraction=(project.bytes / largest if largest > 0 else 0.0),
        )
        for label, _key, project in shown
    )
    return _ArtifactRunPruneReviewView(
        state=state,
        freshness=f"snapshot · {freshness}",
        stale=stale,
        stale_warning="This preview is older than 24 hours." if stale else None,
        run_count=f"{review.counts.selected:,}",
        reclaimable_size=human_size(review.reclaimable_bytes),
        project_count=f"{len(review.projects):,}",
        keep_window=(
            f"Keep newest {review.keep_recent_months:,} months "
            f"from {_month_label(review.first_kept_month)} · "
            f"{review.counts.protected:,} protected"
        ),
        projects=projects,
        more_projects=max(0, len(named) - len(projects)),
        unavailable_sources=review.unavailable_sources[:6],
        unavailable_source_count=review.unavailable_source_count,
    )


def human_size(size_bytes: int | None) -> str:
    """Format bytes with the existing KiB/MiB/GiB convention."""
    if size_bytes is None:
        return "-"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


def _format_run_date(timestamp: str) -> str:
    """Format a run timestamp such as ``20260707T12...`` as ``Jul 7``."""
    try:
        moment = datetime.strptime(timestamp[:8], "%Y%m%d")
    except ValueError:
        return timestamp
    return f"{moment.strftime('%b')} {moment.day}"


def _project_label(project: str, display_snapshot: Mapping[str, str]) -> str:
    if project not in display_snapshot:
        return "Project unavailable"
    label = display_snapshot[project]
    if not isinstance(label, str) or not label.strip():
        return "Project unavailable"
    return label.strip()


def _month_label(month: str) -> str:
    try:
        moment = datetime.strptime(month, "%Y-%m")
    except ValueError:
        return month
    return f"{moment.strftime('%b')} {moment.year}"


def _freshness(captured_at: str, now: datetime) -> tuple[str, bool]:
    try:
        captured = datetime.fromisoformat(captured_at)
    except ValueError:
        return "age unknown", False
    if captured.tzinfo is None:
        return "age unknown", False
    if now.tzinfo is None:
        now = now.replace(tzinfo=captured.tzinfo)
    seconds = max(0, int((now - captured).total_seconds()))
    if seconds < 60:
        age = "just now"
    elif seconds < 3600:
        age = f"{seconds // 60}m ago"
    elif seconds < 86400:
        age = f"{seconds // 3600}h ago"
    else:
        age = f"{seconds // 86400}d ago"
    return age, seconds > 86400


__all__ = [
    "build_artifact_run_prune_review_view",
    "human_size",
]
