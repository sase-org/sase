"""Shared helpers for failed-close recovery tests.

Split from ``tests.test_finalizers_failed_close_recovery``. All helpers use
public names so the focused test modules can import them without touching a
``_``-prefixed symbol across files.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.bead.model import IssueType, PhaseSize, Resolution
from sase.bead.project import BeadProject
from sase.bead.sync import commit_failed_close_recovery
from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo

from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
)


def commit_config() -> FinalizerConfig:
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    return FinalizerConfig(
        defaults=("commit",),
        required=(),
        instances={"commit": commit},
        provenance={},
    )


def use_config(monkeypatch: pytest.MonkeyPatch, config: FinalizerConfig) -> None:
    def loader() -> FinalizerConfig:
        return config

    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", loader)
    monkeypatch.setattr("sase.finalizers.config.load_finalizer_config", loader)


def seed_git_store(root: Path) -> BeadProject:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "config", "user.name", "probe"], cwd=root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "probe@example.invalid"], cwd=root, check=True
    )
    return BeadProject.init(root)


def close_phase_with_plan(project: BeadProject) -> tuple[str, str]:
    """Create a plan plus phase and close both with the harness run identity."""
    plan = project.create("Recovery plan", IssueType.PLAN, tier="epic")
    phase = project.create(
        "Recovery phase",
        IssueType.PHASE,
        parent_id=plan.id,
        size=PhaseSize.MEDIUM,
        created_by="probe",
    )
    project.close([phase.id], resolution=Resolution.DONE)
    project.close([plan.id], resolution=Resolution.DONE)
    return plan.id, phase.id


@contextmanager
def machine_lane(monkeypatch: pytest.MonkeyPatch, beads_dir: Path) -> Iterator[None]:
    """Route the machine lane at a temporary bead store."""
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("test-user", "test_host"),
    )
    store = SimpleNamespace(project="test-recovery", beads_dir=beads_dir, context=None)

    @contextmanager
    def acquire(project: str, run_id: str) -> Iterator[Any]:
        assert project == "test-recovery"
        assert run_id == "run-1"
        yield store

    def commit(
        target: Path,
        run_id: str,
        *,
        already_locked: bool = False,
        operation_context: Any = None,
    ) -> bool:
        return commit_failed_close_recovery(
            target, run_id, already_locked=already_locked
        )

    monkeypatch.setattr(
        "sase.finalizers._failed_close_recovery_apply._resolve_machine_project",
        lambda _artifacts: "test-recovery",
    )
    monkeypatch.setattr(
        "sase.finalizers._failed_close_recovery_apply._acquire_recovery_store", acquire
    )
    monkeypatch.setattr(
        "sase.finalizers._failed_close_recovery_apply._commit_recovery_mutation", commit
    )
    yield


def prepare_commit_run(
    monkeypatch: pytest.MonkeyPatch, artifacts: Path, repo: Path
) -> None:
    prepare_agent_env(monkeypatch, artifacts, repo)
    patch_dirty(monkeypatch, repo, {"repos": (dirty_repo(repo),)})
    use_config(monkeypatch, commit_config())


def fail_stitch(
    _repo: DirtyRepo,
    _message: str,
    _excludes: tuple[str, ...],
    _context: object,
) -> StitchCommandResult:
    return StitchCommandResult(returncode=1, stderr="hook failed\n")


def record_landing_marker(artifacts: Path, repo: DirtyRepo) -> None:
    existing = artifacts / "commit_results.json"
    payload = (
        json.loads(existing.read_text(encoding="utf-8")) if existing.exists() else []
    )
    payload.append(
        {
            "cwd": repo.path,
            "result": "ok",
            "run_id": "run-1",
            "commit_sha": "a" * 40,
            "commit_tree": "b" * 40,
        }
    )
    existing.write_text(json.dumps(payload), encoding="utf-8")


def git_run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    )


def seed_git_store_with_remote(root: Path, remote: Path) -> BeadProject:
    remote.mkdir()
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    project = seed_git_store(root)
    git_run(root, "config", "user.name", "probe")
    git_run(root, "config", "user.email", "probe@example.invalid")
    git_run(root, "add", "-A")
    git_run(root, "commit", "-m", "init beads", "--allow-empty")
    git_run(root, "remote", "add", "origin", str(remote))
    git_run(root, "push", "-u", "origin", "HEAD")
    return project


def git_push_origin(beads_dir: Path) -> SimpleNamespace:
    from sase.bead._sync_git import find_git_root

    repo = find_git_root(beads_dir)
    assert repo is not None
    result = subprocess.run(
        ["git", "push", "origin", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return SimpleNamespace(
            pushed=False,
            skipped_no_remote=False,
            error=result.stderr.strip() or "push failed",
        )
    return SimpleNamespace(pushed=True, skipped_no_remote=False, error=None)


def recovery_events_in_repo(root: Path) -> int:
    events_root = root / "sdd" / "beads" / "events"
    if not events_root.is_dir():
        events_root = root / "beads" / "events"
    count = 0
    for path in events_root.rglob("*.jsonl"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if (
                "completion_failure_recovered" in line
                or "CompletionFailureRecovered" in line
            ):
                count += 1
    return count
