"""Tests for historical plans-sidecar prompt migration."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.migration import (
    _migrate_prompt_archive_repositories,
)
from sase.agents_sync.git import run_git
from sase.agents_sync.prompt_archive.protection import PROMPT_PROTECTION_BLOCKED
from sase.agents_sync.prompt_archive.validation import validate_prompt_archive
from sase.sdd.links import validate_sdd_tree
from tests.agents_sync.test_publication_recovery._helpers import (
    TOKEN,
    gh013_stderr,
    isolate_protection,
)

MARKER = b"SYNTHETIC-PROMPT-SECRET-1os"


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


def _install_scan_binding(
    monkeypatch: pytest.MonkeyPatch,
    *,
    blocked: bytes | None = None,
) -> None:
    import sase.core.rust as rust

    real_require = rust.require_rust_binding

    def require_binding(name: str):
        if name == "attachment_scan_file":

            def scan(
                path: str,
                max_bytes: int,
                _env: dict[str, str],
                _home: str,
                _sase_home: str,
            ) -> dict[str, object]:
                data = Path(path).read_bytes()
                if blocked is not None and blocked in data:
                    return {
                        "outcome": "hit",
                        "hit": {
                            "kind": "credential_pattern",
                            "rule_id": "synthetic-marker",
                            "line": 1,
                            "rules_version": 1,
                        },
                        "bytes_scanned": len(data),
                        "rules_version": 1,
                    }
                return {
                    "outcome": "clean",
                    "hit": None,
                    "bytes_scanned": len(data),
                    "rules_version": 1,
                }

            return scan
        return real_require(name)

    monkeypatch.setattr(rust, "require_rust_binding", require_binding)


@pytest.fixture(autouse=True)
def _isolate_migration_protection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    isolate_protection(monkeypatch, tmp_path)
    _install_scan_binding(monkeypatch)


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


def test_migration_withholds_secret_prompt_and_publishes_clean_sibling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_scan_binding(monkeypatch, blocked=MARKER)
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    _init_repo(plans, "https://github.com/example/project--plans.git")
    _init_repo(agents, "https://github.com/example/project--agents.git")
    secret_text = f"# Secret prompt {MARKER.decode()}\n"
    clean = plans / "202608/prompts/clean.md"
    secret = plans / "202608/prompts/secret.md"
    plan = plans / "202608/clean.md"
    clean.parent.mkdir(parents=True)
    clean.write_text(
        "- **PLAN:** [../202608/clean.md](../clean.md)\n\n# Clean prompt\n",
        encoding="utf-8",
    )
    plan.write_text(
        "---\ntier: tale\n---\n\n"
        "- **PROMPT:** [202608/prompts/clean.md](prompts/clean.md)\n\n"
        "# Clean plan\n",
        encoding="utf-8",
    )
    secret.write_text(secret_text, encoding="utf-8")
    _commit_fixtures(plans)
    target = _target(agents, tmp_path / "workspace")

    report = _migrate_prompt_archive_repositories(target, plans, write=True)

    assert report.prompts_moved == 1
    assert report.plans_relinked == 1
    assert report.months_committed == 1
    assert len(report.skipped) == 1
    assert report.skipped[0].path == "202608/prompts/secret.md"
    assert report.skipped[0].reason == PROMPT_PROTECTION_BLOCKED
    assert secret.is_file()
    assert secret.read_text(encoding="utf-8") == secret_text
    assert not clean.exists()
    archived = agents / "prompts/202608/clean.md"
    assert archived.is_file()
    assert MARKER not in archived.read_bytes()
    assert not (agents / "prompts/202608/secret.md").exists()
    for path in agents.rglob("*"):
        if path.is_file() and ".git" not in path.parts:
            assert MARKER not in path.read_bytes()
    dumped = json.dumps(report.to_json_dict())
    assert MARKER.decode() not in dumped
    assert TOKEN not in dumped
    assert _ahead(agents) == 0
    assert _ahead(plans) == 0


def test_migration_gh013_does_not_advise_or_execute_raw_repush(
    tmp_path: Path,
) -> None:
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    _init_repo(plans, "https://github.com/example/project--plans.git")
    _init_repo(agents, "https://github.com/example/project--agents.git")
    source = plans / "202608/prompts/ordinary.md"
    source.parent.mkdir(parents=True)
    source.write_text("# Ordinary prompt\n", encoding="utf-8")
    _commit_fixtures(plans)
    push_remote = (agents.parent / "agents-remote.git").resolve()
    _git(agents, "remote", "set-url", "origin", str(push_remote))
    target = ProjectTarget(
        project_key="project-key",
        project="Project",
        primary_checkout=tmp_path / "workspace",
        primary_roots=(tmp_path / "workspace",),
        sidecar_path=agents,
        remote_url=str(push_remote),
    )
    base_tip = _head(agents)
    relative = "prompts/202608/ordinary.md"
    pushes: list[Path] = []

    def fail_agents_gh013(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        if args == ["push", "origin", "HEAD"]:
            pushes.append(cwd)
            if cwd == agents:
                return subprocess.CompletedProcess(args, 1, "", gh013_stderr(relative))
        return run_git(cwd, args, network=network, op=op)

    with pytest.raises(RuntimeError) as excinfo:
        _migrate_prompt_archive_repositories(
            target,
            plans,
            month="202608",
            write=True,
            git_runner=fail_agents_gh013,
        )

    message = str(excinfo.value)
    assert TOKEN not in message
    assert "push origin HEAD" not in message
    assert "secret scanning" in message
    assert (
        "sase agent prompts migrate --write --project Project --month 202608" in message
    )
    assert pushes == [agents]
    assert _head(agents) == base_tip
    assert not (agents / relative).exists()


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
