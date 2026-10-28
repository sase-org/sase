"""Retry exhaustion and non-conflict failure coverage for reset-and-replay."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import sase.workspace_provider.reset_replay as reset_replay
from sase.workspace_provider.reset_replay import (
    ReplayConflict,
    ReplayDeferred,
    ResetReplayError,
    reset_and_replay,
)
from sase.workspace_provider.snapshot import PreservationError, restore_git_snapshot
from tests.workspace_provider._reset_replay_helpers import (
    clone_repo,
    init_origin,
    operation_context,
    redirect_rescue_state,  # noqa: F401 (registers the autouse fixture)
    repo_head,
)

__all__ = [
    "TestRetryExhaustionAndOtherFailures",
    "redirect_rescue_state",
]


class TestRetryExhaustionAndOtherFailures:
    def test_retry_exhaustion_keeps_recovery_locations_from_prior_reset(
        self, tmp_path: Path
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
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
        clone_repo(origin, restored)
        restore_git_snapshot(exc_info.value.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == "attempt 1\n"
        assert n == 2

    def test_each_retry_snapshot_is_retained(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
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
            clone_repo(origin, restored)
            restore_git_snapshot(location, restored)
            assert (restored / "README.md").read_text(encoding="utf-8") == (
                f"attempt {number}\n"
            )

    def test_fetch_failure_after_snapshot_names_recovery_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
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
        clone_repo(origin, restored)
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
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
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
        clone_repo(origin, restored)
        restore_git_snapshot(exc_info.value.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == (
            "dirty before failure\n"
        )

    def test_snapshot_failure_stops_before_abort_or_reset(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
        tracked = checkout / "README.md"
        before_head = repo_head(checkout)
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
        assert repo_head(checkout) == before_head
        assert tracked.read_text(encoding="utf-8") == "must remain\n"

    def test_later_snapshot_failure_retains_earlier_location(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
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
        clone_repo(origin, restored)
        restore_git_snapshot(exc_info.value.recovery_locations[0], restored)
        assert (restored / "README.md").read_text(encoding="utf-8") == "attempt 1\n"
        assert (checkout / "README.md").read_text(encoding="utf-8") == "attempt 2\n"

    def test_remote_unavailable_defers_without_git_calls(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        origin = tmp_path / "origin"
        checkout = tmp_path / "proj_10"
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")

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
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
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
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
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
        init_origin(origin)
        clone_repo(origin, checkout)
        context = operation_context(checkout, tmp_path / "proj")
        with pytest.raises(ValueError, match="max_attempts"):
            reset_and_replay(context, checkout, lambda: "ok", max_attempts=0)
