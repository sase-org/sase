"""Memory-only stranded-work presentation for the Beads pane."""

from __future__ import annotations

from time import time

from rich.text import Text

from sase.bead.stranded_presentation import (
    STRANDED_BREADCRUMB_STYLE,
    STRANDED_GLYPH,
    STRANDED_LEAF_STYLE,
    stranded_age_label,
)
from sase.core.stranded_work_facade import StrandedWorkVerdict

from ...models.agent_stranded import cached_stranded_report
from .beads_data_models import BeadsSnapshot


def cached_bead_verdict(project: str, bead_id: str) -> StrandedWorkVerdict | None:
    """Look up a bead in the shared report without touching its store."""
    snapshot = cached_stranded_report(project)
    if snapshot is None:
        return None
    return next((v for v in snapshot.report.verdicts if v.bead_id == bead_id), None)


def stranded_badge(verdict: StrandedWorkVerdict | None) -> Text:
    """Render the leaf age or the quieter ancestor breadcrumb."""
    if verdict is None:
        return Text()
    if verdict.state == "stranded":
        age = stranded_age_label(verdict.since, time())
        return Text(f" {STRANDED_GLYPH} {age}".rstrip(), style=STRANDED_LEAF_STYLE)
    if verdict.state == "blocked":
        return Text(f" {STRANDED_GLYPH}", style=STRANDED_BREADCRUMB_STYLE)
    return Text()


def epic_stranded_style(project: str, bead_id: str) -> str | None:
    """Use the reducer's ancestry, including leaves hidden by folds or filters."""
    snapshot = cached_stranded_report(project)
    if snapshot is None:
        return None
    verdict = cached_bead_verdict(project, bead_id)
    leaf_ids = set(verdict.blocked_by) if verdict is not None else set()
    leaves = tuple(
        v
        for v in snapshot.report.verdicts
        if v.state == "stranded"
        and (v.bead_id == bead_id or v.parent_id == bead_id or v.bead_id in leaf_ids)
    )
    if not leaves:
        return None
    if any(v.bead_id == bead_id or v.parent_id == bead_id for v in leaves):
        return STRANDED_LEAF_STYLE
    return STRANDED_BREADCRUMB_STYLE


def beads_stranded_count(snapshot: BeadsSnapshot) -> int:
    """Count leaves once per project, including standalone task beads."""
    return sum(
        len(report.report.stranded_ids)
        for project in set(snapshot.projects)
        if (report := cached_stranded_report(project)) is not None
    )


def beads_stranded_signature(snapshot: BeadsSnapshot) -> tuple[object, ...]:
    """Diff displayed facts and age labels, never the collector timestamp."""
    now = time()
    return tuple(
        (project, v, stranded_age_label(v.since, now))
        for project in snapshot.projects
        if (report := cached_stranded_report(project)) is not None
        for v in report.report.verdicts
        if v.state in {"stranded", "blocked"} or v.blocked_by
    )
