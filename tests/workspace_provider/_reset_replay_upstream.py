"""Direct leased-checkout reset and OperationalLease wrapper coverage."""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from sase.workspace_provider.lease import OperationalLease
from sase.workspace_provider.reset_replay import (
    ReplayConflict,
    ResetRecoveryOutcome,
    ResetReplayError,
    reset_leased_checkout_to_upstream,
    reset_leased_checkout_to_upstream_with_recovery,
)
from sase.workspace_provider.snapshot import restore_git_snapshot
from tests.workspace_provider._reset_replay_helpers import (
    advance_origin,
    clone_repo,
    init_origin,
    operation_context,
    redirect_rescue_state,  # noqa: F401 (registers the autouse fixture)
    repo_head,
    run_git,
)

__all__ = [
    "TestOperationalLeaseResetAndReplay",
    "TestResetLeasedCheckoutToUpstream",
    "redirect_rescue_state",
]


def _plant_index_lock(repo: Path, *, age_seconds: float) -> Path:
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale\n", encoding="utf-8")
    stamped = time.time() - age_seconds
    os.utime(lock, (stamped, stamped))
    return lock


class TestResetLeasedCheckoutToUpstream:
    def test_direct_reset_returns_snapshot_and_keeps_legacy_head_ref_api(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        (checkout / "README.md").write_text("local recovery bytes\n", encoding="utf-8")
        context = operation_context(checkout, tmp_path / "proj")

        outcome = reset_leased_checkout_to_upstream_with_recovery(context, checkout)

        assert isinstance(outcome, ResetRecoveryOutcome)
        assert outcome.recovery_ref is not None
        assert len(outcome.recovery_locations) == 1
        restored = tmp_path / "restored-direct-reset"
        clone_repo(origin, restored)
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
        init_origin(origin)
        clone_repo(origin, checkout)
        checkout_head = repo_head(checkout)
        nested_origin = tmp_path / "plans-origin"
        nested = checkout / "sase" / "repos" / "plans"
        nested.parent.mkdir(parents=True)
        init_origin(nested_origin)
        clone_repo(nested_origin, nested)
        advance_origin(nested_origin, "origin v2\n")
        (nested / "README.md").write_text("local nested\n", encoding="utf-8")
        run_git(["commit", "-aq", "-m", "local nested"], nested)
        local_nested = repo_head(nested)
        context = operation_context(checkout, tmp_path / "proj")

        ref = reset_leased_checkout_to_upstream(context, nested)

        assert ref is not None
        assert repo_head(nested) == repo_head(nested_origin)
        assert repo_head(checkout) == checkout_head
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
        init_origin(origin)
        clone_repo(origin, checkout)
        advance_origin(origin, "origin v2\n")
        lock = _plant_index_lock(checkout, age_seconds=3600)
        context = operation_context(checkout, tmp_path / "proj")

        reset_leased_checkout_to_upstream(context, checkout)

        assert repo_head(checkout) == repo_head(origin)
        assert not lock.exists()

    def test_does_not_remove_a_fresh_index_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0")
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        lock = _plant_index_lock(checkout, age_seconds=0)
        context = operation_context(checkout, tmp_path / "proj")

        with pytest.raises(ResetReplayError, match="index.lock"):
            reset_leased_checkout_to_upstream(context, checkout)

        assert lock.exists()


class TestOperationalLeaseResetAndReplay:
    def test_lease_method_replays_on_conflict(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        advance_origin(origin, "origin v2\n")
        lease = OperationalLease(
            project="demo",
            workflow="chop:demo",
            holder="holder",
            workspace_num=10,
            checkout_dir=checkout,
            project_file=tmp_path / "demo.sase",
            claim_pid=os.getpid(),
            cl_name="holder",
            context=operation_context(checkout, tmp_path / "proj"),
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
        assert repo_head(checkout) == repo_head(origin)

    def test_lease_reset_to_upstream_resets_nested_repo(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        checkout_head = repo_head(checkout)
        nested_origin = tmp_path / "plans-origin"
        nested = checkout / "sase" / "repos" / "plans"
        nested.parent.mkdir(parents=True)
        init_origin(nested_origin)
        clone_repo(nested_origin, nested)
        advance_origin(nested_origin, "origin v2\n")
        (nested / "README.md").write_text("local nested\n", encoding="utf-8")
        run_git(["commit", "-aq", "-m", "local nested"], nested)
        lease = OperationalLease(
            project="demo",
            workflow="chop:demo",
            holder="holder",
            workspace_num=10,
            checkout_dir=checkout,
            project_file=tmp_path / "demo.sase",
            claim_pid=os.getpid(),
            cl_name="holder",
            context=operation_context(checkout, tmp_path / "proj"),
        )

        ref = lease.reset_to_upstream(repo_root=nested)

        assert ref is not None
        assert repo_head(nested) == repo_head(nested_origin)
        assert repo_head(checkout) == checkout_head
