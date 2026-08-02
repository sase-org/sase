"""Tests for historical plans-sidecar prompt migration."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.migration import (
    _migrate_prompt_archive_repositories,
)
from sase.agents_sync.git import run_git
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
    push_remote = repo.parent / f"{repo.name}-remote.git"
    subprocess.run(
        ["git", "init", "--bare", str(push_remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "remote", "add", "origin", remote)
    _git(repo, "config", "remote.origin.pushurl", str(push_remote))
    (repo / ".gitkeep").write_text("", encoding="utf-8")
    _git(repo, "add", ".gitkeep")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "push", "--set-upstream", "origin", "main")


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

    completed_heads = (_head(plans), _head(agents))
    repeated = _migrate_prompt_archive_repositories(target, plans, write=True)

    assert repeated.prompts_moved == 0
    assert repeated.plans_relinked == 0
    assert repeated.months_committed == 0
    assert (_head(plans), _head(agents)) == completed_heads
    assert _ahead(plans) == 0
    assert _ahead(agents) == 0


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


def test_migration_restarts_when_archive_commit_already_exists(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    _init_repo(plans, "https://github.com/example/project--plans.git")
    _init_repo(agents, "https://github.com/example/project--agents.git")
    source = plans / "202608/prompts/restart.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Restart prompt\n", encoding="utf-8")
    archive = agents / "prompts/202608/restart.md"
    archive.parent.mkdir(parents=True)
    archive.write_text("# Restart prompt\n", encoding="utf-8")
    _commit_fixtures(plans, agents)
    _git(plans, "push", "origin", "HEAD")

    report = _migrate_prompt_archive_repositories(
        _target(agents, tmp_path / "workspace"),
        plans,
        write=True,
    )

    assert report.prompts_moved == 1
    assert not source.exists()
    assert archive.read_text(encoding="utf-8") == "# Restart prompt\n"
    assert _ahead(plans) == 0
    assert _ahead(agents) == 0


def test_migration_recovers_when_only_plans_push_remains(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    _init_repo(plans, "https://github.com/example/project--plans.git")
    _init_repo(agents, "https://github.com/example/project--agents.git")
    source = plans / "202608/prompts/partial.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Partial prompt\n", encoding="utf-8")
    _commit_fixtures(plans)
    target = _target(agents, tmp_path / "workspace")

    def fail_plans_push(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        if cwd == plans and args == ["push", "origin", "HEAD"]:
            return subprocess.CompletedProcess(args, 1, "", "planned push failure")
        return run_git(cwd, args, network=network, op=op)

    with pytest.raises(RuntimeError) as excinfo:
        _migrate_prompt_archive_repositories(
            target,
            plans,
            month="202608",
            write=True,
            git_runner=fail_plans_push,
        )

    message = str(excinfo.value)
    assert "plans sidecar migration push failed: planned push failure" in message
    assert f"git -C {plans} push origin HEAD" in message
    assert f"git -C {agents} push origin HEAD" not in message
    assert (
        "sase agent prompts migrate --write --project Project --month 202608" in message
    )
    assert _ahead(agents) == 0
    assert _ahead(plans) > 0

    restarted = _migrate_prompt_archive_repositories(
        target,
        plans,
        month="202608",
        write=True,
    )

    assert restarted.prompts_moved == 0
    assert restarted.months_committed == 0
    assert _ahead(plans) == 0
    assert _ahead(agents) == 0


def _ahead(repo: Path) -> int:
    result = subprocess.run(
        ["git", "rev-list", "--count", "@{upstream}..HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def _head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
