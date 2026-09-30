"""Shared setup helpers for the repo-inventory test modules.

Split from ``tests.test_repo_inventory``; the original module re-exports its
tests so its import path keeps working.

Names are public so the ``test_repo_inventory_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.workspace_provider.registry import WorkspaceEntry


def set_github_origin(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/acme/widget.git",
        ],
        cwd=path,
        check=True,
    )


def project_record(
    tmp_path: Path,
    *,
    key: str = "gh_acme__widget",
    display_name: str = "widget",
    state: str = "enabled",
) -> ProjectRecordWire:
    project_dir = tmp_path / "projects" / key
    project_dir.mkdir(parents=True)
    primary = tmp_path / display_name
    primary.mkdir()
    project_file = project_dir / f"{key}.sase"
    project_file.write_text(f"WORKSPACE_DIR: {primary}\n", encoding="utf-8")
    return ProjectRecordWire(
        schema_version=3,
        project_name=key,
        project_dir=str(project_dir),
        project_file=str(project_file),
        archive_file=None,
        workspace_dir=str(primary),
        state=state,
        state_explicit=state == "disabled",
        system_managed=False,
        active_claim_count=0,
        launchable=state == "enabled",
        display_name=display_name,
        is_project=True,
        vcs_kind="gh",
    )


def workspace_entry(path: Path) -> WorkspaceEntry:
    return WorkspaceEntry(
        checkout_dir=str(path),
        materialization="git-clone",
        role="claim",
        created_at=1.0,
        last_used_at=1.0,
    )
