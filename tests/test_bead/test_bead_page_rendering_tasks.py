"""Task-bead specific sections on generated bead pages."""

from __future__ import annotations

from types import MappingProxyType
from typing import cast

from sase.bead.model import (
    CloseRecord,
    Issue,
    IssueType,
    PhaseSize,
    ReopenCause,
    Resolution,
    Status,
    TaskPlusOneEvidence,
)
from sase.bead.project import BeadProject
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.rendering import render_bead_page
from tests.test_bead.bead_page_rendering_test_helpers import ReferenceLinks, View


def test_task_bead_page_renders_the_task_identity_and_ready_status() -> None:
    task = Issue(
        "sase-task",
        "Fix the flaky linter",
        status=Status.READY,
        issue_type=IssueType.TASK,
        size=PhaseSize.SMALL,
        description="Discovered while landing sase-ai.",
    )
    view = View((task,))

    rendered = render_bead_page(
        cast(BeadProject, view),
        task,
        BeadAssociationIndex(MappingProxyType({})),
    )

    assert "**Status:** ◇ ready · **Type:** ◆ task" in rendered
    assert "**Size:** small" in rendered
    assert "[Bead Pages](../README.md) / sase-task" in rendered


def test_task_bead_page_renders_bounded_linked_plus_one_callouts() -> None:
    task = Issue(
        "sase-task",
        "Fix the stale cache",
        status=Status.READY,
        issue_type=IssueType.TASK,
        size=PhaseSize.MEDIUM,
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp="2026-08-01T15:00:00Z",
                reporter="agent.beta",
                note="# Reproduced\n```unsafe",
                refs=("plans:202608/cache.md",),
            )
        ],
    )
    view = View((task,))

    rendered = render_bead_page(
        cast(BeadProject, view),
        task,
        BeadAssociationIndex(MappingProxyType({})),
        link_resolver=ReferenceLinks(),
    )

    assert "**+1 reports:** +1" in rendered
    assert "## +1 Evidence" in rendered
    assert "> **+1** by `agent.beta` · 2026-08-01 11:00:00 EDT" in rendered
    assert "> \\# Reproduced" in rendered
    assert "> \\```unsafe" in rendered
    assert (
        "[plans:202608/cache.md](https://example.test/plans/202608/cache.md)"
        in rendered
    )


def test_task_bead_page_marks_post_close_plus_one_callouts() -> None:
    task = Issue(
        "sase-task",
        "Fix the stale cache",
        status=Status.CLOSED,
        issue_type=IssueType.TASK,
        size=PhaseSize.MEDIUM,
        closed_at="2026-08-01T14:00:00Z",
        resolution=Resolution.DONE,
        plus_one_evidence=[
            TaskPlusOneEvidence(
                timestamp="2026-08-01T15:00:00Z",
                reporter="agent.beta",
                note="Saw this before the close landed.",
                observed_since="2026-01-01T00:00:00Z",
            )
        ],
    )
    view = View((task,))

    rendered = render_bead_page(
        cast(BeadProject, view),
        task,
        BeadAssociationIndex(MappingProxyType({})),
    )

    assert "**Post-close +1:** +1 after close" in rendered
    assert (
        "> **+1** by `agent.beta` · 2026-08-01 11:00:00 EDT · **post-close evidence**"
    ) in rendered
    assert "> **Observed since:** 2025-12-31 19:00:00 EST" in rendered


def test_task_bead_page_renders_bounded_previously_closed_callouts() -> None:
    task = Issue(
        "sase-task",
        "Flaky retry test in CI",
        status=Status.READY,
        issue_type=IssueType.TASK,
        size=PhaseSize.SMALL,
        description="Discovered while investigating flaky retries.",
        close_history=[
            CloseRecord(
                closed_at="2026-06-01T00:00:00Z",
                reopened_at="2026-06-10T00:00:00Z",
                reopened_via=ReopenCause.OPEN,
            ),
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at="2026-08-05T17:04:11Z",
                reopened_via=ReopenCause.PLUS_ONE,
                close_reason="# injected\nNot reproducible on main.",
                resolution=Resolution.CANCELED,
                reopened_by="claude.probe",
            ),
        ],
    )
    view = View((task,))

    rendered = render_bead_page(
        cast(BeadProject, view),
        task,
        BeadAssociationIndex(MappingProxyType({})),
    )

    assert "**↺ Reopened:** ↺2" in rendered
    assert "## Previously Closed" in rendered
    assert rendered.index("## Previously Closed") < rendered.index("## Description")
    assert "> ↺ Closed 2026-07-30T09:12:04Z · canceled" in rendered
    assert "> \\# injected" in rendered
    assert "> Reopened 2026-08-05T17:04:11Z by a +1 from @claude.probe" in rendered
    assert "> ↺ Closed 2026-06-01T00:00:00Z · (unrecorded)" in rendered
    assert "> Reopened 2026-06-10T00:00:00Z by `sase bead open`" in rendered
    # Newest record renders first even though storage is oldest-first.
    assert rendered.index("2026-07-30T09:12:04Z") < rendered.index(
        "2026-06-01T00:00:00Z"
    )


def test_previously_closed_section_omits_reason_line_when_none_was_recorded() -> None:
    task = Issue(
        "sase-task",
        "Flaky retry test in CI",
        issue_type=IssueType.TASK,
        close_history=[
            CloseRecord(
                closed_at="2026-06-01T00:00:00Z",
                reopened_at="2026-06-10T00:00:00Z",
                reopened_via=ReopenCause.OPEN,
            ),
        ],
    )
    view = View((task,))

    rendered = render_bead_page(
        cast(BeadProject, view),
        task,
        BeadAssociationIndex(MappingProxyType({})),
    )

    assert "> (none)" in rendered
