from __future__ import annotations

from pathlib import Path
import subprocess

import pluggy
import pytest

from sase.workspace_provider._hookspec import WorkspaceHookSpec
from sase.workspace_provider._plugin_manager import WorkspacePluginManager
import sase.workspace_provider._registry as workspace_registry


def install_workspace_plugin(monkeypatch: pytest.MonkeyPatch, plugin: object) -> None:
    pm = pluggy.PluginManager("sase_workspace")
    pm.add_hookspecs(WorkspaceHookSpec)
    pm.register(plugin)
    monkeypatch.setattr(workspace_registry, "_manager", WorkspacePluginManager(pm))
    workspace_registry.get_all_workflow_metadata.cache_clear()


def git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def init_git_identity(repo: Path) -> None:
    git(["config", "user.email", "sase-test@example.com"], repo)
    git(["config", "user.name", "SASE Test"], repo)
    git(["config", "commit.gpgsign", "false"], repo)


def init_bare_repo(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


def clone(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(source), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    init_git_identity(dest)


def commit_all(repo: Path, message: str) -> None:
    git(["add", "-A"], repo)
    git(["commit", "-m", message], repo)


def build_separate_repo_clones(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Build a companion bare repo, primary clone, and stale workspace clone."""
    companion = tmp_path / "companion.git"
    primary_sdd = tmp_path / "repo" / ".sase" / "sdd"
    workspace_sdd = tmp_path / "repo_2" / ".sase" / "sdd"

    init_bare_repo(companion)

    clone(companion, primary_sdd)
    (primary_sdd / "README.md").write_text("# SDD store\n", encoding="utf-8")
    commit_all(primary_sdd, "Initialize SDD store")
    git(["push", "-u", "origin", "main"], primary_sdd)

    # Clone the workspace copy while the companion is still at the initial commit.
    clone(companion, workspace_sdd)

    # The primary store advances with the just-committed tale and pushes it.
    tale = primary_sdd / "plans" / "202607" / "feature.md"
    tale.parent.mkdir(parents=True)
    tale.write_text("# Plan\n", encoding="utf-8")
    commit_all(primary_sdd, "Add tale")
    git(["push"], primary_sdd)

    return companion, primary_sdd, workspace_sdd
