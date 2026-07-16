"""Shared test helpers for ``sase repo`` handler tests."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.main.workspace_handler_context import ProjectContext
from sase.repo_inventory import RepoCloneRecord, RepoRecord
from sase.workspace_provider.store import WorkspaceStore


def project_context(tmp_path: Path) -> ProjectContext:
    primary = tmp_path / "demo"
    primary.mkdir(exist_ok=True)
    return ProjectContext(
        project_name="demo",
        project_file=str(tmp_path / "demo.sase"),
        primary_workspace_dir=str(primary),
        store=WorkspaceStore(str(primary)),
    )


def repo_record(
    tmp_path: Path,
    *,
    name: str,
    kind: str,
    slug: str | None = None,
    clones: tuple[RepoCloneRecord, ...] = (),
) -> RepoRecord:
    path = tmp_path / f"{kind}-{name}"
    path.mkdir(parents=True, exist_ok=True)
    return RepoRecord(
        name=name,
        kind=kind,  # type: ignore[arg-type]
        project="demo",
        project_key="demo",
        path=str(path),
        exists=True,
        auto_clone=False,
        description=None,
        source="test",
        env_name=None,
        slug=slug,
        clones=clones,
    )


def project_record(name: str, workspace_dir: Path) -> ProjectRecordWire:
    return ProjectRecordWire(
        schema_version=3,
        project_name=name,
        project_dir=str(workspace_dir.parent / f"project-{name}"),
        project_file=str(workspace_dir.parent / f"project-{name}" / f"{name}.sase"),
        archive_file=None,
        workspace_dir=str(workspace_dir),
        state="enabled",
        state_explicit=False,
        system_managed=False,
        active_claim_count=0,
        launchable=True,
        aliases=[],
        warnings=[],
        parse_warnings=[],
        display_name=None,
        is_project=True,
        vcs_kind="git",
    )


def init_git_repo(path: Path) -> None:
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"], cwd=path, check=True
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=path, check=True)
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=path, check=True)
