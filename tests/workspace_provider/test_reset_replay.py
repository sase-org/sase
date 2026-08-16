"""Reset-and-replay conflict recovery coverage (sase-mq.3)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from sase.workspace_provider.lease import OperationalLease
from sase.workspace_provider.ownership import (
    AccessKind,
    MutationOrigin,
    OperationContext,
    WorkspaceOwnershipError,
)
from sase.workspace_provider.reset_replay import (
    DEFAULT_MAX_ATTEMPTS,
    ReplayConflict,
    ReplayDeferred,
    ResetReplayError,
    ResetReplayResult,
    reset_and_replay,
)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _init_origin(path: Path) -> None:
    path.mkdir(parents=True)
    _run(["init", "-q", "-b", "main"], path)
    _run(["config", "user.email", "test@test.com"], path)
    _run(["config", "user.name", "Test"], path)
    (path / "README.md").write_text("origin v1\n", encoding="utf-8")
    _run(["add", "."], path)
    _run(["commit", "-q", "-m", "init"], path)


def _clone(origin: Path, target: Path) -> Path:
    _run(["clone", "-q", str(origin), str(target)], target.parent)
    _run(["config", "user.email", "test@test.com"], target)
    _run(["config", "user.name", "Test"], target)
    return target


def _head(repo: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _advance_origin(origin: Path, content: str) -> None:
    (origin / "README.md").write_text(content, encoding="utf-8")
    _run(["commit", "-aq", "-m", "advance"], origin)


def _put_checkout_in_stale_rebase(checkout: Path, origin: Path) -> None:
    """Diverge *checkout* from *origin* and leave a conflicted, mid-rebase state."""

    _advance_origin(origin, "origin v2\n")
    (checkout / "README.md").write_text("local v2\n", encoding="utf-8")
    _run(["commit", "-aq", "-m", "local divergent change"], checkout)
    _run(["fetch", "-q", "origin"], checkout)
    subprocess.run(
        ["git", "rebase", "origin/main"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
    )
    git_dir_result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=checkout,
        check=True,
        capture_output=True,
        text=True,
    )
    git_dir = Path(git_dir_result.stdout.strip())
    if not git_dir.is_absolute():
        git_dir = checkout / git_dir
    assert (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()


def _context(
    checkout: Path,
    primary: Path,
    *,
    access_kind: AccessKind = AccessKind.LEASED_OPERATIONAL,
    workspace_num: int = 10,
    no_claim: bool = False,
) -> OperationContext:
    return OperationContext(
        project="demo",
        access_kind=access_kind,
        mutation_origin=MutationOrigin.MACHINE,
        workspace_num=workspace_num,
        checkout_dir=checkout,
        primary_checkout_dir=primary,
        project_file=None,
        claim_pid=None if no_claim else os.getpid(),
        claim_workflow="chop:demo",
    )


class TestRefusesUnauthorizedContexts:
    def test_refuses_primary_workspace(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary"
        checkout.mkdir()
        context = _context(checkout, checkout, workspace_num=0)
        with pytest.raises(WorkspaceOwnershipError, match="primary workspace #0"):
            reset_and_replay(context, checkout, lambda: "ok")

    def test_refuses_read_only_canonical(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary"
        checkout.mkdir()
        context = _context(
            checkout, checkout, access_kind=AccessKind.READ_ONLY_CANONICAL
        )
        with pytest.raises(WorkspaceOwnershipError, match="leased operational context"):
            reset_and_replay(context, checkout, lambda: "ok")

    def test_refuses_user_directed(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj"
        checkout.mkdir()
        context = _context(checkout, checkout, access_kind=AccessKind.USER_DIRECTED)
        with pytest.raises(WorkspaceOwnershipError, match="leased operational context"):
            reset_and_replay(context, checkout, lambda: "ok")

    def test_refuses_primary_sidecar_sync(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary--beads"
        checkout.mkdir()
        primary = tmp_path / "primary"
        primary.mkdir()
        context = _context(
            checkout, primary, access_kind=AccessKind.PRIMARY_SIDECAR_SYNC
        )
        with pytest.raises(WorkspaceOwnershipError, match="leased operational context"):
            reset_and_replay(context, checkout, lambda: "ok")

    def test_refuses_missing_live_claim(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        primary = tmp_path / "proj"
        primary.mkdir()
        context = _context(checkout, primary, no_claim=True)
        with pytest.raises(WorkspaceOwnershipError, match="no live workspace claim"):
            reset_and_replay(context, checkout, lambda: "ok")

    def test_refuses_repo_outside_checkout(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        primary = tmp_path / "proj"
        primary.mkdir()
        context = _context(checkout, primary)
        with pytest.raises(WorkspaceOwnershipError, match="outside leased checkout"):
            reset_and_replay(context, outside, lambda: "ok")

    def test_no_git_commands_run_before_authorization_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        checkout = tmp_path / "primary"
        checkout.mkdir()
        context = _context(checkout, checkout, workspace_num=0)
        called = False

        def _boom(*_args: object, **_kwargs: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(
            "sase.workspace_provider.reset_replay._run_git",
            _boom,
        )
        with pytest.raises(WorkspaceOwnershipError):
            reset_and_replay(context, checkout, lambda: "ok")
        assert called is False


class TestSuccessfulReplay:
    def test_first_attempt_success_does_not_reset(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            return "done"

        result = reset_and_replay(context, checkout, _operation)
        assert result == ResetReplayResult(
            value="done",
            attempts=1,
            reset_performed=False,
            recovery_ref=None,
        )
        assert n == 1

    def test_max_attempts_defaults_to_three(self) -> None:
        assert DEFAULT_MAX_ATTEMPTS == 3


class TestConflictTriggersResetAndReplay:
    def test_stale_rebase_is_reset_and_operation_is_replayed(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        _put_checkout_in_stale_rebase(checkout, origin)
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            if n == 1:
                raise ReplayConflict("stale rebase detected")
            return "recovered"

        result = reset_and_replay(context, checkout, _operation)
        assert result.value == "recovered"
        assert result.attempts == 2
        assert result.reset_performed is True
        assert result.recovery_ref is not None
        assert n == 2
        git_dir = checkout / ".git"
        assert not (git_dir / "rebase-merge").exists()
        assert not (git_dir / "rebase-apply").exists()
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=checkout,
            check=True,
            capture_output=True,
            text=True,
        )
        assert status.stdout.strip() == ""
        assert _head(checkout) == _head(origin)
        show = subprocess.run(
            ["git", "cat-file", "-e", result.recovery_ref],
            cwd=checkout,
            check=False,
        )
        assert show.returncode == 0

    def test_semantic_push_race_conflict_resets_to_new_upstream_tip(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        _advance_origin(origin, "origin v2\n")
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            if n == 1:
                raise ReplayConflict("non-fast-forward push race")
            return "published"

        result = reset_and_replay(context, checkout, _operation)
        assert result.value == "published"
        assert result.attempts == 2
        assert n == 2
        assert _head(checkout) == _head(origin)

    def test_clear_paths_removes_lease_owned_state_on_reset(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        generated = checkout / ".sase" / "sdd" / "beads"
        generated.mkdir(parents=True)
        (generated / "stale.txt").write_text("stale\n", encoding="utf-8")
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            if n == 1:
                raise ReplayConflict("stale generated sidecar state")
            return "ok"

        result = reset_and_replay(
            context, checkout, _operation, clear_paths=[generated]
        )
        assert result.value == "ok"
        assert not generated.exists()

    def test_clear_paths_outside_checkout_are_refused(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        outside = tmp_path / "outside"
        _init_origin(origin)
        _clone(origin, checkout)
        outside.mkdir()
        context = _context(checkout, tmp_path / "proj")

        def _operation() -> str:
            raise ReplayConflict("conflict")

        with pytest.raises(WorkspaceOwnershipError, match="outside leased checkout"):
            reset_and_replay(
                context,
                checkout,
                _operation,
                max_attempts=2,
                clear_paths=[outside],
            )


class TestRetryExhaustionAndOtherFailures:
    def test_retry_exhaustion_raises_reset_replay_error(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            raise ReplayConflict("always conflicts")

        with pytest.raises(ResetReplayError, match="exhausted 2 attempt") as exc_info:
            reset_and_replay(context, checkout, _operation, max_attempts=2)
        assert exc_info.value.attempts == 2
        assert isinstance(exc_info.value.last_error, ReplayConflict)
        assert n == 2

    def test_remote_unavailable_defers_without_git_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("deferred retries must not run git")

        monkeypatch.setattr(
            "sase.workspace_provider.reset_replay._run_git",
            _boom,
        )
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            raise ReplayDeferred("remote unavailable")

        with pytest.raises(ResetReplayError, match="remote unavailable"):
            reset_and_replay(context, checkout, _operation, max_attempts=2)
        assert n == 2

    def test_lock_contention_defers_and_then_succeeds(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            if n == 1:
                raise ReplayDeferred("store write lock unavailable")
            return "ok"

        result = reset_and_replay(context, checkout, _operation)
        assert result.value == "ok"
        assert result.reset_performed is False
        assert n == 2

    def test_other_exceptions_propagate_without_retry(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            raise ValueError("not a conflict/defer signal")

        with pytest.raises(ValueError, match="not a conflict/defer signal"):
            reset_and_replay(context, checkout, _operation)
        assert n == 1

    def test_max_attempts_must_be_positive(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        with pytest.raises(ValueError, match="max_attempts"):
            reset_and_replay(context, checkout, lambda: "ok", max_attempts=0)


class TestOperationalLeaseResetAndReplay:
    def test_lease_method_replays_on_conflict(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        _advance_origin(origin, "origin v2\n")
        lease = OperationalLease(
            project="demo",
            workflow="chop:demo",
            holder="holder",
            workspace_num=10,
            checkout_dir=checkout,
            project_file=tmp_path / "demo.sase",
            claim_pid=os.getpid(),
            cl_name="holder",
            context=_context(checkout, tmp_path / "proj"),
        )
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            if n == 1:
                raise ReplayConflict("plan merge conflict")
            return "archived"

        result = lease.reset_and_replay(_operation)
        assert result.value == "archived"
        assert result.reset_performed is True
        assert n == 2
        assert _head(checkout) == _head(origin)
