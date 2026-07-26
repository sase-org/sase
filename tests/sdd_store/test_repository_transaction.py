"""Transactional integration and repository-health regression coverage."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.sdd._git import run_sdd_git
from sase.sdd._integration_marker import integration_is_fresh
from sase.sdd._repository_transaction import (
    SddIntegrationStatus,
    integrate_machine_managed_sdd_repository,
    integrate_sdd_repository,
    require_sdd_repository_health,
)
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


def _enable_ambient_rerere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    global_config = tmp_path / "gitconfig"
    global_config.write_text(
        "[rerere]\n\tenabled = true\n\tautoupdate = true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


def _rr_cache_files(repo: Path) -> tuple[Path, ...]:
    rr_cache = repo / ".git" / "rr-cache"
    if not rr_cache.exists():
        return ()
    return tuple(path for path in rr_cache.rglob("*") if path.is_file())


def test_sdd_git_runner_disables_ambient_rerere(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(["init", "-q"], repo)
    _enable_ambient_rerere(tmp_path, monkeypatch)

    enabled = run_sdd_git(
        ["config", "--get", "rerere.enabled"],
        cwd=repo,
        op="test.rerere.enabled",
        check=False,
        capture_output=True,
        text=True,
    )
    autoupdate = run_sdd_git(
        ["config", "--get", "rerere.autoupdate"],
        cwd=repo,
        op="test.rerere.autoupdate",
        check=False,
        capture_output=True,
        text=True,
    )

    assert enabled.stdout.strip() == "false"
    assert autoupdate.stdout.strip() == "false"


def test_machine_managed_integration_does_not_create_rerere_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _remote, left, _right = _build_diverged_clones(tmp_path)
    _enable_ambient_rerere(tmp_path, monkeypatch)

    outcome = integrate_machine_managed_sdd_repository(
        left,
        recovery_cooldown_seconds=0,
    )

    assert outcome.status is SddIntegrationStatus.RECOVERED
    assert _rr_cache_files(left) == ()


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


def test_rebase_recovers_planted_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    left = tmp_path / "left"
    right = tmp_path / "right"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, left)
    clone(remote, right)
    (left / "local.md").write_text("local\n", encoding="utf-8")
    commit_all(left, "local change")
    (right / "remote.md").write_text("remote\n", encoding="utf-8")
    commit_all(right, "remote change")
    git(["push"], right)

    lock_path = left / ".git" / "index.lock"
    lock_path.touch()
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001")
    monkeypatch.delenv("SASE_SDD_GIT_LOCK_RETRY_DELAYS", raising=False)

    outcome = integrate_sdd_repository(left)

    assert outcome.succeeded is True
    assert outcome.integrated is True
    assert not lock_path.exists()
    assert (left / "local.md").read_text(encoding="utf-8") == "local\n"
    assert (left / "remote.md").read_text(encoding="utf-8") == "remote\n"
    require_sdd_repository_health(left)


@pytest.mark.parametrize("backend", ["merge", "apply"])
def test_machine_managed_clone_recovers_preexisting_rebase(
    tmp_path: Path,
    backend: str,
) -> None:
    _remote, left, right = _build_diverged_clones(tmp_path)
    git(["fetch", "origin"], left)
    started = subprocess.run(
        ["git", "rebase", f"--{backend}", "origin/main"],
        cwd=left,
        check=False,
        capture_output=True,
        text=True,
    )
    assert started.returncode != 0
    original_branch_head = git(["rev-parse", "refs/heads/main"], left).stdout.strip()
    marker = left / ".git" / f"rebase-{backend}"
    assert marker.exists()

    outcome = integrate_machine_managed_sdd_repository(left)

    assert outcome.status is SddIntegrationStatus.RECOVERED
    assert outcome.recovery_ref is not None
    assert git(["rev-parse", outcome.recovery_ref], left).stdout.strip() == (
        original_branch_head
    )
    assert git(["show", f"{outcome.recovery_ref}:plans/shared.md"], left).stdout == (
        "local\n"
    )
    assert (
        git(["rev-parse", "HEAD"], left).stdout
        == git(["rev-parse", "HEAD"], right).stdout
    )
    assert git(["symbolic-ref", "--short", "HEAD"], left).stdout.strip() == "main"
    assert not (left / ".git/rebase-merge").exists()
    assert not (left / ".git/rebase-apply").exists()
    assert git(["diff", "--name-only", "--diff-filter=U"], left).stdout == ""
    assert git(["status", "--porcelain"], left).stdout == ""
    require_sdd_repository_health(left)


def test_machine_managed_recovery_snapshots_dirty_index_and_untracked_files(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)

    (seed / "remote.md").write_text("remote\n", encoding="utf-8")
    commit_all(seed, "advance remote")
    git(["push"], seed)
    remote_head = git(["rev-parse", "HEAD"], seed).stdout.strip()

    (clone_dir / "README.md").write_text("dirty tracked\n", encoding="utf-8")
    (clone_dir / "staged.md").write_text("dirty staged\n", encoding="utf-8")
    git(["add", "staged.md"], clone_dir)
    (clone_dir / "untracked.md").write_text("dirty untracked\n", encoding="utf-8")

    outcome = integrate_machine_managed_sdd_repository(clone_dir)

    assert outcome.status is SddIntegrationStatus.RECOVERED
    assert outcome.recovery_ref is not None
    assert git(["rev-parse", "HEAD"], clone_dir).stdout.strip() == remote_head
    assert git(["status", "--porcelain"], clone_dir).stdout == ""
    assert git(["show", f"{outcome.recovery_ref}:README.md"], clone_dir).stdout == (
        "dirty tracked\n"
    )
    assert git(["show", f"{outcome.recovery_ref}:staged.md"], clone_dir).stdout == (
        "dirty staged\n"
    )
    assert (
        git(["show", f"{outcome.recovery_ref}^3:untracked.md"], clone_dir).stdout
        == "dirty untracked\n"
    )
    assert outcome.recovery_ref in git(["stash", "list"], clone_dir).stdout
    require_sdd_repository_health(clone_dir)


def test_generic_integration_preserves_dirty_state_without_recovery(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    (seed / "remote.md").write_text("remote\n", encoding="utf-8")
    commit_all(seed, "advance remote")
    git(["push"], seed)

    (clone_dir / "README.md").write_text("keep dirty\n", encoding="utf-8")
    starting = _snapshot(clone_dir)

    outcome = integrate_sdd_repository(clone_dir)

    assert outcome.status is SddIntegrationStatus.LOCAL_CHANGES
    assert _snapshot(clone_dir) == starting
    assert git(["for-each-ref", "refs/sase/recovery"], clone_dir).stdout == ""


@pytest.mark.parametrize("failure_stage", ["create", "verify", "verify_after_stash"])
def test_failed_recovery_snapshot_does_not_reset_managed_branch(
    tmp_path: Path,
    failure_stage: str,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    (seed / "remote.md").write_text("remote\n", encoding="utf-8")
    commit_all(seed, "advance remote")
    git(["push"], seed)
    (clone_dir / "README.md").write_text("keep dirty\n", encoding="utf-8")
    starting = _snapshot(clone_dir)

    recovery_verifications = 0

    def fail_snapshot_ref(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal recovery_verifications
        fail_create = failure_stage == "create" and args[:1] == ["update-ref"]
        recovery_verify = args[:2] == ["rev-parse", "--verify"] and args[-1].startswith(
            "refs/sase/recovery/"
        )
        if recovery_verify:
            recovery_verifications += 1
        fail_verify = recovery_verify and (
            (failure_stage == "verify" and recovery_verifications == 1)
            or (failure_stage == "verify_after_stash" and recovery_verifications == 2)
        )
        if fail_create or fail_verify:
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected snapshot failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    outcome = integrate_machine_managed_sdd_repository(
        clone_dir,
        git_runner=fail_snapshot_ref,
        recovery_cooldown_seconds=0,
    )

    assert outcome.status is SddIntegrationStatus.RECOVERY_FAILED
    if failure_stage == "create":
        assert "injected snapshot failure" in (outcome.error or "")
    else:
        assert "could not verify the recovery ref" in (outcome.error or "")
    assert _snapshot(clone_dir) == starting


def test_recovery_attempt_cooldown_is_durable_and_reopens_after_window(
    tmp_path: Path,
) -> None:
    remote = tmp_path / "plans.git"
    seed = tmp_path / "seed"
    clone_dir = tmp_path / "plans"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text("base\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    clone(remote, clone_dir)
    (clone_dir / "README.md").write_text("keep dirty\n", encoding="utf-8")

    attempts: list[list[str]] = []
    now = [100.0]

    def fail_snapshot_ref(
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[:1] == ["update-ref"]:
            attempts.append(args)
            return subprocess.CompletedProcess(
                ["git", *args], 1, stdout="", stderr="injected snapshot failure"
            )
        return _runner(repo_root, args, op=op, network=network)

    def recover():
        return integrate_machine_managed_sdd_repository(
            clone_dir,
            git_runner=fail_snapshot_ref,
            clock=lambda: now[0],
            recovery_cooldown_seconds=10,
        )

    assert recover().status is SddIntegrationStatus.RECOVERY_FAILED
    assert recover().status is SddIntegrationStatus.RECOVERY_COOLDOWN
    assert len(attempts) == 1

    now[0] = 111.0
    assert recover().status is SddIntegrationStatus.RECOVERY_FAILED
    assert len(attempts) == 2


def test_machine_managed_recovery_refuses_unrelated_git_operation(
    tmp_path: Path,
) -> None:
    _remote, left, _right = _build_diverged_clones(tmp_path)
    git(["fetch", "origin"], left)
    started = subprocess.run(
        ["git", "merge", "origin/main"],
        cwd=left,
        check=False,
        capture_output=True,
        text=True,
    )
    assert started.returncode != 0
    assert (left / ".git/MERGE_HEAD").exists()
    starting = _snapshot(left)

    outcome = integrate_machine_managed_sdd_repository(left)

    assert outcome.status is SddIntegrationStatus.UNRECOVERABLE
    assert "refuses unrelated Git operations: merge" in (outcome.error or "")
    assert _snapshot(left) == starting
    assert (left / ".git/MERGE_HEAD").exists()
    assert git(["for-each-ref", "refs/sase/recovery"], left).stdout == ""


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
