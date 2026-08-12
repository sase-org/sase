"""Tests for the external issue mirror reconciler (called directly)."""

from __future__ import annotations

from pathlib import Path

import pluggy
import pytest

from sase.bead.model import IssueType, PhaseSize, Status
from sase.bead.project import BeadProject
from sase.bead.store_locator import open_bead_project_for_beads_dir
from sase.external_mirror.auth import read_tracker_probes
from sase.external_mirror.filters import IssueFilters
from sase.external_mirror.issues import run_issue_mirror_for_project
from sase.external_mirror.state import mirror_state_document_path, read_mirror_state
from sase.vcs_provider import VCSHookSpec, VCSPluginManager
from sase.vcs_provider._types import IssueWire
from sase.vcs_provider.testing import FakeIssueProvider

_WORKSPACE_DIR = "/repo"


def _provider(*plugins: object) -> VCSPluginManager:
    manager = pluggy.PluginManager("sase_vcs")
    manager.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        manager.register(plugin)
    return VCSPluginManager(manager)


def _issue(
    number: int,
    *,
    state: str = "open",
    title: str | None = None,
    body: str = "",
    labels: tuple[str, ...] = (),
    updated_at: str = "2026-08-10T18:00:00Z",
    provider_id: str | None = None,
) -> IssueWire:
    return IssueWire(
        number=number,
        title=title if title is not None else f"Issue {number}",
        state=state,  # type: ignore[arg-type]
        body=body,
        labels=labels,
        created_at=updated_at,
        updated_at=updated_at,
        url=f"https://example.test/issues/{number}",
        provider_id=provider_id or f"I_{number}",
    )


@pytest.fixture
def bead_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "bead-store"
    with BeadProject.init(root):
        pass
    beads_dir = root / "sdd" / "beads"
    monkeypatch.setattr(
        "sase.external_mirror.issues.canonical_beads_dir_for_project",
        lambda _project: beads_dir,
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    return beads_dir


def _install_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: object,
    *,
    listing_supported: bool = True,
) -> None:
    monkeypatch.setattr(
        "sase.external_mirror.issues.get_vcs_provider", lambda _cwd: provider
    )
    monkeypatch.setattr(
        "sase.external_mirror.issues.supports_issue_listing",
        lambda _cwd: listing_supported,
    )


def _run(
    *,
    project_key: str = "sase",
    display_name: str = "sase",
    dry_run: bool = False,
    full: bool = False,
):
    return run_issue_mirror_for_project(
        project_key=project_key,
        display_name=display_name,
        workspace_dir=_WORKSPACE_DIR,
        dry_run=dry_run,
        full=full,
    )


def _beads(beads_dir: Path) -> list:
    with open_bead_project_for_beads_dir(beads_dir) as project:
        return project.list_issues()


class _RaisingProvider:
    def __init__(self, message: str) -> None:
        self._message = message

    def list_issues(self, cwd: str, state: str, limit: int) -> list[IssueWire]:
        del cwd, state, limit
        raise RuntimeError(self._message)


def test_uncovered_issue_creates_bead_then_second_pass_is_noop(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(
        FakeIssueProvider([_issue(42, title="Fix the thing", body="Body text.")])
    )
    _install_provider(monkeypatch, provider)

    report1 = _run()
    assert report1.beads_created == 1
    assert report1.created_refs == ("bug:sase#42",)

    [bead] = _beads(bead_store)
    assert bead.status == Status.OPEN
    assert bead.issue_type == IssueType.TASK
    assert bead.size == PhaseSize.SMALL
    assert bead.external_ref == "bug:sase#42"
    assert "bug:sase#42" in bead.refs
    assert bead.title == "Fix the thing"

    report2 = _run()
    assert report2.beads_created == 0


def test_ref_uses_display_name_while_external_ref_uses_stable_key(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(FakeIssueProvider([_issue(42)]))
    _install_provider(monkeypatch, provider)

    _run(project_key="gh_sase-org__sase", display_name="sase")

    [bead] = _beads(bead_store)
    assert bead.external_ref == "bug:gh_sase-org__sase#42"
    assert bead.refs == ["bug:sase#42"]


def test_cross_project_issues_do_not_collide(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(FakeIssueProvider([_issue(42)]))
    _install_provider(monkeypatch, provider)

    report_a = _run(project_key="sase", display_name="sase")
    report_b = _run(project_key="sase-github", display_name="sase-github")

    assert report_a.beads_created == 1
    assert report_b.beads_created == 1

    beads = _beads(bead_store)
    assert {bead.external_ref for bead in beads} == {
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
            refs=["bug:sase#42"],
            size=PhaseSize.SMALL,
        )

    provider = _provider(FakeIssueProvider([_issue(42)]))
    _install_provider(monkeypatch, provider)

    report = _run()

    assert report.beads_created == 0


def test_conflict_created_between_plan_and_apply_is_detected_under_lock(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with open_bead_project_for_beads_dir(bead_store) as project:
        project.create(
            "Existing",
            IssueType.TASK,
            external_ref="bug:sase#42",
            size=PhaseSize.SMALL,
        )

    # Simulate a race: the unlocked planning read (no kwargs, per issues.py's
    # call shape) sees zero beads, while the live rebuild under the lock
    # (BeadProject.list_issues always passes statuses/issue_types/tiers)
    # sees the bead created above.
    from sase.core import bead_read_facade as _rust_beads

    real_list_issues = _rust_beads.list_issues

    def _fake_list_issues(beads_dir: object, **kwargs: object) -> list:
        if not kwargs:
            return []
        return real_list_issues(beads_dir, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        "sase.external_mirror.issues.bead_read_facade.list_issues",
        _fake_list_issues,
    )
    provider = _provider(FakeIssueProvider([_issue(42)]))
    _install_provider(monkeypatch, provider)

    report = _run()

    assert report.beads_created == 0
    assert report.conflicts == 1
    assert len(_beads(bead_store)) == 1


def test_creation_budget_defers_then_converges_next_pass(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = [
        _issue(number, updated_at=f"2026-08-10T00:{number:02d}:00Z")
        for number in range(1, 41)
    ]
    provider = _provider(FakeIssueProvider(issues))
    _install_provider(monkeypatch, provider)

    # Relies on the module's default budget: max_creations=25.
    report1 = _run()
    assert report1.beads_created == 25
    assert report1.deferred == 15
    assert report1.checkpoint_advanced is False

    report2 = _run()
    assert report2.beads_created == 15
    assert report2.deferred == 0
    assert report2.checkpoint_advanced is True

    assert len(_beads(bead_store)) == 40


def test_upstream_close_appends_exactly_one_note_across_three_passes(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider1 = _provider(FakeIssueProvider([_issue(42, state="open")]))
    _install_provider(monkeypatch, provider1)
    report1 = _run()
    assert report1.beads_created == 1
    assert report1.notes_appended == 0

    provider2 = _provider(
        FakeIssueProvider(
            [_issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
        )
    )
    _install_provider(monkeypatch, provider2)
    report2 = _run()
    assert report2.notes_appended == 1

    provider3 = _provider(
        FakeIssueProvider(
            [_issue(42, state="closed", updated_at="2026-08-10T19:00:00Z")]
        )
    )
    _install_provider(monkeypatch, provider3)
    report3 = _run()
    assert report3.notes_appended == 0

    [bead] = _beads(bead_store)
    assert bead.status == Status.OPEN


def test_disappeared_issue_appends_one_stale_note(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider1 = _provider(FakeIssueProvider([_issue(42)]))
    _install_provider(monkeypatch, provider1)
    report1 = _run()
    assert report1.beads_created == 1

    provider2 = _provider(FakeIssueProvider([]))
    _install_provider(monkeypatch, provider2)
    report2 = _run(full=True)

    assert report2.notes_appended == 1
    state = read_mirror_state(
        mirror_state_document_path("issues", "sase"), project="sase"
    )
    assert state.upstream_states == {"bug:sase#42": "absent"}


def test_provider_error_appends_no_notes_and_leaves_upstream_states_untouched(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider1 = _provider(FakeIssueProvider([_issue(42)]))
    _install_provider(monkeypatch, provider1)
    _run()

    provider2 = _provider(FakeIssueProvider([]))
    _install_provider(monkeypatch, provider2)
    _run(full=True)
    state_after_disappearance = read_mirror_state(
        mirror_state_document_path("issues", "sase"), project="sase"
    )

    _install_provider(
        monkeypatch, _RaisingProvider("gh issue list: connection reset by peer")
    )
    report3 = _run(full=True)

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
    provider = _provider(
        FakeIssueProvider(
            [
                _issue(1, labels=("bug",)),
                _issue(2, labels=("question",)),
            ]
        )
    )
    _install_provider(monkeypatch, provider)

    report = _run()

    assert report.beads_created == 1
    assert report.unmirrored == 1


def test_filter_change_forces_reexamination_of_previously_dropped_issues(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = [_issue(1, labels=("bug",)), _issue(2, labels=("question",))]
    provider = _provider(FakeIssueProvider(issues))
    _install_provider(monkeypatch, provider)

    monkeypatch.setattr(
        "sase.external_mirror.issues.issue_filters",
        lambda: IssueFilters(label_globs=("!question",)),
    )
    report1 = _run()
    assert report1.beads_created == 1
    assert report1.unmirrored == 1
    assert report1.checkpoint_advanced is True

    # Same provider listing and same filter: hits the unchanged-upstream
    # early return and does no new work.
    report2 = _run()
    assert report2.beads_created == 0
    assert report2.checkpoint_advanced is True

    # Clearing the filter changes its fingerprint, so the early return is
    # skipped for one pass and #2 becomes includable.
    monkeypatch.setattr(
        "sase.external_mirror.issues.issue_filters",
        lambda: IssueFilters(),
    )
    report3 = _run()

    assert report3.beads_created == 1
    assert report3.unmirrored == 0
    assert len(_beads(bead_store)) == 2


def test_dry_run_writes_nothing_but_reports_created_refs(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _provider(FakeIssueProvider([_issue(42)]))
    _install_provider(monkeypatch, provider)

    report = _run(dry_run=True)

    assert report.created_refs == ("bug:sase#42",)
    assert report.beads_created == 0
    assert _beads(bead_store) == []
    assert not mirror_state_document_path("issues", "sase").exists()


def test_provider_auth_error_records_probe_and_sets_backoff(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del bead_store
    _install_provider(
        monkeypatch,
        _RaisingProvider(
            "gh issue list: GitHub authentication required; run `gh auth login`"
        ),
    )

    report = _run()

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
    _install_provider(monkeypatch, _provider(), listing_supported=False)

    report = _run()

    assert report.degraded == "unsupported_provider"
    probes = read_tracker_probes()
    assert probes["sase"].outcome == "unsupported"
