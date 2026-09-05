from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess

import pytest

from sase.agents_sync import git_sync
from sase.agents_sync.git import noninteractive_git_env, run_git
from sase.agents_sync.git_objects import LocalGitObjectReader
from sase.agents_sync.incoming_detection import capture_fetched_agent_updates
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_io import apply_payload_atomic
from sase.agents_sync.v2_models import V2PublicationCounts
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.git_lock_retry import STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS

from tests.agents_sync.git_sync_fixtures import (
    git,
    patch_payload_pass,
    setup_repo,
    target,
)


def test_default_sync_lock_timeout_waits_briefly() -> None:
    assert git_sync.DEFAULT_SYNC_LOCK_TIMEOUT_SECONDS == 10.0


def test_full_sync_reuses_one_name_registry_load_session_for_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync_target = target(tmp_path, tmp_path / "remote.git", tmp_path / "sidecar")
    events: list[str] = []

    class _Session:
        def __enter__(self) -> None:
            events.append("enter")

        def __exit__(self, *_args: object) -> None:
            events.append("exit")

    monkeypatch.setattr(git_sync, "name_registry_load_session", _Session)

    def build_inventory(
        _target: ProjectTarget,
        _identity: object,
        **_kwargs: object,
    ) -> ProjectHoodInventory:
        events.append("inventory")
        return ProjectHoodInventory(AgentOwnerIdentity("alice", "athena"), "proj", ())

    def reconcile(
        *_args: object,
        **_kwargs: object,
    ) -> V2PublicationCounts:
        events.append("reconcile")
        return V2PublicationCounts()

    monkeypatch.setattr(
        git_sync,
        "build_project_hood_inventory",
        build_inventory,
    )
    monkeypatch.setattr(
        git_sync,
        "reconcile_agent_hoods",
        reconcile,
    )

    git_sync._integrate_export_pass(
        sync_target,
        sync_target.sidecar_path,
        AgentOwnerIdentity("alice", "athena"),
        run_git,
    )

    assert events == ["enter", "inventory", "reconcile", "exit"]


def test_full_sync_transaction_commits_and_pushes_only_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)
    patch_payload_pass(monkeypatch)

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=run_git)

    assert outcome.error is None
    assert outcome.pulled and outcome.committed and outcome.pushed
    assert outcome.hoods_published == 1
    verify = tmp_path / "verify"
    git(tmp_path, "clone", str(remote), str(verify))
    assert (
        verify / "agents" / "local.athena.worker" / "chat.md"
    ).read_text() == "chat\n"
    assert git(verify, "log", "-1", "--format=%s").stdout.strip() == (
        "chore(agents): sync from local.athena"
    )
    assert json.loads((verify / "manifest.json").read_text()) == {
        "schema_version": 1,
        "agents": {},
    }


def test_full_sync_recovers_dirty_payload_before_pull(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)
    patch_payload_pass(monkeypatch)
    (sidecar / "manifest.json").write_text("stranded payload\n")
    stranded = sidecar / "agents" / "stranded" / "README.md"
    stranded.parent.mkdir()
    stranded.write_text("uncommitted payload\n")

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=run_git)

    assert outcome.error is None
    assert outcome.pushed
    assert not stranded.exists()
    assert json.loads((sidecar / "manifest.json").read_text()) == {
        "schema_version": 1,
        "agents": {},
    }
    assert git(sidecar, "status", "--short").stdout == ""


def test_full_sync_clears_stale_index_lock_before_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)
    patch_payload_pass(monkeypatch)
    lock_path = sidecar / ".git" / "index.lock"
    lock_path.write_text("abandoned\n")
    old = lock_path.stat().st_mtime - STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS - 1
    os.utime(lock_path, (old, old))

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=run_git)

    assert outcome.error is None
    assert outcome.pushed
    assert not lock_path.exists()
    assert git(sidecar, "status", "--short").stdout == ""


def test_full_sync_failure_after_payload_write_restores_clean_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)

    def fail_after_write(
        _target: ProjectTarget,
        repo: Path,
        **_kwargs: object,
    ) -> V2PublicationCounts:
        apply_payload_atomic(
            repo,
            {
                "README.md": b"# Stranded publication\n",
                "agents/stranded/README.md": b"# Stranded agent\n",
            },
        )
        raise RuntimeError("publication failed after payload write")

    monkeypatch.setattr(git_sync, "reconcile_agent_hoods", fail_after_write)

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=run_git)

    assert outcome.error == "publication failed after payload write"
    assert not (sidecar / "README.md").exists()
    assert not (sidecar / "agents" / "stranded").exists()
    assert git(sidecar, "status", "--short").stdout == ""


def test_payload_commit_force_stages_user_ignored_hood(
    tmp_path: Path,
) -> None:
    _remote, _seed, sidecar = setup_repo(tmp_path)
    (sidecar / "README.md").write_text("# Hoods\n")
    (sidecar / "schema.json").write_text("{}\n")
    for directory in ("users", "families"):
        root = sidecar / directory
        root.mkdir()
        (root / ".gitkeep").write_text("")
    git(sidecar, "add", "README.md", "schema.json", "users", "families")
    git(
        sidecar,
        "-c",
        "user.name=Tests",
        "-c",
        "user.email=tests@example.test",
        "commit",
        "-m",
        "complete sidecar baseline",
    )
    excludes = tmp_path / "global-excludes"
    excludes.write_text("*.gz\n")
    git(sidecar, "config", "core.excludesFile", str(excludes))
    readme = sidecar / "agents" / "alice.athena.gz" / "README.md"
    readme.parent.mkdir()
    readme.write_text("# Ignored hood\n")
    assert git(sidecar, "check-ignore", "-v", str(readme)).stdout

    owner = AgentOwnerIdentity("alice", "athena")
    assert git_sync.commit_agents_payload_if_dirty(sidecar, owner, run_git) is True
    head = git(sidecar, "rev-parse", "HEAD").stdout.strip()
    assert (
        git(sidecar, "show", "HEAD:agents/alice.athena.gz/README.md").stdout
        == "# Ignored hood\n"
    )

    assert git_sync.commit_agents_payload_if_dirty(sidecar, owner, run_git) is False
    assert git(sidecar, "rev-parse", "HEAD").stdout.strip() == head


def test_owner_manifest_missing_file_diagnostic_names_ignore_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote, seed, sidecar = setup_repo(tmp_path)
    manifest = seed / "users" / "alice" / "machines" / "athena" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "owner": {"username": "alice", "machine_name": "athena"},
                "project": {"key": "proj", "name": "Project"},
                "hoods": {
                    "gz": {
                        "digest": "a" * 64,
                        "files": ["agents/alice.athena.gz/README.md"],
                        "run_count": 1,
                        "family_count": 0,
                    }
                },
            }
        )
        + "\n"
    )
    git(seed, "add", str(manifest.relative_to(seed)))
    git(seed, "commit", "-m", "publish manifest without ignored hood")
    git(seed, "push")
    git(sidecar, "pull")
    excludes = tmp_path / "global-excludes"
    excludes.write_text("*.gz\n")
    git(sidecar, "config", "core.excludesFile", str(excludes))
    ignored_readme = sidecar / "agents" / "alice.athena.gz" / "README.md"
    ignored_readme.parent.mkdir()
    ignored_readme.write_text("# Stranded hood\n")
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))

    report = capture_fetched_agent_updates(
        target(tmp_path, remote, sidecar),
        AgentOwnerIdentity("alice", "athena"),
        reader=LocalGitObjectReader(sidecar),
        now=1.0,
    )

    assert len(report.diagnostics) == 1
    diagnostic = report.diagnostics[0]
    assert "owner manifest references 'agents/alice.athena.gz/README.md'" in diagnostic
    assert "missing from commit" in diagnostic
    assert "local ignore rule:" in diagnostic
    assert "*.gz" in diagnostic


def test_non_fast_forward_recomputes_and_retries_push_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)
    export_calls = patch_payload_pass(monkeypatch)
    intruder = tmp_path / "intruder"
    git(tmp_path, "clone", str(remote), str(intruder))
    git(intruder, "config", "user.name", "Intruder")
    git(intruder, "config", "user.email", "intruder@example.test")
    push_calls = 0

    def rejecting_runner(
        cwd: Path, args: list[str], *, network: bool = False, op: str = ""
    ) -> subprocess.CompletedProcess[str]:
        nonlocal push_calls
        if args == ["push"]:
            push_calls += 1
            if push_calls == 1:
                (intruder / "remote.txt").write_text("remote\n")
                git(intruder, "add", "remote.txt")
                git(intruder, "commit", "-m", "remote race")
                git(intruder, "push")
        return run_git(cwd, args, network=network, op=op)

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=rejecting_runner)

    assert outcome.error is None
    assert outcome.push_attempts == 2
    assert outcome.pushed
    assert push_calls == 2
    assert len(export_calls) == 2
    assert not (sidecar / ".git" / "rebase-merge").exists()
    assert not (sidecar / ".git" / "rebase-apply").exists()


def test_bounded_lock_contention_is_a_benign_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)
    patch_payload_pass(monkeypatch)
    lock_path = sidecar / ".git" / "sase-agents-sync.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        outcome = git_sync._sync_project(
            sync_target,
            "athena",
            git_runner=run_git,
            lock_timeout_seconds=0,
        )
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)

    assert outcome.error is None
    assert outcome.skip_reason == "agents sync lock is busy"


def test_missing_configured_remote_is_not_created(tmp_path: Path) -> None:
    missing = tmp_path / "missing.git"
    sync_target = target(tmp_path, missing, tmp_path / "sidecar")

    outcome = git_sync._sync_project(sync_target, "athena", git_runner=run_git)

    assert outcome.error is not None
    assert "could not clone" in outcome.error
    assert not missing.exists()


def test_pull_rebase_conflict_is_aborted_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    remote, _seed, sidecar = setup_repo(tmp_path)
    sync_target = target(tmp_path, remote, sidecar)
    git(sidecar, "config", "user.name", "Local")
    git(sidecar, "config", "user.email", "local@example.test")
    (sidecar / "conflict.txt").write_text("local\n")
    git(sidecar, "add", "conflict.txt")
    git(sidecar, "commit", "-m", "local ahead")

    intruder = tmp_path / "conflict-intruder"
    git(tmp_path, "clone", str(remote), str(intruder))
    git(intruder, "config", "user.name", "Remote")
    git(intruder, "config", "user.email", "remote@example.test")
    (intruder / "conflict.txt").write_text("remote\n")
    git(intruder, "add", "conflict.txt")
    git(intruder, "commit", "-m", "remote ahead")
    git(intruder, "push")
    outcome = git_sync._sync_project(sync_target, "athena", git_runner=run_git)

    assert outcome.error is not None
    assert "pull --rebase failed" in outcome.error
    assert git(sidecar, "log", "-1", "--format=%s").stdout.strip() == "local ahead"
    assert (sidecar / "conflict.txt").read_text() == "local\n"
    assert not (sidecar / ".git" / "rebase-merge").exists()
    assert not (sidecar / ".git" / "rebase-apply").exists()


def test_network_git_environment_is_noninteractive() -> None:
    original = {"PATH": "/bin", "GIT_TERMINAL_PROMPT": "1"}

    env = noninteractive_git_env(original)

    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert "BatchMode=yes" in env["GIT_SSH_COMMAND"]
    assert original["GIT_TERMINAL_PROMPT"] == "1"
