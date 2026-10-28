"""Conflict-triggered reset-and-replay coverage."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import sase.workspace_provider.reset_replay as reset_replay
from sase.workspace_provider.ownership import WorkspaceOwnershipError
from sase.workspace_provider.reset_replay import (
    ReplayConflict,
    ResetReplayError,
    reset_and_replay,
)
from sase.workspace_provider.snapshot import PreservationError, restore_git_snapshot
from tests.workspace_provider._reset_replay_helpers import (
    advance_origin,
    clone_repo,
    init_origin,
    operation_context,
    redirect_rescue_state,  # noqa: F401 (registers the autouse fixture)
    repo_head,
    run_git,
    run_git_capture,
)

__all__ = [
    "TestConflictTriggersResetAndReplay",
    "redirect_rescue_state",
]


def _put_checkout_in_stale_rebase(checkout: Path, origin: Path) -> None:
    """Diverge *checkout* from *origin* and leave a conflicted, mid-rebase state."""

    advance_origin(origin, "origin v2\n")
    (checkout / "README.md").write_text("local v2\n", encoding="utf-8")
    run_git(["commit", "-aq", "-m", "local divergent change"], checkout)
    run_git(["fetch", "-q", "origin"], checkout)
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


class TestConflictTriggersResetAndReplay:
    def test_stale_rebase_is_reset_and_operation_is_replayed(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        _put_checkout_in_stale_rebase(checkout, origin)
        context = operation_context(checkout, tmp_path / "proj")
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
        assert repo_head(checkout) == repo_head(origin)
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
        init_origin(origin)
        (origin / "src").mkdir()
        (origin / "src" / "dispatch.py").write_bytes(b"dispatch base\n")
        run_git(["add", "src/dispatch.py"], origin)
        run_git(["commit", "-q", "-m", "add dispatch"], origin)
        checkout = tmp_path / "proj_10"
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
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
        clone_repo(origin, restored)
        restore_git_snapshot(manifest_path, restored)
        assert (restored / "src" / "dispatch.py").read_bytes() == tracked_bytes
        assert (restored / "src" / "new_impl.py").read_bytes() == untracked_bytes

        # Exercise the normal post-reset cleanup path after proving the external
        # snapshot can restore the bytes without the original checkout.
        run_git(
            ["stash", "push", "--include-untracked", "-m", "post-reset cleanup"],
            checkout,
        )
        assert "post-reset cleanup" in run_git_capture(["stash", "list"], checkout)

    def test_untracked_path_collision_with_upstream_is_snapshotted(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        init_origin(origin)
        checkout = tmp_path / "proj_10"
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
        collision = checkout / "collision.py"
        collision.write_bytes(b"local untracked\x00bytes")
        advance_origin(origin, "origin v2\n")
        (origin / "collision.py").write_bytes(b"upstream tracked bytes\n")
        run_git(["add", "collision.py"], origin)
        run_git(["commit", "-q", "-m", "upstream collision"], origin)

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
        clone_repo(origin, restored)
        restore_git_snapshot(result.recovery_locations[0], restored)
        assert (restored / "collision.py").read_bytes() == b"local untracked\x00bytes"
        assert "collision.py" not in run_git_capture(["ls-files"], restored)

    def test_delete_modify_conflict_bytes_recover_after_reset(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        init_origin(origin)
        (origin / "conflict.txt").write_text("base\n", encoding="utf-8")
        run_git(["add", "conflict.txt"], origin)
        run_git(["commit", "-q", "-m", "base conflict"], origin)
        checkout = tmp_path / "proj_10"
        clone_repo(origin, checkout)
        run_git(["checkout", "-b", "theirs"], checkout)
        (checkout / "conflict.txt").write_text("theirs\n", encoding="utf-8")
        run_git(["commit", "-aq", "-m", "theirs change"], checkout)
        run_git(["checkout", "-q", "main"], checkout)
        run_git(["rm", "--", "conflict.txt"], checkout)
        run_git(["commit", "-q", "-m", "delete on main"], checkout)
        merge = subprocess.run(
            ["git", "merge", "theirs"],
            cwd=checkout,
            capture_output=True,
            text=True,
        )
        assert merge.returncode != 0
        unique = b"unique manual conflict edits\n"
        (checkout / "conflict.txt").write_bytes(unique)
        src_stage = run_git_capture(
            ["ls-files", "--stage", "--", "conflict.txt"], checkout
        )
        assert " 1\tconflict.txt" in src_stage
        assert " 3\tconflict.txt" in src_stage
        context = operation_context(checkout, tmp_path / "proj")
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
        assert run_git_capture(["status", "--porcelain"], checkout).strip() == ""
        assert len(result.recovery_locations) == 1
        restored = tmp_path / "restored-du"
        restored.mkdir()
        restore_git_snapshot(result.recovery_locations[0], restored)
        assert (restored / "conflict.txt").read_bytes() == unique
        dest_stage = run_git_capture(
            ["ls-files", "--stage", "--", "conflict.txt"], restored
        )
        assert dest_stage == src_stage

    def test_semantic_push_race_conflict_resets_to_new_upstream_tip(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        advance_origin(origin, "origin v2\n")
        context = operation_context(checkout, tmp_path / "proj")
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
        assert repo_head(checkout) == repo_head(origin)

    def test_clear_paths_removes_lease_owned_state_on_reset(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        generated = checkout / ".sase" / "sdd" / "beads"
        generated.mkdir(parents=True)
        (generated / "stale.txt").write_text("stale\n", encoding="utf-8")
        context = operation_context(checkout, tmp_path / "proj")
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
        init_origin(origin)
        (origin / ".gitignore").write_text("sase/repos/\n", encoding="utf-8")
        run_git(["add", ".gitignore"], origin)
        run_git(["commit", "-q", "-m", "ignore nested repos"], origin)
        clone_repo(origin, checkout)
        nested_origin = tmp_path / "nested-origin"
        init_origin(nested_origin)
        nested = checkout / "sase" / "repos" / "linked" / "plugin"
        nested.parent.mkdir(parents=True)
        clone_repo(nested_origin, nested)
        (nested / "README.md").write_text("nested staged\n", encoding="utf-8")
        run_git(["add", "README.md"], nested)
        (nested / "README.md").write_text("nested working\n", encoding="utf-8")
        (nested / "untracked.txt").write_text("nested untracked\n", encoding="utf-8")
        nested_stage = run_git_capture(
            ["ls-files", "--stage", "--", "README.md"], nested
        )
        context = operation_context(checkout, tmp_path / "proj")
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
            run_git_capture(["ls-files", "--stage", "--", "README.md"], restored)
            == nested_stage
        )

    def test_clear_paths_refuse_when_nested_snapshot_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        (origin / ".gitignore").write_text("sase/repos/\n", encoding="utf-8")
        run_git(["add", ".gitignore"], origin)
        run_git(["commit", "-q", "-m", "ignore nested repos"], origin)
        clone_repo(origin, checkout)
        nested_origin = tmp_path / "nested-origin"
        init_origin(nested_origin)
        nested = checkout / "sase" / "repos" / "linked" / "plugin"
        nested.parent.mkdir(parents=True)
        clone_repo(nested_origin, nested)
        (nested / "README.md").write_text("must remain\n", encoding="utf-8")
        context = operation_context(checkout, tmp_path / "proj")

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
        init_origin(origin)
        clone_repo(origin, checkout)
        outside.mkdir()
        context = operation_context(checkout, tmp_path / "proj")

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
