"""Tests for external issue mirror bead creation and identity."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.bead.model import IssueType, PhaseSize, Status
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.vcs_provider.testing import FakeIssueProvider

from tests.external_mirror_issue_helpers import (
    beads,
    install_provider,
    issue,
    provider,
    run_mirror,
)

pytest_plugins = ["tests.external_mirror_issue_fixtures"]


def test_uncovered_issue_creates_bead_then_second_pass_is_noop(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vcs_provider = provider(
        FakeIssueProvider([issue(42, title="Fix the thing", body="Body text.")])
    )
    install_provider(monkeypatch, vcs_provider)

    report1 = run_mirror()
    assert report1.beads_created == 1
    assert report1.created_refs == ("bug:sase#42",)

    [bead] = beads(bead_store)
    assert bead.status == Status.OPEN
    assert bead.issue_type == IssueType.TASK
    assert bead.size == PhaseSize.SMALL
    assert bead.task_type == "github"
    assert bead.external_ref == "bug:sase#42"
    assert "bug:sase#42" in bead.refs
    assert bead.title == "Fix the thing"

    report2 = run_mirror()
    assert report2.beads_created == 0


def test_ref_uses_display_name_while_external_ref_uses_stable_key(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vcs_provider = provider(FakeIssueProvider([issue(42)]))
    install_provider(monkeypatch, vcs_provider)

    run_mirror(project_key="gh_sase-org__sase", display_name="sase")

    [bead] = beads(bead_store)
    assert bead.external_ref == "bug:gh_sase-org__sase#42"
    assert bead.refs == ["bug:sase#42"]


def test_cross_project_issues_do_not_collide(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vcs_provider = provider(FakeIssueProvider([issue(42)]))
    install_provider(monkeypatch, vcs_provider)

    report_a = run_mirror(project_key="sase", display_name="sase")
    report_b = run_mirror(project_key="sase-github", display_name="sase-github")

    assert report_a.beads_created == 1
    assert report_b.beads_created == 1

    mirrored_beads = beads(bead_store)
    assert {bead.external_ref for bead in mirrored_beads} == {
        "bug:sase#42",
        "bug:sase-github#42",
    }


def test_bead_with_only_bug_ref_is_recognized_as_covering(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_bead_project_for_beads_dir(bead_store) as project:
        project.create(
            "Manually linked",
            IssueType.TASK,
            task_type="bug",
            refs=["bug:sase#42"],
            size=PhaseSize.SMALL,
        )

    vcs_provider = provider(FakeIssueProvider([issue(42)]))
    install_provider(monkeypatch, vcs_provider)

    report = run_mirror()

    assert report.beads_created == 0
    [bead] = beads(bead_store)
    assert bead.task_type == "bug"


def test_flag_task_bead_bug_ref_does_not_cover_external_issue(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_bead_project_for_beads_dir(bead_store) as project:
        project.create(
            "Temporary plugin flag",
            IssueType.TASK,
            size="small",
            task_type="flag",
            refs=["bug:sase#42"],
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
    vcs_provider = provider(FakeIssueProvider([issue(42)]))
    install_provider(monkeypatch, vcs_provider)

    report = run_mirror()

    assert report.beads_created == 1
    mirrored = beads(bead_store)
    assert sum(1 for bead in mirrored if bead.task_type == "flag") == 1
    created = next(bead for bead in mirrored if bead.task_type == "github")
    assert created.external_ref == "bug:sase#42"


def test_conflict_created_between_plan_and_apply_is_detected_under_lock(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_bead_project_for_beads_dir(bead_store) as project:
        project.create(
            "Existing",
            IssueType.TASK,
            task_type="bug",
            external_ref="bug:sase#42",
            size=PhaseSize.SMALL,
        )

    # Simulate a race: the unlocked planning read (no kwargs, per issues.py's
    # call shape) sees zero beads, while the live rebuild under the lock
    # (BeadProject.list_issues always passes statuses/issue_types/tiers)
    # sees the bead created above.
    from sase.core import bead_read_facade as rust_beads

    real_list_issues = rust_beads.list_issues

    def fake_list_issues(beads_dir: object, **kwargs: object) -> list:
        if not kwargs:
            return []
        return real_list_issues(beads_dir, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "sase.external_mirror.issues.bead_read_facade.list_issues",
        fake_list_issues,
    )
    vcs_provider = provider(FakeIssueProvider([issue(42)]))
    install_provider(monkeypatch, vcs_provider)

    report = run_mirror()

    assert report.beads_created == 0
    assert report.conflicts == 1
    assert len(beads(bead_store)) == 1


def test_creation_budget_defers_then_converges_next_pass(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = [
        issue(number, updated_at=f"2026-08-10T00:{number:02d}:00Z")
        for number in range(1, 41)
    ]
    vcs_provider = provider(FakeIssueProvider(issues))
    install_provider(monkeypatch, vcs_provider)

    # Relies on the module's default budget: max_creations=25.
    report1 = run_mirror()
    assert report1.beads_created == 25
    assert report1.deferred == 15
    assert report1.checkpoint_advanced is False

    report2 = run_mirror()
    assert report2.beads_created == 15
    assert report2.deferred == 0
    assert report2.checkpoint_advanced is True

    assert len(beads(bead_store)) == 40
    assert {bead.task_type for bead in beads(bead_store)} == {"github"}


def test_missing_github_type_fails_the_run_instead_of_creating_untyped(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.plugins.required import missing_required_plugin_message
    from sase.task_types._models import TaskTypeRegistry

    monkeypatch.setattr(
        "sase.external_mirror._issue_apply.get_task_type_registry",
        lambda: TaskTypeRegistry(records=(), diagnostics=()),
    )
    vcs_provider = provider(FakeIssueProvider([issue(42, title="Fix the thing")]))
    install_provider(monkeypatch, vcs_provider)

    with pytest.raises(
        RuntimeError,
        match=missing_required_plugin_message("sase-github"),
    ):
        run_mirror()

    assert beads(bead_store) == []
