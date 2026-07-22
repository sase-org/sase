"""End-to-end two-machine exercise of the agents sidecar sync flow.

Unlike ``test_git_sync`` (which stubs export/import to focus on the git
transaction) and ``test_bundles`` (which stubs the artifact/registry seams to
focus on one bundle), this module drives the *real* export -> commit -> push
and pull -> import stack across two independent machines that share a single
bare "GitHub" agents sidecar remote. Each machine has its own ``SASE_HOME`` so
artifact dirs, chats, and the durable name registry are genuinely separate.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.models import ProjectTarget
from sase.core.agent_artifact_paths import (
    ACE_RUN_WORKFLOW_DIR,
    canonical_agent_artifact_path,
    iter_agent_artifact_dirs,
)
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
    """Create a bare remote seeded like a freshly initialized agents sidecar."""

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


def _make_primary_with_agent_commit(
    tmp_path: Path, name: str, machine: str, suffix: str
) -> Path:
    """Create a primary repo whose HEAD carries the agent's provenance footer."""

    primary = tmp_path / f"{name}-primary"
    primary.mkdir()
    _git(primary, "init")
    _git(primary, "config", "user.name", "Author")
    _git(primary, "config", "user.email", "author@example.test")
    (primary / "code.txt").write_text(f"{name} change\n")
    _git(primary, "add", ".")
    message = update_trailing_commit_tags(
        f"feat: {suffix} work\n",
        {"AGENT": suffix, "MACHINE": machine},
        remove_keys=RUNTIME_COMMIT_TAG_KEYS,
    )
    _git(primary, "commit", "-m", message)
    return primary


def _seed_local_completed_agent(suffix: str, chat_text: str, timestamp: str) -> Path:
    """Materialize a terminal, commit-worthy local agent for the current machine.

    ``SASE_HOME`` must already point at this machine's state directory so the
    canonical artifact path resolves inside it.
    """

    artifact = canonical_agent_artifact_path(
        PROJECT_KEY, ACE_RUN_WORKFLOW_DIR, timestamp
    )
    artifact.mkdir(parents=True)
    chat = artifact / "chat.md"
    chat.write_text(chat_text)
    # ``pid``/``workspace_dir`` are deliberately machine-local: the portable
    # projection must drop them, so their survival on the far machine is a bug.
    (artifact / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": suffix,
                "model": "opus",
                "workflow_name": ACE_RUN_WORKFLOW_DIR,
                "chat_path": str(chat),
                "pid": 4242,
                "workspace_dir": "/private/workspace/sase_9",
            }
        )
    )
    (artifact / "done.json").write_text(
        json.dumps({"outcome": "completed", "name": suffix})
    )
    return artifact


def _target(project_primary: Path, sidecar: Path, remote: Path) -> ProjectTarget:
    return ProjectTarget(
        PROJECT_KEY,
        PROJECT_NAME,
        project_primary,
        (project_primary.resolve(),),
        sidecar,
        str(remote),
    )


def _imported_artifact_meta(project_key: str, qualified_name: str) -> dict[str, object]:
    """Return the imported artifact ``agent_meta.json`` for *qualified_name*."""

    for artifact in iter_agent_artifact_dirs(
        project_key, ACE_RUN_WORKFLOW_DIR, newest_first=True
    ):
        meta_path = artifact / "agent_meta.json"
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text())
        if meta.get("name") == qualified_name:
            return meta
    raise AssertionError(f"no imported artifact for {qualified_name!r}")


def _registry_entry(home: Path, qualified_name: str) -> dict[str, object]:
    data = json.loads((home / "agent_name_registry.json").read_text())
    entries = data.get("entries", {})
    assert qualified_name in entries, f"{qualified_name!r} not in name registry"
    return entries[qualified_name]


def test_two_machines_round_trip_completed_agents_through_shared_sidecar(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote = _seed_bare_remote(tmp_path)

    home_alpha = tmp_path / "alpha-home"
    home_beta = tmp_path / "beta-home"
    home_alpha.mkdir()
    home_beta.mkdir()

    primary_alpha = _make_primary_with_agent_commit(
        tmp_path, "alpha", "alpha", "worker"
    )
    primary_beta = _make_primary_with_agent_commit(tmp_path, "beta", "beta", "builder")

    target_alpha = _target(primary_alpha, tmp_path / "alpha-sidecar", remote)
    target_beta = _target(primary_beta, tmp_path / "beta-sidecar", remote)

    # --- Machine alpha: record a completed agent and publish it. ------------
    monkeypatch.setenv("SASE_HOME", str(home_alpha))
    _seed_local_completed_agent("worker", "alpha worker transcript\n", "20260722010101")

    alpha_first = git_sync._sync_project(target_alpha, "alpha", git_runner=run_git)
    assert alpha_first.error is None, alpha_first.error
    assert alpha_first.exported == 1
    assert alpha_first.pushed

    # The published bundle exists on the shared remote under the qualified name.
    verify = tmp_path / "verify"
    _git(tmp_path, "clone", str(remote), str(verify))
    published_meta = json.loads(
        (verify / "agents" / "alpha.worker" / "meta.json").read_text()
    )
    assert published_meta["name"] == "alpha.worker"
    assert published_meta["machine"] == "alpha"
    assert "pid" not in published_meta
    assert "workspace_dir" not in published_meta

    # --- Machine beta: import alpha's agent and publish its own. ------------
    monkeypatch.setenv("SASE_HOME", str(home_beta))
    _seed_local_completed_agent(
        "builder", "beta builder transcript\n", "20260722020202"
    )

    beta_first = git_sync._sync_project(target_beta, "beta", git_runner=run_git)
    assert beta_first.error is None, beta_first.error
    assert beta_first.integrated == 1
    assert beta_first.exported == 1
    assert beta_first.pushed

    # Alpha's agent reconstructs as a normal terminal artifact on beta, keeps
    # its fully qualified foreign name, and drops machine-local metadata.
    imported_on_beta = _imported_artifact_meta(PROJECT_KEY, "alpha.worker")
    assert imported_on_beta["imported_from_machine"] == "alpha"
    assert imported_on_beta["model"] == "opus"
    assert "pid" not in imported_on_beta
    assert "workspace_dir" not in imported_on_beta
    assert (
        Path(str(imported_on_beta["chat_path"])).read_text()
        == "alpha worker transcript\n"
    )
    beta_registry_entry = _registry_entry(home_beta, "alpha.worker")
    assert beta_registry_entry["imported_from_machine"] == "alpha"

    # --- Machine alpha again: import beta's agent (round trip closes). ------
    monkeypatch.setenv("SASE_HOME", str(home_alpha))
    alpha_second = git_sync._sync_project(target_alpha, "alpha", git_runner=run_git)
    assert alpha_second.error is None, alpha_second.error
    assert alpha_second.integrated == 1
    # Alpha's own bundle is already published and unchanged.
    assert alpha_second.exported == 0

    imported_on_alpha = _imported_artifact_meta(PROJECT_KEY, "beta.builder")
    assert imported_on_alpha["imported_from_machine"] == "beta"
    assert (
        Path(str(imported_on_alpha["chat_path"])).read_text()
        == "beta builder transcript\n"
    )
    assert (
        _registry_entry(home_alpha, "beta.builder")["imported_from_machine"] == "beta"
    )

    # --- Idempotence: a further beta sync imports nothing new. --------------
    monkeypatch.setenv("SASE_HOME", str(home_beta))
    beta_second = git_sync._sync_project(target_beta, "beta", git_runner=run_git)
    assert beta_second.error is None, beta_second.error
    assert beta_second.integrated == 0
    assert beta_second.refreshed == 0
    assert beta_second.exported == 0
