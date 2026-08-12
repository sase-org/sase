"""CLI coverage for ``sase patch sync-external``."""

from __future__ import annotations

import argparse
from pathlib import Path

from sase.core.project_lifecycle_wire import (
    PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
    ProjectRecordWire,
)
from sase.external_mirror.report import MirrorReport
from sase.main.patch_handler import _handle_sync_external


def _project_record(
    tmp_path: Path,
    *,
    project_name: str = "proj",
    display_name: str = "Proj",
    workspace_dir: str | None = "/repo",
    aliases: list[str] | None = None,
) -> ProjectRecordWire:
    project_dir = tmp_path / project_name
    return ProjectRecordWire(
        schema_version=PROJECT_LIFECYCLE_WIRE_SCHEMA_VERSION,
        project_name=project_name,
        project_dir=str(project_dir),
        project_file=str(project_dir / f"{project_name}.sase"),
        archive_file=str(project_dir / f"{project_name}-archive.sase"),
        workspace_dir=workspace_dir,
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=list(aliases or ()),
        display_name=display_name,
        is_project=True,
        vcs_kind="git",
    )


def _args(
    *,
    dry_run: bool = False,
    full: bool = False,
    project: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        command="patch",
        patch_subcommand="sync-external",
        changespec_subcommand="sync-external",
        dry_run=dry_run,
        full=full,
        project=project,
    )


def test_sync_external_dry_run_reports_selected_project(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    calls: list[dict[str, object]] = []
    record = _project_record(tmp_path, aliases=["alias-proj"])

    monkeypatch.setattr(
        "sase.main.patch_handler.list_project_records",
        lambda *_args, **_kwargs: [record],
        raising=False,
    )
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )
    monkeypatch.setattr(
        "sase.project_aliases.resolve_project_alias_ref",
        lambda value: value,
    )
    monkeypatch.setattr(
        "sase.main.patch_handler.get_vcs_provider",
        lambda _workspace_dir: object(),
    )

    def _sync(**kwargs: object) -> MirrorReport:
        calls.append(kwargs)
        return MirrorReport(fetched=3, seen=3, created=1, skipped=2)

    monkeypatch.setattr(
        "sase.external_mirror.pr_sync.sync_external_pull_requests",
        _sync,
    )

    exit_code = _handle_sync_external(
        _args(dry_run=True, full=True, project="alias-proj")
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Dry run:" in output
    assert "Proj" in output
    assert "3" in output
    assert calls[0]["project_key"] == "proj"
    assert calls[0]["dry_run"] is True
    assert calls[0]["full"] is True


def test_sync_external_reports_missing_workspace(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    record = _project_record(tmp_path, workspace_dir=None)
    monkeypatch.setattr(
        "sase.core.project_lifecycle_facade.list_project_records",
        lambda *_args, **_kwargs: [record],
    )

    exit_code = _handle_sync_external(_args())

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "missing_workspa" in output
