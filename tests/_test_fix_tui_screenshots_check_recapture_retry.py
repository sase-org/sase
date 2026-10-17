"""Retry, budget, and recovery check-mode tests."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from pathlib import Path

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    AttemptScript,
    git_index,
    make_png,
    silent_hooks,
)
from tests._fix_tui_screenshots_check_recapture_helpers import pair, read_manifest
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    MaintenanceHooks,
    main,
)
from tests.ace.tui.visual._visual_maintenance_cli import RECAPTURE_BUDGET_ENV


def test_check_budget_exhaustion_keeps_first_pass_and_writes_manifest(
    tmp_path: Path,
) -> None:
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(
            ["--check", "--recapture-budget-seconds", "0"],
            repo_root=tmp_path,
            hooks=silent_hooks(runner),
            environ={},
        )
        == EXIT_DRIFT
    )
    assert ace.read_bytes() == red
    assert len(runner.calls) == 1
    assert all("-verify" not in str(call["run_id"]) for call in runner.calls)
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "drift"
    assert manifest["exit_code"] == EXIT_DRIFT
    assert manifest["recapture_budget_seconds"] == 0
    assert any("budget exhausted" in str(warning) for warning in manifest["warnings"])
    assert (tmp_path / ".pytest_cache/sase-visual/runs").is_dir()
    assert read_manifest(tmp_path)["status"] == "drift"


def test_check_budget_env_zero_skips_recapture(tmp_path: Path) -> None:
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    assert (
        main(
            ["--check"],
            repo_root=tmp_path,
            hooks=silent_hooks(runner),
            environ={RECAPTURE_BUDGET_ENV: "0"},
        )
        == EXIT_DRIFT
    )
    assert ace.read_bytes() == red
    assert len(runner.calls) == 1


def test_check_internal_error_recovery_still_fails(tmp_path: Path) -> None:
    """A first-pass internal error is not cured by an exact-match retry."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    index = git_index(tmp_path)
    runner.attempts = [AttemptScript(exit_code=3, session_exitstatus=3)]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any("child_exit_code:3" in str(error) for error in manifest["errors"])
    assert any("session_exitstatus:3" in str(error) for error in manifest["errors"])


def test_check_exit_disagreement_recovery_still_fails(tmp_path: Path) -> None:
    """Child exit 3 with a clean session record stays a failure after retry."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    index = git_index(tmp_path)
    runner.attempts = [AttemptScript(exit_code=3, session_exitstatus=0)]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert any("exit_disagreement" in str(error) for error in manifest["errors"])


def test_check_targeted_recapture_ignores_missing_root(tmp_path: Path) -> None:
    """A targeted run that recaptures its drift is clean without both roots."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    index = git_index(tmp_path)
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(
            ["--check", "--", ACE_NODE],
            repo_root=tmp_path,
            hooks=silent_hooks(runner),
            environ={},
        )
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "clean"
    assert manifest["complete"] is True
    assert not any(
        "visual_root_unexecuted" in str(error) for error in manifest["errors"]
    )


def test_check_ordinary_failure_recovery_stays_clean(tmp_path: Path) -> None:
    """An ordinary test failure cured by an exact-match retry is clean."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    index = git_index(tmp_path)
    runner.attempts = [AttemptScript(exit_code=1, failed=(ACE_NODE,))]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "clean"
    unstable = manifest["unstable"]
    assert len(unstable) == 1
    assert unstable[0]["node_id"] == ACE_NODE


def test_check_broken_retry_cannot_cure_first_pass(tmp_path: Path) -> None:
    """A matching image from an abnormal-exit retry does not recover the node."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    index = git_index(tmp_path)
    runner.verify_attempts = [
        AttemptScript(exit_code=3, pngs={ACE_NODE: red}),
        AttemptScript(exit_code=0, pngs={ACE_NODE: red}),
    ]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    # The later valid retry still recovers the node, but the broken first
    # retry itself fails the run.
    assert len(manifest["unstable"]) == 1
    assert manifest["unstable"][0]["node_id"] == ACE_NODE
    assert any("retry verify" in str(error) for error in manifest["errors"])


def test_check_only_broken_retry_leaves_node_unrecovered(
    tmp_path: Path,
) -> None:
    """One broken matching retry with no later cure fails unrecovered."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.verify_attempts = [AttemptScript(exit_code=3, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["unstable"] == []
    assert any("retry verify" in str(error) for error in manifest["errors"])


def test_check_protocol_broken_retry_cannot_cure_first_pass(
    tmp_path: Path,
) -> None:
    """A matching image from an incomplete retry does not recover the node."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.verify_attempts = [
        AttemptScript(exit_code=0, pngs={ACE_NODE: red}, incomplete=True),
        AttemptScript(exit_code=0, pngs={ACE_NODE: red}),
    ]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert len(manifest["unstable"]) == 1
    assert manifest["unstable"][0]["node_id"] == ACE_NODE
    assert any("incomplete_worker" in str(error) for error in manifest["errors"])


class _FakeClock:
    """Monotonic clock replaying scripted times, then holding the last."""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self._last = self._values[-1] if self._values else 0.0

    def __call__(self) -> float:
        if self._values:
            self._last = self._values.pop(0)
        return self._last


def test_check_budget_expires_between_retries_keeps_first_pass(
    tmp_path: Path,
) -> None:
    """Exhaustion before the second retry keeps drift and carries the budget."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.verify_attempts = [
        AttemptScript(exit_code=0, pngs={ACE_NODE: make_png(1, 1, (0, 255, 0, 255))}),
    ]
    clock = _FakeClock([1000.0, 1000.0, 1000.0, 3000.0])
    hooks = dataclasses.replace(silent_hooks(runner), monotonic=clock)
    assert (
        main(
            ["--check", "--recapture-budget-seconds", "600"],
            repo_root=tmp_path,
            hooks=hooks,
            environ={},
        )
        == EXIT_DRIFT
    )
    assert ace.read_bytes() == red
    assert len(runner.calls) == 2
    assert runner.calls[0]["timeout_seconds"] is None
    assert runner.calls[1]["timeout_seconds"] == 600.0
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "drift"
    assert any("budget exhausted" in str(warning) for warning in manifest["warnings"])


def test_check_timed_out_retry_keeps_first_pass_and_writes_manifest(
    tmp_path: Path,
) -> None:
    """A retry stopped at the deadline keeps drift with a readable manifest."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    seen_timeouts: list[float | None] = []

    def stop_at_deadline(
        *,
        repo_root: Path,
        capture_dir: Path,
        run_id: str,
        scope: str,
        pytest_args: Sequence[str],
        log_path: Path,
        ace_root: Path,
        pager_root: Path,
        workers: int | None = None,
        timeout_seconds: float | None = None,
    ) -> int:
        seen_timeouts.append(timeout_seconds)
        log_path.write_text("fake hung visual pytest\n", encoding="utf-8")
        return 124

    def first_then_stop(
        *,
        repo_root: Path,
        capture_dir: Path,
        run_id: str,
        scope: str,
        pytest_args: Sequence[str],
        log_path: Path,
        ace_root: Path,
        pager_root: Path,
        workers: int | None = None,
        timeout_seconds: float | None = None,
    ) -> int:
        if "-verify" in run_id:
            return stop_at_deadline(
                repo_root=repo_root,
                capture_dir=capture_dir,
                run_id=run_id,
                scope=scope,
                pytest_args=pytest_args,
                log_path=log_path,
                ace_root=ace_root,
                pager_root=pager_root,
                workers=workers,
                timeout_seconds=timeout_seconds,
            )
        return runner(
            repo_root=repo_root,
            capture_dir=capture_dir,
            run_id=run_id,
            scope=scope,
            pytest_args=pytest_args,
            log_path=log_path,
            ace_root=ace_root,
            pager_root=pager_root,
            workers=workers,
            timeout_seconds=timeout_seconds,
        )

    hooks = MaintenanceHooks(
        preflight=lambda _update: None,
        run_pytest=first_then_stop,
        is_ci=lambda _env: False,
        renderer_identity=lambda: {"packages": {}, "fonts": {}},
        monotonic=_FakeClock([0.0, 0.0, 0.0, 1000.0, 1000.0]),
    )
    first_calls = runner.calls
    assert (
        main(
            ["--check", "--recapture-budget-seconds", "600"],
            repo_root=tmp_path,
            hooks=hooks,
            environ={},
        )
        == EXIT_DRIFT
    )
    assert ace.read_bytes() == red
    assert seen_timeouts == [600.0]
    assert len(first_calls) == 1
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "drift"
    assert any("budget exhausted" in str(warning) for warning in manifest["warnings"])
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "verify"]
    verify = next(
        attempt for attempt in manifest["attempts"] if attempt["label"] == "verify"
    )
    assert verify["child_exit_code"] == 124


def test_check_timed_out_retry_preserves_unrecovered_first_pass_failure(
    tmp_path: Path,
) -> None:
    """A timed-out retry keeps a first-pass failure in the manifest and exit."""
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (255, 0, 0, 255)))
    runner.attempts = [AttemptScript(exit_code=1, failed=(ACE_NODE,))]
    index = git_index(tmp_path)
    seen_timeouts: list[float | None] = []

    def first_then_stop(
        *,
        repo_root: Path,
        capture_dir: Path,
        run_id: str,
        scope: str,
        pytest_args: Sequence[str],
        log_path: Path,
        ace_root: Path,
        pager_root: Path,
        workers: int | None = None,
        timeout_seconds: float | None = None,
    ) -> int:
        if "-verify" in run_id:
            seen_timeouts.append(timeout_seconds)
            log_path.write_text("fake hung visual pytest\n", encoding="utf-8")
            return 124
        return runner(
            repo_root=repo_root,
            capture_dir=capture_dir,
            run_id=run_id,
            scope=scope,
            pytest_args=pytest_args,
            log_path=log_path,
            ace_root=ace_root,
            pager_root=pager_root,
            workers=workers,
            timeout_seconds=timeout_seconds,
        )

    hooks = MaintenanceHooks(
        preflight=lambda _update: None,
        run_pytest=first_then_stop,
        is_ci=lambda _env: False,
        renderer_identity=lambda: {"packages": {}, "fonts": {}},
        monotonic=_FakeClock([0.0, 0.0, 0.0, 1000.0, 1000.0]),
    )
    assert (
        main(
            ["--check", "--recapture-budget-seconds", "600"],
            repo_root=tmp_path,
            hooks=hooks,
            environ={},
        )
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    assert seen_timeouts == [600.0]
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any("budget exhausted" in str(warning) for warning in manifest["warnings"])
    assert any(ACE_NODE in str(error) for error in manifest["errors"])
    assert manifest["unstable"] == []
    verify = next(
        attempt for attempt in manifest["attempts"] if attempt["label"] == "verify"
    )
    assert verify["child_exit_code"] == 124
