"""Three-identity local-bare-remote rollout verification."""

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
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
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
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    for key in (
        "GIT_DIR",
        "GIT_WORK_TREE",
        "GIT_OBJECT_DIRECTORY",
        "GIT_INDEX_FILE",
    ):
        env.pop(key, None)
    # Keep receive-pack from detaching auto-gc during the nested push race.
    result = subprocess.run(
        ["git", "-c", "gc.auto=0", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"git {' '.join(args)} in {cwd} exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def _disable_auto_gc(repo: Path) -> None:
    _git(repo, "config", "gc.auto", "0")
    _git(repo, "config", "gc.autoDetach", "false")


def _clone(cwd: Path, remote: Path, dest: Path) -> None:
    # `--local` hardlinks objects and can race with receive-pack auto-gc.
    assert not dest.exists(), f"clone dest already exists: {dest}"
    _git(cwd, "clone", "--no-local", str(remote), str(dest))
    _disable_auto_gc(dest)


def _seed_bare_remote(tmp_path: Path) -> Path:
    remote = tmp_path / "agents-remote.git"
    remote.mkdir()
    _git(remote, "init", "--bare")
    _disable_auto_gc(remote)
    seed = tmp_path / "agents-seed"
    seed.mkdir()
    _git(seed, "init")
    _disable_auto_gc(seed)
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


def _make_primary(
    tmp_path: Path,
    label: str,
    owner: AgentOwnerIdentity,
    agent: str,
) -> Path:
    primary = tmp_path / f"{label}-primary"
    primary.mkdir()
    _git(primary, "init")
    _git(primary, "config", "user.name", "Author")
    _git(primary, "config", "user.email", "author@example.test")
    (primary / "code.txt").write_text(f"{label}\n")
    _git(primary, "add", ".")
    message = update_trailing_commit_tags(
        f"feat: {label}\n\nSASE_MACHINE=legacy-host\n",
        {"AGENT": f"{owner.username}.{owner.machine_name}.{agent}"},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )
    assert "SASE_MACHINE" not in message
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
    update_agent_artifact_index_for_marker_mutation(artifact)
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


def _artifact_names(home: Path) -> set[str]:
    root = home / "projects" / PROJECT_KEY / "artifacts" / ACE_RUN_WORKFLOW_DIR
    return {
        str(json.loads(path.read_text())["name"])
        for path in root.rglob("agent_meta.json")
    }


def test_three_identities_converge_and_localize_through_non_fast_forward_race(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = _seed_bare_remote(tmp_path)
    athena_owner = AgentOwnerIdentity("bbugyi200", "athena")
    zeus_owner = AgentOwnerIdentity("bbugyi200", "zeus")
    alice_owner = AgentOwnerIdentity("alice", "athena")
    athena_sidecar = tmp_path / "athena-sidecar"
    zeus_sidecar = tmp_path / "zeus-sidecar"
    alice_sidecar = tmp_path / "alice-sidecar"
    for sidecar in (athena_sidecar, zeus_sidecar, alice_sidecar):
        _clone(tmp_path, remote, sidecar)

    athena_home = tmp_path / "athena-home"
    zeus_home = tmp_path / "zeus-home"
    alice_home = tmp_path / "alice-home"
    for home in (athena_home, zeus_home, alice_home):
        home.mkdir()
    athena_primary = _make_primary(tmp_path, "athena", athena_owner, "worker")
    zeus_primary = _make_primary(tmp_path, "zeus", zeus_owner, "builder")
    alice_primary = _make_primary(tmp_path, "alice", alice_owner, "reviewer")
    athena_target = _target(athena_primary, athena_sidecar, remote)
    zeus_target = _target(zeus_primary, zeus_sidecar, remote)
    alice_target = _target(alice_primary, alice_sidecar, remote)

    monkeypatch.setenv("SASE_HOME", str(athena_home))
    athena_artifact = _seed_agent("worker", "20260722010101")
    athena_first = git_sync._sync_project(
        athena_target,
        athena_owner,
        git_runner=run_git,
    )
    assert athena_first.error is None
    assert athena_first.hoods_published == 1

    monkeypatch.setenv("SASE_HOME", str(zeus_home))
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
                os.environ["SASE_HOME"] = str(athena_home)
                try:
                    (athena_artifact / "raw_xprompt.md").write_text(
                        "refreshed athena prompt\n"
                    )
                    raced = git_sync._sync_project(
                        athena_target,
                        athena_owner,
                        git_runner=run_git,
                    )
                    assert raced.error is None
                    assert raced.hoods_refreshed == 1
                finally:
                    os.environ["SASE_HOME"] = previous_home
        return run_git(cwd, args, network=network, op=op)

    zeus = git_sync._sync_project(
        zeus_target,
        zeus_owner,
        git_runner=racing_runner,
    )
    assert zeus.error is None, zeus.error
    assert zeus.push_attempts == 2
    assert zeus.pushed
    assert zeus.hoods_published + zeus.hoods_refreshed == 1, zeus.to_json_dict()
    assert _artifact_names(zeus_home) == {"builder", "athena.worker"}

    monkeypatch.setenv("SASE_HOME", str(alice_home))
    _seed_agent("reviewer", "20260722030303")
    alice = git_sync._sync_project(
        alice_target,
        alice_owner,
        git_runner=run_git,
    )
    assert alice.error is None, alice.error
    assert alice.pushed
    assert alice.hoods_published + alice.hoods_refreshed == 1, alice
    assert _artifact_names(alice_home) == {
        "reviewer",
        "bbugyi200.athena.worker",
        "bbugyi200.zeus.builder",
    }

    # The exact-owner snapshot is observed, not duplicated. Foreign names use
    # the conditional machine/user prefixes dictated by the owner matrix.
    monkeypatch.setenv("SASE_HOME", str(athena_home))
    athena_final = git_sync._sync_project(
        athena_target,
        athena_owner,
        git_runner=run_git,
    )
    assert athena_final.error is None, athena_final.error
    assert _artifact_names(athena_home) == {
        "worker",
        "zeus.builder",
        "alice.athena.reviewer",
    }

    verify = tmp_path / "verify"
    _clone(tmp_path, remote, verify)
    assert (
        verify / "users" / "bbugyi200" / "machines" / "athena" / "manifest.json"
    ).is_file()
    assert (
        verify / "users" / "bbugyi200" / "machines" / "zeus" / "manifest.json"
    ).is_file()
    assert (
        verify / "users" / "alice" / "machines" / "athena" / "manifest.json"
    ).is_file()
    assert (
        verify / "agents" / "bbugyi200.athena.worker" / "prompt.md"
    ).read_text() == "refreshed athena prompt\n"
    assert (
        verify / "agents" / "bbugyi200.zeus.builder" / "prompt.md"
    ).read_text() == "prompt for builder\n"
    assert (
        verify / "agents" / "alice.athena.reviewer" / "prompt.md"
    ).read_text() == "prompt for reviewer\n"
    root = (verify / "README.md").read_text()
    assert "bbugyi200" in root and "alice" in root
    assert json.loads((verify / "manifest.json").read_text()) == {
        "schema_version": 1,
        "agents": {},
    }
    for primary, owner in (
        (athena_primary, athena_owner),
        (zeus_primary, zeus_owner),
        (alice_primary, alice_owner),
    ):
        message = _git(primary, "log", "-1", "--format=%B").stdout
        assert f"SASE_AGENT={owner.username}.{owner.machine_name}." in message
        assert "SASE_MACHINE" not in message
