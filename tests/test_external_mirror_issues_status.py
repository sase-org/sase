"""Tests for status reconciliation of mirrored external issues."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import BeadTier, IssueType, PhaseSize, Resolution, Status
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.external_mirror.issues import DEFAULT_BUDGET
from sase.external_mirror.state import mirror_state_document_path, read_mirror_state
from sase.vcs_provider.testing import FakeIssueProvider

from tests.external_mirror_issue_helpers import (
    beads,
    create_mirrored_bead,
    install_provider,
    issue,
    provider,
    run_mirror,
    show_bead,
)

pytest_plugins = ["tests.external_mirror_issue_fixtures"]


def test_upstream_close_appends_exactly_one_note_across_three_passes(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider1 = provider(FakeIssueProvider([issue(42, state="open")]))
    install_provider(monkeypatch, provider1)
    report1 = run_mirror()
    assert report1.beads_created == 1
    assert report1.notes_appended == 0

    provider2 = provider(
        FakeIssueProvider(
            [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
        )
    )
    install_provider(monkeypatch, provider2)
    report2 = run_mirror()
    assert report2.notes_appended == 1
    assert report2.beads_closed == 1
    assert report2.closed_refs == ("bug:sase#42",)

    provider3 = provider(
        FakeIssueProvider(
            [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
        )
    )
    install_provider(monkeypatch, provider3)
    report3 = run_mirror()
    assert report3.notes_appended == 0

    [bead] = beads(bead_store)
    assert bead.status == Status.CLOSED
    assert bead.task_type == "github"
    assert "open -> closed" in bead.notes
    assert "Closed this mirrored bead to match." in bead.notes


def test_untyped_mirrored_bead_still_reconciles_when_github_type_is_absent(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.task_types._models import TaskTypeRegistry

    create_mirrored_bead(bead_store, number=42)
    monkeypatch.setattr(
        "sase.external_mirror._issue_apply.get_task_type_registry",
        lambda: TaskTypeRegistry(records=(), diagnostics=()),
    )
    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    seeded = run_mirror()
    assert seeded.beads_created == 0

    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )

    report = run_mirror()

    assert report.beads_created == 0
    assert report.beads_closed == 1
    [bead] = beads(bead_store)
    assert bead.status == Status.CLOSED
    assert bead.task_type == ""


def test_upstream_reopen_reopens_mirrored_bead(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    run_mirror()
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )
    run_mirror()

    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="open", updated_at="2026-08-10T20:00:00Z")]
            )
        ),
    )
    report = run_mirror()

    assert report.notes_appended == 1
    assert report.beads_reopened == 1
    assert report.reopened_refs == ("bug:sase#42",)
    [bead] = beads(bead_store)
    assert bead.status == Status.OPEN
    assert "closed -> open" in bead.notes
    assert "Reopened this mirrored bead to match." in bead.notes


def test_mirrored_status_round_trip_records_each_transition(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    run_mirror()
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )
    run_mirror()
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="open", updated_at="2026-08-10T20:00:00Z")]
            )
        ),
    )
    run_mirror()
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T21:00:00Z")]
            )
        ),
    )
    report = run_mirror()

    assert report.beads_closed == 1
    [bead] = beads(bead_store)
    assert bead.status == Status.CLOSED
    assert bead.notes.count("changed state:") == 3


def test_referenced_only_bead_gets_note_but_status_stays_open(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_bead_project_for_beads_dir(bead_store) as project:
        project.create(
            "Manually linked",
            IssueType.TASK,
            refs=["bug:sase#42"],
            size=PhaseSize.SMALL,
        )

    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    run_mirror()
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )
    report = run_mirror()

    assert report.notes_appended == 1
    assert report.beads_closed == 0
    [bead] = beads(bead_store)
    assert bead.status == Status.OPEN
    assert "This bead's status is unchanged; reconcile deliberately." in bead.notes


@pytest.mark.parametrize("status", [Status.IN_PROGRESS, Status.CLAIMED])
def test_working_mirrored_bead_gets_note_but_status_is_unchanged(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, status: Status
) -> None:
    bead_id = create_mirrored_bead(bead_store, status=status)
    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    run_mirror()

    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )
    report = run_mirror()
    report2 = run_mirror()

    assert report.notes_appended == 1
    assert report.beads_closed == 0
    assert report2.notes_appended == 0
    bead = show_bead(bead_store, bead_id)
    assert bead.status == status
    assert "status is unchanged (an agent is working this bead)" in bead.notes


def test_mirrored_bead_with_unclosed_child_gets_note_but_status_stays_open(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_bead_project_for_beads_dir(bead_store) as project:
        parent = project.create(
            "Parent",
            IssueType.PLAN,
            refs=["bug:sase#42"],
            external_ref="bug:sase#42",
            tier=BeadTier.EPIC,
        )
        project.create(
            "Child",
            IssueType.PHASE,
            parent.id,
            size=PhaseSize.SMALL,
        )

    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    run_mirror()
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )
    report = run_mirror()
    report2 = run_mirror()

    assert report.notes_appended == 1
    assert report.beads_closed == 0
    assert report2.notes_appended == 0
    bead = show_bead(bead_store, parent.id)
    assert bead.status == Status.OPEN
    assert "status is unchanged (the bead has unclosed descendants)" in bead.notes


def test_human_closed_mirrored_bead_gets_note_but_is_not_reclosed(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bead_id = create_mirrored_bead(bead_store)
    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    run_mirror()
    with open_bead_project_for_beads_dir(bead_store) as project:
        project.close([bead_id], resolution=Resolution.DONE)

    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )
    report = run_mirror()
    report2 = run_mirror()

    assert report.notes_appended == 1
    assert report.beads_closed == 0
    assert report2.notes_appended == 0
    bead = show_bead(bead_store, bead_id)
    assert bead.status == Status.CLOSED
    assert "status is unchanged (the bead is already closed)" in bead.notes


def test_status_race_between_plan_and_apply_demotes_to_note_only(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    run_mirror()

    from sase.core import bead_read_facade as rust_beads

    real_list_issues = rust_beads.list_issues
    raced = False

    def fake_list_issues(beads_dir: object, **kwargs: object) -> list:
        nonlocal raced
        planned = real_list_issues(beads_dir, **kwargs)  # type: ignore[arg-type]
        if not kwargs and not raced:
            raced = True
            with open_bead_project_for_beads_dir(bead_store) as project:
                project.update(
                    planned[0].id,
                    status=Status.IN_PROGRESS.value,
                    assignee="agent",
                )
        return planned

    monkeypatch.setattr(
        "sase.external_mirror.issues.bead_read_facade.list_issues",
        fake_list_issues,
    )
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )

    report = run_mirror()

    assert report.notes_appended == 1
    assert report.beads_closed == 0
    [bead] = beads(bead_store)
    assert bead.status == Status.IN_PROGRESS
    assert "status is unchanged (an agent is working this bead)" in bead.notes


def test_dry_run_reports_status_transition_and_leaves_state_untouched(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_provider(monkeypatch, provider(FakeIssueProvider([issue(42)])))
    run_mirror()
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
            )
        ),
    )

    report = run_mirror(dry_run=True)

    assert report.closed_refs == ("bug:sase#42",)
    assert report.beads_closed == 0
    [bead] = beads(bead_store)
    assert bead.status == Status.OPEN
    assert bead.notes == ""
    state = read_mirror_state(
        mirror_state_document_path("issues", "sase"), project="sase"
    )
    assert state.upstream_states == {"bug:sase#42": "open"}


def test_status_transitions_are_limited_by_note_budget_and_converge(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_provider(
        monkeypatch,
        provider(FakeIssueProvider([issue(1), issue(2)])),
    )
    run_mirror()
    install_provider(
        monkeypatch,
        provider(
            FakeIssueProvider(
                [
                    issue(1, state="closed", updated_at="2026-08-10T19:00:00Z"),
                    issue(2, state="closed", updated_at="2026-08-10T19:01:00Z"),
                ]
            )
        ),
    )
    budget = DEFAULT_BUDGET.__class__(max_notes=1)

    report1 = run_mirror(budget=budget)
    report2 = run_mirror(budget=budget)

    assert report1.beads_closed == 1
    assert report1.deferred == 1
    assert report1.checkpoint_advanced is False
    assert report2.beads_closed == 1
    assert report2.deferred == 0
    assert report2.checkpoint_advanced is True
    assert {bead.status for bead in beads(bead_store)} == {Status.CLOSED}
    assert (
        sum(
            bead.notes.count("Closed this mirrored bead to match.")
            for bead in beads(bead_store)
        )
        == 2
    )
