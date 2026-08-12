"""Tests for external issue mirror reconciliation controls and failures."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import Status
from sase.external_mirror.auth import read_tracker_probes
from sase.external_mirror.filters import IssueFilters
from sase.external_mirror.state import mirror_state_document_path, read_mirror_state
from sase.vcs_provider.testing import FakeIssueProvider

from tests.external_mirror_issue_helpers import (
    RaisingProvider,
    beads,
    install_provider,
    issue,
    provider,
    run_mirror,
)

pytest_plugins = ["tests.external_mirror_issue_fixtures"]


def test_disappeared_issue_appends_one_stale_note(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider1 = provider(FakeIssueProvider([issue(42)]))
    install_provider(monkeypatch, provider1)
    report1 = run_mirror()
    assert report1.beads_created == 1

    provider2 = provider(FakeIssueProvider([]))
    install_provider(monkeypatch, provider2)
    report2 = run_mirror(full=True)

    assert report2.notes_appended == 1
    assert report2.beads_closed == 0
    [bead] = beads(bead_store)
    assert bead.status == Status.OPEN
    state = read_mirror_state(
        mirror_state_document_path("issues", "sase"), project="sase"
    )
    assert state.upstream_states == {"bug:sase#42": "absent"}


def test_provider_error_appends_no_notes_and_leaves_upstream_states_untouched(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider1 = provider(FakeIssueProvider([issue(42)]))
    install_provider(monkeypatch, provider1)
    run_mirror()

    provider2 = provider(FakeIssueProvider([]))
    install_provider(monkeypatch, provider2)
    run_mirror(full=True)
    state_after_disappearance = read_mirror_state(
        mirror_state_document_path("issues", "sase"), project="sase"
    )

    install_provider(
        monkeypatch, RaisingProvider("gh issue list: connection reset by peer")
    )
    report3 = run_mirror(full=True)

    assert report3.degraded == "unavailable"
    assert report3.notes_appended == 0
    state_after_error = read_mirror_state(
        mirror_state_document_path("issues", "sase"), project="sase"
    )
    assert (
        state_after_error.upstream_states == state_after_disappearance.upstream_states
    )


def test_exclude_labels_skips_and_counts_unmirrored(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "sase.external_mirror.issues.issue_filters",
        lambda: IssueFilters(label_globs=("!question",)),
    )
    vcs_provider = provider(
        FakeIssueProvider(
            [
                issue(1, labels=("bug",)),
                issue(2, labels=("question",)),
            ]
        )
    )
    install_provider(monkeypatch, vcs_provider)

    report = run_mirror()

    assert report.beads_created == 1
    assert report.unmirrored == 1


def test_filter_change_forces_reexamination_of_previously_dropped_issues(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = [issue(1, labels=("bug",)), issue(2, labels=("question",))]
    vcs_provider = provider(FakeIssueProvider(issues))
    install_provider(monkeypatch, vcs_provider)

    monkeypatch.setattr(
        "sase.external_mirror.issues.issue_filters",
        lambda: IssueFilters(label_globs=("!question",)),
    )
    report1 = run_mirror()
    assert report1.beads_created == 1
    assert report1.unmirrored == 1
    assert report1.checkpoint_advanced is True

    # Same provider listing and same filter: hits the unchanged-upstream
    # early return and does no new work.
    report2 = run_mirror()
    assert report2.beads_created == 0
    assert report2.checkpoint_advanced is True

    # Clearing the filter changes its fingerprint, so the early return is
    # skipped for one pass and #2 becomes includable.
    monkeypatch.setattr(
        "sase.external_mirror.issues.issue_filters",
        IssueFilters,
    )
    report3 = run_mirror()

    assert report3.beads_created == 1
    assert report3.unmirrored == 0
    assert len(beads(bead_store)) == 2


def test_dry_run_writes_nothing_but_reports_created_refs(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vcs_provider = provider(FakeIssueProvider([issue(42)]))
    install_provider(monkeypatch, vcs_provider)

    report = run_mirror(dry_run=True)

    assert report.created_refs == ("bug:sase#42",)
    assert report.beads_created == 0
    assert beads(bead_store) == []
    assert not mirror_state_document_path("issues", "sase").exists()


def test_provider_auth_error_records_probe_and_sets_backoff(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del bead_store
    install_provider(
        monkeypatch,
        RaisingProvider(
            "gh issue list: GitHub authentication required; run `gh auth login`"
        ),
    )

    report = run_mirror()

    assert report.degraded == "auth_error"
    probes = read_tracker_probes()
    assert probes["sase"].outcome == "auth_error"
    state = read_mirror_state(
        mirror_state_document_path("issues", "sase"), project="sase"
    )
    assert state.failures == 1
    assert state.next_attempt_at
    assert state.watermark_updated_at == ""


def test_unsupported_provider_records_probe_and_degrades(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del bead_store
    install_provider(monkeypatch, provider(), listing_supported=False)

    report = run_mirror()

    assert report.degraded == "unsupported_provider"
    probes = read_tracker_probes()
    assert probes["sase"].outcome == "unsupported"
