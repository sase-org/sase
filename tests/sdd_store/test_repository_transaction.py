"""Transactional integration and repository-health regression coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.sdd._repository_transaction import (
    SddIntegrationStatus,
    integrate_sdd_repository,
    require_sdd_repository_health,
)
from sase.sdd._integration_marker import integration_is_fresh
from sase.sdd._store_link import ensure_sidecar_sdd_clone
from sase.sdd._store_types import SddMaterializationError
from tests.sdd_store._helpers import (
    clone,
    commit_all,
    git,
    init_bare_repo,
)


def _build_diverged_clones(
    tmp_path: Path,
    *,
    relative_path: str = "plans/shared.md",
    base: str = "base\n",
    local: str = "local\n",
    remote_text: str = "remote\n",
) -> tuple[Path, Path, Path]:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    left = tmp_path / "left"
    right = tmp_path / "right"
    init_bare_repo(remote)
    clone(remote, seed)
    target = seed / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(base, encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, left)
    clone(remote, right)

    (left / relative_path).write_text(local, encoding="utf-8")
    commit_all(left, "local change")
    (right / relative_path).write_text(remote_text, encoding="utf-8")
    commit_all(right, "remote change")
    git(["push"], right)
    return remote, left, right


def _snapshot(repo: Path) -> tuple[str, str, str]:
    return (
        git(["symbolic-ref", "--short", "HEAD"], repo).stdout,
        git(["rev-parse", "HEAD"], repo).stdout,
        git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            repo,
        ).stdout,
    )


def _runner(
    repo_root: Path,
    args: list[str],
    *,
    op: str,
    network: bool = False,
) -> subprocess.CompletedProcess[str]:
    del op, network
    return subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )


def test_unsupported_plan_conflict_aborts_to_exact_starting_state(
    tmp_path: Path,
) -> None:
    _remote, left, _right = _build_diverged_clones(tmp_path)
    untracked = left / "keep-untracked.md"
    untracked.write_text("keep\n", encoding="utf-8")
    starting = _snapshot(left)

    outcome = integrate_sdd_repository(left, beads_dir=left / "beads")

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    assert "non-bead conflicts remain" in (outcome.error or "")
    assert _snapshot(left) == starting
    assert untracked.read_text(encoding="utf-8") == "keep\n"
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert git(["diff", "--name-only", "--diff-filter=U"], left).stdout == ""
    require_sdd_repository_health(left)


def test_fetch_failure_is_typed_only_when_repository_remains_healthy(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "clone"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    git(["remote", "set-url", "origin", str(tmp_path / "missing.git")], clone_dir)
    starting = _snapshot(clone_dir)

    outcome = integrate_sdd_repository(clone_dir)

    assert outcome.status is SddIntegrationStatus.REMOTE_UNAVAILABLE
    assert outcome.structurally_healthy is True
    assert _snapshot(clone_dir) == starting
    require_sdd_repository_health(clone_dir)


def test_successful_integration_updates_shared_freshness_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "clone"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"bead_refresh": {"ttl_seconds": 120}}},
    )

    assert integration_is_fresh(clone_dir) is False

    outcome = integrate_sdd_repository(clone_dir)

    assert outcome.succeeded is True
    assert outcome.upstream_present is True
    assert integration_is_fresh(clone_dir) is True


def test_strict_clone_refuses_preexisting_rebase_without_modifying_it(
    tmp_path: Path,
) -> None:
    remote, left, _right = _build_diverged_clones(tmp_path)
    git(["fetch", "origin"], left)
    started = subprocess.run(
        ["git", "rebase", "origin/main"],
        cwd=left,
        check=False,
        capture_output=True,
        text=True,
    )
    assert started.returncode != 0
    before_head = git(["rev-parse", "HEAD"], left).stdout
    before_status = git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"], left
    ).stdout

    with pytest.raises(SddMaterializationError, match="not safe to write"):
        ensure_sidecar_sdd_clone(left, str(remote), strict=True)

    assert git(["rev-parse", "HEAD"], left).stdout == before_head
    assert (
        git(["status", "--porcelain=v1", "-z", "--untracked-files=all"], left).stdout
        == before_status
    )
    assert (left / ".git/rebase-merge").exists() or (
        left / ".git/rebase-apply"
    ).exists()


def test_injected_rebase_failure_without_operation_restores_cleanly(
    tmp_path: Path,
) -> None:
    _remote, left, _right = _build_diverged_clones(
        tmp_path,
        relative_path="remote.md",
        local="local base\n",
        remote_text="remote base\n",
    )
    starting = _snapshot(left)

    def fail_rebase(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["rebase"]:
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected rebase failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository(left, git_runner=fail_rebase)

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    assert "injected rebase failure" in (outcome.error or "")
    assert _snapshot(left) == starting


def test_injected_continue_failure_aborts_after_semantic_repair(
    tmp_path: Path,
) -> None:
    issue_base = '{"id":"item","title":"base"}\n'
    _remote, left, _right = _build_diverged_clones(
        tmp_path,
        relative_path="beads/issues.jsonl",
        base=issue_base,
        local='{"id":"item","title":"local"}\n',
        remote_text='{"id":"item","title":"remote"}\n',
    )
    starting = _snapshot(left)

    def fail_continue(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[-2:] == ["rebase", "--continue"]:
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected continue failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository(
        left,
        beads_dir=left / "beads",
        git_runner=fail_continue,
    )

    assert outcome.status is SddIntegrationStatus.ABORTED_UNSUPPORTED_CONFLICTS
    assert outcome.restored is True
    assert "injected continue failure" in (outcome.error or "")
    assert _snapshot(left) == starting
    assert not (left / "beads/events/manifest.json").exists()


def test_injected_abort_failure_reports_primary_and_rollback_failures(
    tmp_path: Path,
) -> None:
    _remote, left, _right = _build_diverged_clones(tmp_path)

    def fail_abort(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args == ["rebase", "--abort"]:
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected abort failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_sdd_repository(
        left,
        beads_dir=left / "beads",
        git_runner=fail_abort,
    )

    assert outcome.status is SddIntegrationStatus.UNRECOVERABLE
    assert outcome.structurally_healthy is False
    assert "git rebase failed" in (outcome.error or "")
    assert "injected abort failure" in (outcome.error or "")
    assert "rollback verification failed" in (outcome.error or "")
    assert (left / ".git/rebase-merge").exists() or (
        left / ".git/rebase-apply"
    ).exists()
