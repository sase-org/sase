"""Reset-and-replay conflict recovery coverage (sase-mq.3)."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

import sase.workspace_provider.reset_replay as reset_replay
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
    ResetRecoveryOutcome,
    ResetReplayResult,
    reset_and_replay,
    reset_leased_checkout_to_upstream,
    reset_leased_checkout_to_upstream_with_recovery,
)
from sase.workspace_provider.snapshot import PreservationError, restore_git_snapshot
from tests.workspace_provider.test_rescue._helpers import redirect_state


@pytest.fixture(autouse=True)
def _redirect_rescue_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    redirect_state(tmp_path, monkeypatch)


def _run(args: list[str], cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def _run_capture(args: list[str], cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


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


def _plant_index_lock(repo: Path, *, age_seconds: float) -> Path:
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale\n", encoding="utf-8")
    stamped = time.time() - age_seconds
    os.utime(lock, (stamped, stamped))
    return lock


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


def _assert_reset_entry_points_refused(
    context: OperationContext,
    repo_root: Path,
    match: str,
) -> None:
    with pytest.raises(WorkspaceOwnershipError, match=match):
        reset_and_replay(context, repo_root, lambda: "ok")
    with pytest.raises(WorkspaceOwnershipError, match=match):
        reset_leased_checkout_to_upstream(context, repo_root)


class TestRefusesUnauthorizedContexts:
    def test_refuses_primary_workspace(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary"
        checkout.mkdir()
        context = _context(checkout, checkout, workspace_num=0)
        _assert_reset_entry_points_refused(context, checkout, "primary workspace #0")

    def test_refuses_read_only_canonical(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary"
        checkout.mkdir()
        context = _context(
            checkout, checkout, access_kind=AccessKind.READ_ONLY_CANONICAL
        )
        _assert_reset_entry_points_refused(
            context, checkout, "leased operational context"
        )

    def test_refuses_user_directed(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj"
        checkout.mkdir()
        context = _context(checkout, checkout, access_kind=AccessKind.USER_DIRECTED)
        _assert_reset_entry_points_refused(
            context, checkout, "leased operational context"
        )

    def test_refuses_primary_sidecar_sync(self, tmp_path: Path) -> None:
        checkout = tmp_path / "primary--beads"
        checkout.mkdir()
        primary = tmp_path / "primary"
        primary.mkdir()
        context = _context(
            checkout, primary, access_kind=AccessKind.PRIMARY_SIDECAR_SYNC
        )
        _assert_reset_entry_points_refused(
            context, checkout, "leased operational context"
        )

    def test_refuses_missing_live_claim(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        primary = tmp_path / "proj"
        primary.mkdir()
        context = _context(checkout, primary, no_claim=True)
        _assert_reset_entry_points_refused(context, checkout, "no live workspace claim")

    def test_refuses_repo_outside_checkout(self, tmp_path: Path) -> None:
        checkout = tmp_path / "proj_10"
        checkout.mkdir()
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        primary = tmp_path / "proj"
        primary.mkdir()
        context = _context(checkout, primary)
        _assert_reset_entry_points_refused(context, outside, "outside leased checkout")

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
        with pytest.raises(WorkspaceOwnershipError):
            reset_leased_checkout_to_upstream(context, checkout)
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
        assert len(result.recovery_locations) == 1
        manifest_path = Path(result.recovery_locations[0])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["unmerged"] is True
        assert any(
            marker in {"rebase-merge", "rebase-apply"}
            for marker in manifest["operation_markers"]
        )
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

    def test_dirty_tracked_and_untracked_work_recover_after_replay_reset(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        _init_origin(origin)
        (origin / "src").mkdir()
        (origin / "src" / "dispatch.py").write_bytes(b"dispatch base\n")
        _run(["add", "src/dispatch.py"], origin)
        _run(["commit", "-q", "-m", "add dispatch"], origin)
        checkout = tmp_path / "proj_10"
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        tracked = checkout / "src" / "dispatch.py"
        untracked = checkout / "src" / "new_impl.py"
        tracked_bytes = b"tracked dispatch change\x00with binary-safe bytes\n"
        untracked_bytes = b"new implementation\x00source\n"
        attempts = 0

        def _operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                tracked.write_bytes(tracked_bytes)
                untracked.write_bytes(untracked_bytes)
                raise ReplayConflict("dispatch publication conflicted")
            return "recovered"

        result = reset_and_replay(context, checkout, _operation)

        assert result.value == "recovered"
        assert len(result.recovery_locations) == 1
        manifest_path = Path(result.recovery_locations[0])
        assert manifest_path.is_absolute()
        assert manifest_path.is_file()
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["snapshot_id"]
        assert tracked.read_bytes() != tracked_bytes

        restored = tmp_path / "restored"
        _clone(origin, restored)
        restore_git_snapshot(manifest_path, restored)
        assert (restored / "src" / "dispatch.py").read_bytes() == tracked_bytes
        assert (restored / "src" / "new_impl.py").read_bytes() == untracked_bytes

        # Exercise the normal post-reset cleanup path after proving the external
        # snapshot can restore the bytes without the original checkout.
        _run(
            ["stash", "push", "--include-untracked", "-m", "post-reset cleanup"],
            checkout,
        )
        assert "post-reset cleanup" in _run_capture(["stash", "list"], checkout)

    def test_untracked_path_collision_with_upstream_is_snapshotted(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        _init_origin(origin)
        checkout = tmp_path / "proj_10"
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        collision = checkout / "collision.py"
        collision.write_bytes(b"local untracked\x00bytes")
        _advance_origin(origin, "origin v2\n")
        (origin / "collision.py").write_bytes(b"upstream tracked bytes\n")
        _run(["add", "collision.py"], origin)
        _run(["commit", "-q", "-m", "upstream collision"], origin)

        attempts = 0

        def _operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ReplayConflict("upstream added an untracked path")
            return "recovered"

        result = reset_and_replay(context, checkout, _operation, max_attempts=2)

        assert (checkout / "collision.py").read_bytes() == b"upstream tracked bytes\n"
        assert len(result.recovery_locations) == 1
        restored = tmp_path / "restored-collision"
        _clone(origin, restored)
        restore_git_snapshot(result.recovery_locations[0], restored)
        assert (restored / "collision.py").read_bytes() == b"local untracked\x00bytes"
        assert "collision.py" not in _run_capture(["ls-files"], restored)

    def test_delete_modify_conflict_bytes_recover_after_reset(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        _init_origin(origin)
        (origin / "conflict.txt").write_text("base\n", encoding="utf-8")
        _run(["add", "conflict.txt"], origin)
        _run(["commit", "-q", "-m", "base conflict"], origin)
        checkout = tmp_path / "proj_10"
        _clone(origin, checkout)
        _run(["checkout", "-b", "theirs"], checkout)
        (checkout / "conflict.txt").write_text("theirs\n", encoding="utf-8")
        _run(["commit", "-aq", "-m", "theirs change"], checkout)
        _run(["checkout", "-q", "main"], checkout)
        _run(["rm", "--", "conflict.txt"], checkout)
        _run(["commit", "-q", "-m", "delete on main"], checkout)
        merge = subprocess.run(
            ["git", "merge", "theirs"],
            cwd=checkout,
            capture_output=True,
            text=True,
        )
        assert merge.returncode != 0
        unique = b"unique manual conflict edits\n"
        (checkout / "conflict.txt").write_bytes(unique)
        src_stage = _run_capture(
            ["ls-files", "--stage", "--", "conflict.txt"], checkout
        )
        assert " 1\tconflict.txt" in src_stage
        assert " 3\tconflict.txt" in src_stage
        context = _context(checkout, tmp_path / "proj")
        attempts = 0

        def _operation() -> str:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise ReplayConflict("delete/modify conflict")
            return "recovered"

        result = reset_and_replay(context, checkout, _operation)

        assert result.value == "recovered"
        # Reset is to the verified upstream tip (origin/main still has the
        # base file). Live conflict bytes live in the snapshot, not HEAD.
        assert (checkout / "conflict.txt").read_text(encoding="utf-8") == "base\n"
        assert _run_capture(["status", "--porcelain"], checkout).strip() == ""
        assert len(result.recovery_locations) == 1
        restored = tmp_path / "restored-du"
        restored.mkdir()
        restore_git_snapshot(result.recovery_locations[0], restored)
        assert (restored / "conflict.txt").read_bytes() == unique
        dest_stage = _run_capture(
            ["ls-files", "--stage", "--", "conflict.txt"], restored
        )
        assert dest_stage == src_stage

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

    def test_clear_paths_preserve_dirty_nested_git_repo(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        (origin / ".gitignore").write_text("sase/repos/\n", encoding="utf-8")
        _run(["add", ".gitignore"], origin)
        _run(["commit", "-q", "-m", "ignore nested repos"], origin)
        _clone(origin, checkout)
        nested_origin = tmp_path / "nested-origin"
        _init_origin(nested_origin)
        nested = checkout / "sase" / "repos" / "linked" / "plugin"
        nested.parent.mkdir(parents=True)
        _clone(nested_origin, nested)
        (nested / "README.md").write_text("nested staged\n", encoding="utf-8")
        _run(["add", "README.md"], nested)
        (nested / "README.md").write_text("nested working\n", encoding="utf-8")
        (nested / "untracked.txt").write_text("nested untracked\n", encoding="utf-8")
        nested_stage = _run_capture(["ls-files", "--stage", "--", "README.md"], nested)
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            if n == 1:
                raise ReplayConflict("clear nested clones")
            return "ok"

        result = reset_and_replay(
            context, checkout, _operation, clear_paths=[checkout / "sase" / "repos"]
        )
        assert result.value == "ok"
        assert not nested.exists()
        assert len(result.recovery_locations) == 1
        restored = tmp_path / "restored-nested-clear"
        restored.mkdir()
        restore_git_snapshot(result.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == (
            "nested working\n"
        )
        assert (restored / "untracked.txt").read_text(encoding="utf-8") == (
            "nested untracked\n"
        )
        assert (
            _run_capture(["ls-files", "--stage", "--", "README.md"], restored)
            == nested_stage
        )

    def test_clear_paths_refuse_when_nested_snapshot_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        (origin / ".gitignore").write_text("sase/repos/\n", encoding="utf-8")
        _run(["add", ".gitignore"], origin)
        _run(["commit", "-q", "-m", "ignore nested repos"], origin)
        _clone(origin, checkout)
        nested_origin = tmp_path / "nested-origin"
        _init_origin(nested_origin)
        nested = checkout / "sase" / "repos" / "linked" / "plugin"
        nested.parent.mkdir(parents=True)
        _clone(nested_origin, nested)
        (nested / "README.md").write_text("must remain\n", encoding="utf-8")
        context = _context(checkout, tmp_path / "proj")

        def boom(*args: object, **kwargs: object) -> object:
            del args, kwargs
            raise PreservationError("injected nested capture failure")

        monkeypatch.setattr(reset_replay, "preserve_nested_repositories", boom)

        def _operation() -> str:
            raise ReplayConflict("clear nested clones")

        with pytest.raises(ResetReplayError, match="nested"):
            reset_and_replay(
                context,
                checkout,
                _operation,
                max_attempts=2,
                clear_paths=[checkout / "sase" / "repos"],
            )
        assert (nested / "README.md").read_text(encoding="utf-8") == "must remain\n"

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
    def test_retry_exhaustion_keeps_recovery_locations_from_prior_reset(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            (checkout / "README.md").write_text(f"attempt {n}\n", encoding="utf-8")
            raise ReplayConflict("always conflicts")

        with pytest.raises(ResetReplayError, match="exhausted 2 attempt") as exc_info:
            reset_and_replay(context, checkout, _operation, max_attempts=2)
        assert exc_info.value.attempts == 2
        assert isinstance(exc_info.value.last_error, ReplayConflict)
        assert exc_info.value.recovery_ref is not None
        assert len(exc_info.value.recovery_locations) == 1
        assert exc_info.value.recovery_locations[0] in str(exc_info.value)
        restored = tmp_path / "restored-exhaustion"
        _clone(origin, restored)
        restore_git_snapshot(exc_info.value.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == "attempt 1\n"
        assert n == 2

    def test_each_retry_snapshot_is_retained(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        n = 0

        def _operation() -> str:
            nonlocal n
            n += 1
            if n < 3:
                (checkout / "README.md").write_text(f"attempt {n}\n", encoding="utf-8")
                raise ReplayConflict(f"conflict {n}")
            return "done"

        result = reset_and_replay(context, checkout, _operation, max_attempts=3)

        assert result.recovery_locations == tuple(
            dict.fromkeys(result.recovery_locations)
        )
        assert len(result.recovery_locations) == 2
        assert result.recovery_locations[0] != result.recovery_locations[1]
        for number, location in enumerate(result.recovery_locations, start=1):
            restored = tmp_path / f"restored-attempt-{number}"
            _clone(origin, restored)
            restore_git_snapshot(location, restored)
            assert (restored / "README.md").read_text(encoding="utf-8") == (
                f"attempt {number}\n"
            )

    def test_fetch_failure_after_snapshot_names_recovery_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        (checkout / "README.md").write_text("dirty before fetch\n", encoding="utf-8")
        real_run_git = reset_replay._run_git

        def _fail_fetch(
            args: list[str], repo_root: Path
        ) -> subprocess.CompletedProcess[str]:
            if args[:1] == ["fetch"]:
                return subprocess.CompletedProcess(
                    ["git", *args], 1, stdout="", stderr="forced fetch failure"
                )
            return real_run_git(args, repo_root)

        monkeypatch.setattr(reset_replay, "_run_git", _fail_fetch)

        def _operation() -> str:
            raise ReplayConflict("needs reset")

        with pytest.raises(ResetReplayError, match="forced fetch failure") as exc_info:
            reset_and_replay(context, checkout, _operation, max_attempts=2)

        assert exc_info.value.recovery_ref is not None
        assert len(exc_info.value.recovery_locations) == 1
        assert exc_info.value.recovery_locations[0] in str(exc_info.value)
        restored = tmp_path / "restored-fetch-failure"
        _clone(origin, restored)
        restore_git_snapshot(exc_info.value.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == (
            "dirty before fetch\n"
        )
        assert (checkout / "README.md").read_text(encoding="utf-8") == (
            "dirty before fetch\n"
        )

    @pytest.mark.parametrize("failure_stage", ["abort", "reset"])
    def test_abort_and_reset_failures_keep_snapshot_locations(
        self,
        failure_stage: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        (checkout / "README.md").write_text("dirty before failure\n", encoding="utf-8")

        if failure_stage == "abort":

            def _fail_abort(_repo_root: Path) -> None:
                raise reset_replay._ResetFailure("forced abort failure")

            monkeypatch.setattr(
                reset_replay, "_abort_in_progress_operations", _fail_abort
            )
        else:
            real_mutation = reset_replay._run_git_mutation

            def _fail_reset(
                args: list[str], repo_root: Path
            ) -> subprocess.CompletedProcess[str]:
                if args[:2] == ["reset", "--hard"]:
                    return subprocess.CompletedProcess(
                        ["git", *args], 1, stdout="", stderr="forced reset failure"
                    )
                return real_mutation(args, repo_root)

            monkeypatch.setattr(reset_replay, "_run_git_mutation", _fail_reset)

        def _operation() -> str:
            raise ReplayConflict("needs reset")

        with pytest.raises(ResetReplayError) as exc_info:
            reset_and_replay(context, checkout, _operation, max_attempts=2)

        assert len(exc_info.value.recovery_locations) == 1
        assert exc_info.value.recovery_locations[0] in str(exc_info.value)
        if failure_stage == "reset":
            assert "forced reset failure" in str(exc_info.value)
            assert exc_info.value.recovery_ref is not None
        restored = tmp_path / f"restored-{failure_stage}-failure"
        _clone(origin, restored)
        restore_git_snapshot(exc_info.value.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == (
            "dirty before failure\n"
        )

    def test_snapshot_failure_stops_before_abort_or_reset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        tracked = checkout / "README.md"
        before_head = _head(checkout)
        original_abort = reset_replay._abort_in_progress_operations
        aborted = False

        def _abort_spy(repo_root: Path) -> None:
            nonlocal aborted
            aborted = True
            original_abort(repo_root)

        def _fail_snapshot(*_args: object, **_kwargs: object) -> None:
            raise PreservationError("injected incomplete capture")

        monkeypatch.setattr(reset_replay, "snapshot_git_repo", _fail_snapshot)
        monkeypatch.setattr(reset_replay, "_abort_in_progress_operations", _abort_spy)

        def _operation() -> str:
            tracked.write_text("must remain\n", encoding="utf-8")
            raise ReplayConflict("needs reset")

        with pytest.raises(ResetReplayError, match="injected incomplete capture"):
            reset_and_replay(context, checkout, _operation, max_attempts=2)

        assert aborted is False
        assert _head(checkout) == before_head
        assert tracked.read_text(encoding="utf-8") == "must remain\n"

    def test_later_snapshot_failure_retains_earlier_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        context = _context(checkout, tmp_path / "proj")
        real_snapshot = reset_replay.snapshot_git_repo
        snapshot_calls = 0

        def _fail_second_snapshot(*args: object, **kwargs: object) -> object:
            nonlocal snapshot_calls
            snapshot_calls += 1
            if snapshot_calls == 2:
                raise PreservationError("second capture failed")
            return real_snapshot(*args, **kwargs)

        monkeypatch.setattr(reset_replay, "snapshot_git_repo", _fail_second_snapshot)
        operation_calls = 0

        def _operation() -> str:
            nonlocal operation_calls
            operation_calls += 1
            (checkout / "README.md").write_text(
                f"attempt {operation_calls}\n", encoding="utf-8"
            )
            raise ReplayConflict("repeat conflict")

        with pytest.raises(ResetReplayError, match="second capture failed") as exc_info:
            reset_and_replay(context, checkout, _operation, max_attempts=3)

        assert snapshot_calls == 2
        assert len(exc_info.value.recovery_locations) == 1
        restored = tmp_path / "restored-prior-snapshot"
        _clone(origin, restored)
        restore_git_snapshot(exc_info.value.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == "attempt 1\n"
        assert (checkout / "README.md").read_text(encoding="utf-8") == "attempt 2\n"

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


class TestResetLeasedCheckoutToUpstream:
    def test_direct_reset_returns_snapshot_and_keeps_legacy_head_ref_api(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        (checkout / "README.md").write_text("local recovery bytes\n", encoding="utf-8")
        context = _context(checkout, tmp_path / "proj")

        outcome = reset_leased_checkout_to_upstream_with_recovery(context, checkout)

        assert isinstance(outcome, ResetRecoveryOutcome)
        assert outcome.recovery_ref is not None
        assert len(outcome.recovery_locations) == 1
        restored = tmp_path / "restored-direct-reset"
        _clone(origin, restored)
        restore_git_snapshot(outcome.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == (
            "local recovery bytes\n"
        )

        legacy_ref = reset_leased_checkout_to_upstream(context, checkout)
        assert isinstance(legacy_ref, str)

    def test_resets_nested_store_without_touching_checkout(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        checkout_head = _head(checkout)
        nested_origin = tmp_path / "plans-origin"
        nested = checkout / "sase" / "repos" / "plans"
        nested.parent.mkdir(parents=True)
        _init_origin(nested_origin)
        _clone(nested_origin, nested)
        _advance_origin(nested_origin, "origin v2\n")
        (nested / "README.md").write_text("local nested\n", encoding="utf-8")
        _run(["commit", "-aq", "-m", "local nested"], nested)
        local_nested = _head(nested)
        context = _context(checkout, tmp_path / "proj")

        ref = reset_leased_checkout_to_upstream(context, nested)

        assert ref is not None
        assert _head(nested) == _head(nested_origin)
        assert _head(checkout) == checkout_head
        assert (
            subprocess.run(
                ["git", "cat-file", "-e", ref],
                cwd=nested,
                check=False,
            ).returncode
            == 0
        )
        assert (
            subprocess.run(
                ["git", "rev-parse", ref],
                cwd=nested,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            == local_nested
        )

    def test_resets_through_a_stale_index_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0")
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        _advance_origin(origin, "origin v2\n")
        lock = _plant_index_lock(checkout, age_seconds=3600)
        context = _context(checkout, tmp_path / "proj")

        reset_leased_checkout_to_upstream(context, checkout)

        assert _head(checkout) == _head(origin)
        assert not lock.exists()

    def test_does_not_remove_a_fresh_index_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0")
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        lock = _plant_index_lock(checkout, age_seconds=0)
        context = _context(checkout, tmp_path / "proj")

        with pytest.raises(ResetReplayError, match="index.lock"):
            reset_leased_checkout_to_upstream(context, checkout)

        assert lock.exists()


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

    def test_lease_reset_to_upstream_resets_nested_repo(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        _init_origin(origin)
        _clone(origin, checkout)
        checkout_head = _head(checkout)
        nested_origin = tmp_path / "plans-origin"
        nested = checkout / "sase" / "repos" / "plans"
        nested.parent.mkdir(parents=True)
        _init_origin(nested_origin)
        _clone(nested_origin, nested)
        _advance_origin(nested_origin, "origin v2\n")
        (nested / "README.md").write_text("local nested\n", encoding="utf-8")
        _run(["commit", "-aq", "-m", "local nested"], nested)
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

        ref = lease.reset_to_upstream(repo_root=nested)

        assert ref is not None
        assert _head(nested) == _head(nested_origin)
        assert _head(checkout) == checkout_head
