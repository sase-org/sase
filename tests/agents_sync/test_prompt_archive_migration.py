"""Tests for historical plans-sidecar prompt migration."""

from __future__ import annotations

from pathlib import Path
import subprocess

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.migration import (
    _migrate_prompt_archive_repositories,
)
from sase.agents_sync.prompt_archive.validation import validate_prompt_archive
from sase.sdd.links import validate_sdd_tree


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(repo: Path, remote: str) -> None:
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "remote", "add", "origin", remote)
    (repo / ".gitkeep").write_text("", encoding="utf-8")
    _git(repo, "add", ".gitkeep")
    _git(repo, "commit", "-m", "initial")


def _target(agents: Path, workspace: Path) -> ProjectTarget:
    return ProjectTarget(
        project_key="project-key",
        project="Project",
        primary_checkout=workspace,
        primary_roots=(workspace,),
        sidecar_path=agents,
        remote_url="https://github.com/example/project--agents.git",
    )


def _commit_fixtures(*repos: Path) -> None:
    for repo in repos:
        _git(repo, "add", "--all")
        _git(repo, "commit", "-m", "fixtures")


def test_migration_is_dry_run_complete_and_idempotent(tmp_path: Path) -> None:
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    workspace = tmp_path / "workspace"
    _init_repo(plans, "https://github.com/example/project--plans.git")
    _init_repo(agents, "https://github.com/example/project--agents.git")
    nested = plans / "202608/prompts/paired.md"
    nested.parent.mkdir(parents=True)
    nested.write_text(
        "- **PLAN:** [../202608/paired.md](../paired.md)\n\n# Paired prompt\n",
        encoding="utf-8",
    )
    plan = plans / "202608/paired.md"
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [202608/prompts/paired.md](prompts/paired.md)\n\n"
        "# Paired plan\n",
        encoding="utf-8",
    )
    legacy = plans / "prompts/202607/unpaired.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("# Unpaired prompt\n", encoding="utf-8")
    _commit_fixtures(plans)
    target = _target(agents, workspace)

    preview = _migrate_prompt_archive_repositories(target, plans)

    assert preview.write is False
    assert preview.prompts_moved == 2
    assert preview.plans_relinked == 1
    assert len(preview.skipped) == 1
    assert "paired plan is missing" in preview.skipped[0].reason
    assert nested.is_file()
    assert not (agents / "prompts/202608/paired.md").exists()

    applied = _migrate_prompt_archive_repositories(target, plans, write=True)

    assert applied.prompts_moved == 2
    assert applied.months_committed == 2
    assert not nested.exists()
    assert not legacy.exists()
    archived = agents / "prompts/202608/paired.md"
    assert "project--plans/blob/main/202608/paired.md" in archived.read_text()
    assert "ARTIFACTS" not in archived.read_text()
    assert "project--agents/blob/main/prompts/202608/paired.md" in plan.read_text()
    assert (agents / "prompts/202608/README.md").is_file()
    assert validate_prompt_archive(agents, plans_repo=plans).ok
    assert validate_sdd_tree(str(plans)).ok

    repeated = _migrate_prompt_archive_repositories(target, plans, write=True)

    assert repeated.prompts_moved == 0
    assert repeated.plans_relinked == 0
    assert repeated.months_committed == 0


def test_migration_preserves_different_canonical_destination(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    _init_repo(plans, "https://github.com/example/project--plans.git")
    _init_repo(agents, "https://github.com/example/project--agents.git")
    source = plans / "202608/prompts/collision.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Historical planner prompt\n", encoding="utf-8")
    canonical = agents / "prompts/202608/collision.md"
    canonical.parent.mkdir(parents=True)
    canonical.write_text("# New implementation prompt\n", encoding="utf-8")
    _commit_fixtures(plans, agents)

    report = _migrate_prompt_archive_repositories(
        _target(agents, tmp_path / "workspace"),
        plans,
        write=True,
    )

    assert report.prompts_moved == 1
    assert canonical.read_text(encoding="utf-8") == "# Historical planner prompt\n"
    assert (agents / "prompts/202608/collision_1.md").read_text(
        encoding="utf-8"
    ) == "# New implementation prompt\n"
    assert not source.exists()
