"""Tests for the ``sase bead sync-external`` CLI handler."""

from __future__ import annotations

import argparse
from pathlib import Path

import pluggy
import pytest

from sase.bead.cli_sync_external import handle_bead_sync_external
from sase.bead.project import BeadProject
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.vcs_provider import VCSHookSpec, VCSPluginManager
from sase.vcs_provider._types import IssueWire
from sase.vcs_provider.testing import FakeIssueProvider


def _record(
    *,
    project_name: str,
    workspace_dir: str,
    display_name: str | None = None,
    aliases: list[str] | None = None,
) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=1,
        project_name=project_name,
        project_dir=f"/projects/{project_name}",
        project_file=f"/projects/{project_name}/{project_name}.sase",
        archive_file=None,
        workspace_dir=workspace_dir,
        state="enabled",
        state_explicit=True,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=aliases or [],
        display_name=display_name,
    )


def _provider(*plugins: object) -> VCSPluginManager:
    manager = pluggy.PluginManager("sase_vcs")
    manager.add_hookspecs(VCSHookSpec)
    for plugin in plugins:
        manager.register(plugin)
    return VCSPluginManager(manager)


def _issue(number: int) -> IssueWire:
    return IssueWire(
        number=number,
        title=f"Issue {number}",
        state="open",
        url=f"https://example.test/issues/{number}",
        provider_id=f"I_{number}",
        updated_at="2026-08-10T18:00:00Z",
        created_at="2026-08-10T18:00:00Z",
    )


def _install_provider(monkeypatch: pytest.MonkeyPatch, provider: object) -> None:
    monkeypatch.setattr(
        "sase.external_mirror.issues.get_vcs_provider", lambda _cwd: provider
    )
    monkeypatch.setattr(
        "sase.external_mirror.issues.supports_issue_listing", lambda _cwd: True
    )


def _namespace(
    *, project: str | None = None, dry_run: bool = False, full: bool = False
) -> argparse.Namespace:
    return argparse.Namespace(project=project, dry_run=dry_run, full=full)


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


def test_dry_run_prints_planned_creations_and_mutates_nothing(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_sync_external.list_project_records",
        lambda *a, **k: [_record(project_name="sase", workspace_dir="/repo")],
    )
    _install_provider(monkeypatch, _provider(FakeIssueProvider([_issue(42)])))

    handle_bead_sync_external(_namespace(dry_run=True))

    out = capsys.readouterr().out
    assert "sase" in out
    assert "bug:sase#42" in out
    with BeadProject(bead_store.parent.parent) as project:
        assert project.list_issues() == []


def test_project_flag_narrows_to_one_project_and_accepts_alias(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(
        "sase.bead.cli_sync_external.list_project_records",
        lambda *a, **k: [
            _record(project_name="sase", workspace_dir="/repo-a", aliases=["s"]),
            _record(project_name="sase-github", workspace_dir="/repo-b"),
        ],
    )

    def _fake_mirror(*, project_key: str, **_kwargs: object):
        seen.append(project_key)
        from sase.external_mirror.issues import MirrorReport

        return MirrorReport(project=project_key, display_name=project_key)

    monkeypatch.setattr(
        "sase.bead.cli_sync_external.run_issue_mirror_for_project", _fake_mirror
    )

    handle_bead_sync_external(_namespace(project="s"))

    assert seen == ["sase"]


def test_unknown_project_exits_non_zero_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_sync_external.list_project_records", lambda *a, **k: []
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_bead_sync_external(_namespace(project="does-not-exist"))

    assert exc_info.value.code != 0
    err = capsys.readouterr().err
    assert "does-not-exist" in err


def test_output_renders_display_name_not_project_key(
    bead_store: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_sync_external.list_project_records",
        lambda *a, **k: [
            _record(
                project_name="gh_sase-org__sase",
                workspace_dir="/repo",
                display_name="sase",
            )
        ],
    )
    _install_provider(monkeypatch, _provider(FakeIssueProvider([])))

    handle_bead_sync_external(_namespace())

    out = capsys.readouterr().out
    assert "sase" in out
    assert "gh_sase-org__sase" not in out


def test_output_shows_filtered_count_when_nonzero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from sase.external_mirror.issues import MirrorReport

    monkeypatch.setattr(
        "sase.bead.cli_sync_external.list_project_records",
        lambda *a, **k: [_record(project_name="sase", workspace_dir="/repo")],
    )
    monkeypatch.setattr(
        "sase.bead.cli_sync_external.run_issue_mirror_for_project",
        lambda **_kwargs: MirrorReport(
            project="sase", display_name="sase", issues_seen=3, unmirrored=2
        ),
    )

    handle_bead_sync_external(_namespace())

    out = capsys.readouterr().out
    assert "filtered=2" in out


def test_output_omits_filtered_when_zero(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    from sase.external_mirror.issues import MirrorReport

    monkeypatch.setattr(
        "sase.bead.cli_sync_external.list_project_records",
        lambda *a, **k: [_record(project_name="sase", workspace_dir="/repo")],
    )
    monkeypatch.setattr(
        "sase.bead.cli_sync_external.run_issue_mirror_for_project",
        lambda **_kwargs: MirrorReport(
            project="sase", display_name="sase", issues_seen=3, unmirrored=0
        ),
    )

    handle_bead_sync_external(_namespace())

    out = capsys.readouterr().out
    assert "filtered=" not in out


def test_all_degraded_projects_exit_non_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.bead.cli_sync_external.list_project_records",
        lambda *a, **k: [_record(project_name="sase", workspace_dir="")],
    )

    with pytest.raises(SystemExit) as exc_info:
        handle_bead_sync_external(_namespace())

    assert exc_info.value.code != 0
