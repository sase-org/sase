"""Two-owner local-bare-remote coverage for convergent v2 publication."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.models import ProjectTarget
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    canonical_agent_artifact_path,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.paths import sase_home
from sase.workflows.commit.runtime_tags import (
    RUNTIME_COMMIT_TAG_KEYS,
    update_trailing_commit_tags,
)

PROJECT_KEY = "proj"
PROJECT_NAME = "Project"


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def _seed_bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "agents-remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    seed = tmp_path / "agents-seed"
    seed.mkdir()
    _git(seed, "init")
    _git(seed, "config", "user.name", "Seed")
    _git(seed, "config", "user.email", "seed@example.test")
    (seed / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "agents": {}}, indent=2) + "\n"
    )
    (seed / "agents").mkdir()
    (seed / "agents" / ".gitkeep").write_text("")
    _git(seed, "add", ".")
    _git(seed, "commit", "-m", "seed agents sidecar")
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "-u", "origin", "HEAD")
    return remote


def _make_primary(tmp_path: Path, label: str, machine: str, agent: str) -> Path:
    primary = tmp_path / f"{label}-primary"
    primary.mkdir()
    _git(primary, "init")
    _git(primary, "config", "user.name", "Author")
    _git(primary, "config", "user.email", "author@example.test")
    (primary / "code.txt").write_text(f"{label}\n")
    _git(primary, "add", ".")
    message = update_trailing_commit_tags(
        f"feat: {label}\n",
        {"AGENT": agent, "MACHINE": machine},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )
    _git(primary, "commit", "-m", message)
    return primary


def _seed_agent(agent: str, timestamp: str) -> Path:
    artifact = canonical_agent_artifact_path(
        PROJECT_KEY, ACE_RUN_WORKFLOW_DIR, timestamp
    )
    artifact.mkdir(parents=True)
    chat = sase_home() / "chats" / timestamp[:6] / f"{agent}.md"
    chat.parent.mkdir(parents=True)
    chat.write_text(f"chat for {agent}\n")
    (artifact / "raw_xprompt.md").write_text(f"prompt for {agent}\n")
    (artifact / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": agent,
                "model": "gpt",
                "chat_path": str(chat),
                "pid": 999,
                "workspace_dir": "/private/workspace",
            }
        )
    )
    (artifact / "done.json").write_text(
        json.dumps({"outcome": "completed", "name": agent})
    )
    return artifact


def _target(primary: Path, sidecar: Path, remote: Path) -> ProjectTarget:
    return ProjectTarget(
        PROJECT_KEY,
        PROJECT_NAME,
        primary,
        (primary.resolve(),),
        sidecar,
        str(remote),
    )


def test_two_owners_converge_through_non_fast_forward_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _seed_bare_remote(tmp_path)
    alpha_sidecar = tmp_path / "alpha-sidecar"
    beta_sidecar = tmp_path / "beta-sidecar"
    _git(tmp_path, "clone", str(remote), str(alpha_sidecar))
    _git(tmp_path, "clone", str(remote), str(beta_sidecar))

    alpha_home = tmp_path / "alpha-home"
    beta_home = tmp_path / "beta-home"
    alpha_home.mkdir()
    beta_home.mkdir()
    alpha_primary = _make_primary(tmp_path, "alpha", "alpha", "worker")
    beta_primary = _make_primary(tmp_path, "beta", "beta", "builder")
    alpha_target = _target(alpha_primary, alpha_sidecar, remote)
    beta_target = _target(beta_primary, beta_sidecar, remote)
    alpha_owner = AgentOwnerIdentity("alice", "alpha")
    beta_owner = AgentOwnerIdentity("bob", "beta")

    monkeypatch.setenv("SASE_HOME", str(alpha_home))
    alpha_artifact = _seed_agent("worker", "20260722010101")
    alpha_first = git_sync._sync_project(alpha_target, alpha_owner, git_runner=run_git)
    assert alpha_first.error is None
    assert alpha_first.hoods_published == 1

    monkeypatch.setenv("SASE_HOME", str(beta_home))
    _seed_agent("builder", "20260722020202")
    push_calls = 0

    def racing_runner(
        cwd: Path,
        args: list[str],
        *,
        network: bool = False,
        op: str = "",
    ) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        if args == ["push"]:
            push_calls += 1
            if push_calls == 1:
                previous_home = os.environ["SASE_HOME"]
                os.environ["SASE_HOME"] = str(alpha_home)
                try:
                    (alpha_artifact / "raw_xprompt.md").write_text(
                        "refreshed alpha prompt\n"
                    )
                    raced = git_sync._sync_project(
                        alpha_target,
                        alpha_owner,
                        git_runner=run_git,
                    )
                    assert raced.error is None
                    assert raced.hoods_refreshed == 1
                finally:
                    os.environ["SASE_HOME"] = previous_home
        return run_git(cwd, args, network=network, op=op)

    beta = git_sync._sync_project(
        beta_target,
        beta_owner,
        git_runner=racing_runner,
    )

    assert beta.error is None, beta.error
    assert beta.push_attempts == 2
    assert beta.pushed
    verify = tmp_path / "verify"
    _git(tmp_path, "clone", str(remote), str(verify))
    assert (
        verify / "users" / "alice" / "machines" / "alpha" / "manifest.json"
    ).is_file()
    assert (verify / "users" / "bob" / "machines" / "beta" / "manifest.json").is_file()
    assert (
        verify / "agents" / "alice.alpha.worker" / "prompt.md"
    ).read_text() == "refreshed alpha prompt\n"
    assert (
        verify / "agents" / "bob.beta.builder" / "prompt.md"
    ).read_text() == "prompt for builder\n"
    root = (verify / "README.md").read_text()
    assert "alice" in root and "bob" in root
    assert json.loads((verify / "manifest.json").read_text()) == {
        "schema_version": 1,
        "agents": {},
    }
    assert _git(verify, "log", "-1", "--format=%s").stdout.strip() == (
        "chore(agents): sync from bob.beta"
    )
