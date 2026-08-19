"""Roster rendering for the generated bead pages index."""

from __future__ import annotations

from types import MappingProxyType

from sase.bead.model import (
    BeadTier,
    CloseRecord,
    Issue,
    IssueType,
    ReopenCause,
    Status,
)
from sase.bead_pages.associations import BeadAssociationIndex
from sase.bead_pages.roster import render_bead_pages_roster_bytes


def test_roster_reopen_column_reports_the_archived_close_count() -> None:
    task = Issue(
        "sase-task",
        "Flaky retry test in CI",
        issue_type=IssueType.TASK,
        close_history=[
            CloseRecord(
                closed_at="2026-07-30T09:12:04Z",
                reopened_at="2026-08-05T17:04:11Z",
                reopened_via=ReopenCause.PLUS_ONE,
                reopened_by="claude.probe",
            )
        ],
    )

    rendered = render_bead_pages_roster_bytes(
        (task,),
        BeadAssociationIndex(MappingProxyType({})),
    ).decode()

    assert (
        "| Bead | Title | Type | Task Type | Flag | Tier | Status | Created | +1"
        " | ↺ | Phases | Agents | Commits |" in rendered
    )
    assert (
        "| [sase-task](sase-task/README.md) | Flaky retry test in CI | ◆ task |"
        " · untyped | — | — | open | unknown | 0 | 1 | 0 | 0 | 0 |" in rendered
    )


def test_roster_renders_every_bead_type_with_its_shared_glyph() -> None:
    epic = Issue(
        "sase-ai",
        "Published bead pages",
        issue_type=IssueType.PLAN,
        tier=BeadTier.EPIC,
        created_at="2026-01-01T00:00:00Z",
    )
    phase = Issue(
        "sase-ai.1",
        "Pathing",
        issue_type=IssueType.PHASE,
        parent_id=epic.id,
    )
    task = Issue(
        "sase-task",
        "Fix the flaky linter",
        status=Status.READY,
        issue_type=IssueType.TASK,
    )
    flag = Issue(
        "sase-flag",
        "Remove plugin switch",
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "kind": "beta",
            "when_enabled": "on",
            "when_disabled": "off",
            "remove_when": "done",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
    )

    rendered = render_bead_pages_roster_bytes(
        (epic, phase, task, flag),
        BeadAssociationIndex(MappingProxyType({})),
    ).decode()

    # Phases are rolled into their lineage root, so only roots get a row.
    assert (
        "| [sase-ai](sase-ai/README.md) | Published bead pages | ▸ plan | — | — |"
        " epic | open | 2025-12-31 |" in rendered
    )
    assert (
        "| [sase-task](sase-task/README.md) | Fix the flaky linter | ◆ task |"
        " · untyped | — | — | ready | unknown |" in rendered
    )
    assert (
        "| [sase-flag](sase-flag/README.md) | Remove plugin switch | ◆ task | "
        "⚑ flag | plugins\\_enabled<br>2026-12-01<br>v0.19.0 | — | open | unknown |"
        in rendered
    )
    assert "sase-ai.1" not in rendered


def test_roster_flag_column_reads_task_type_fields() -> None:
    flag = Issue(
        "sase-flag",
        "Remove plugin switch",
        issue_type=IssueType.TASK,
        task_type="flag",
        task_type_fields={
            "key": "plugins_enabled",
            "kind": "beta",
            "when_enabled": "new path",
            "when_disabled": "old path",
            "remove_when": "when proven",
            "remove_by_date": "2026-12-01",
            "remove_by_release": "0.19.0",
        },
    )

    rendered = render_bead_pages_roster_bytes(
        (flag,),
        BeadAssociationIndex(MappingProxyType({})),
    ).decode()

    assert (
        "| [sase-flag](sase-flag/README.md) | Remove plugin switch | ◆ task |"
        " ⚑ flag | plugins\\_enabled<br>2026-12-01<br>v0.19.0 | — | open | unknown |"
        in rendered
    )
