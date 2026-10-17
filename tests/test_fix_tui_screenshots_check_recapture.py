"""Check-mode serial recapture tests for screenshot maintenance."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Sequence
from pathlib import Path

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    AttemptScript,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    git_index,
    init_repo,
    make_png,
    silent_hooks,
    write_golden,
)
from tests.ace.tui.visual._visual_capture import InventoryReport
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    MaintenanceHooks,
    main,
)
from tests.ace.tui.visual._visual_maintenance_cli import RECAPTURE_BUDGET_ENV
from tests.ace.tui.visual._visual_maintenance_verify import (
    CHECK_RECAPTURE_NODE_LIMIT,
    FIRST_ATTEMPT_DIFFS_DIRNAME,
    check_mode_strict_errors,
)

SKIP_NODE = "tests/ace/tui/visual/test_c.py::test_c"
UNINVENTORIED_NODE = "tests/ace/tui/visual/test_d.py::test_d"


def _manifest(repo: Path) -> dict[object, object]:
    paths = sorted(
        (repo / ".pytest_cache/sase-visual/runs").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    assert paths
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def _run_dir(repo: Path) -> Path:
    paths = sorted(
        (repo / ".pytest_cache/sase-visual/runs").glob("*"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    assert paths
    return paths[-1]


def _pair(repo: Path, *, candidate: bytes) -> tuple[bytes, Path, FakeRunner]:
    init_repo(repo)
    red = make_png(1, 1, (255, 0, 0, 255))
    ace = write_golden(repo, "ace", "shot.png", red)
    write_golden(repo, "pager", "shot.png", red)
    commit_all(repo)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", candidate),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=repo,
    )
    return red, ace, runner


def test_check_first_pass_match_does_not_recapture(tmp_path: Path) -> None:
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (255, 0, 0, 255)))
    mtime = ace.stat().st_mtime_ns
    index = git_index(tmp_path)
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == red
    assert ace.stat().st_mtime_ns == mtime
    assert git_index(tmp_path) == index
    assert len(runner.calls) == 1
    assert "-verify" not in str(runner.calls[0]["run_id"])
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "clean"
    assert manifest["unstable"] == []
    assert manifest["exit_code"] == EXIT_SUCCESS


def test_check_retry_match_is_unstable_and_does_not_write(
    tmp_path: Path,
) -> None:
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    mtime = ace.stat().st_mtime_ns
    index = git_index(tmp_path)
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == red
    assert ace.stat().st_mtime_ns == mtime
    assert git_index(tmp_path) == index
    assert len(runner.calls) == 2
    verify = runner.calls[1]
    assert "-verify" in str(verify["run_id"])
    assert verify["workers"] == 1
    assert verify["scope"] == "targeted"
    assert ACE_NODE in verify["pytest_args"]
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "clean"
    assert manifest["exit_code"] == EXIT_SUCCESS
    unstable = manifest["unstable"]
    assert len(unstable) == 1
    assert unstable[0]["node_id"] == ACE_NODE
    assert unstable[0]["reason"] == "unstable"
    assert unstable[0]["attempts"] == 2
    diffs = _run_dir(tmp_path) / FIRST_ATTEMPT_DIFFS_DIRNAME
    assert diffs.is_dir()
    node_dirs = list(diffs.iterdir())
    assert node_dirs
    assert (node_dirs[0] / "expected.png").is_file()
    assert (node_dirs[0] / "actual.png").is_file()
    assert (node_dirs[0] / "diff.png").is_file()
    assert manifest["first_attempt_diffs_dir"]
    assert not list(_run_dir(tmp_path).glob("recover-*"))
    assert not (_run_dir(tmp_path) / "capture-retry").exists()


def test_check_fails_every_attempt_exits_drift(tmp_path: Path) -> None:
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.verify_attempts = [
        AttemptScript(exit_code=0, pngs={ACE_NODE: make_png(1, 1, (0, 255, 0, 255))}),
        AttemptScript(exit_code=0, pngs={ACE_NODE: make_png(1, 1, (0, 255, 255, 255))}),
    ]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_DRIFT
    )
    assert ace.read_bytes() == red
    assert len(runner.calls) == 3
    assert all(call["workers"] == 1 for call in runner.calls[1:])
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "drift"
    assert manifest["exit_code"] == EXIT_DRIFT
    assert manifest["unstable"] == []
    assert any(item["kind"] == "updated" for item in manifest["changes"])
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "verify", "verify-2"]


def test_check_over_cap_skips_recapture_on_systemic_drift(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    nodes = [
        f"tests/ace/tui/visual/test_a.py::test_{index}"
        for index in range(CHECK_RECAPTURE_NODE_LIMIT + 1)
    ]
    runner = FakeRunner(
        captures=[
            *[
                ScriptedCapture(node_id, f"n{index}", "ace", blue)
                for index, node_id in enumerate(nodes)
            ],
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=tmp_path,
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_DRIFT
    )
    assert len(runner.calls) == 1
    assert "-verify" not in str(runner.calls[0]["run_id"])
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "drift"
    assert any("exceed the" in warning for warning in manifest["warnings"])
    assert manifest["unstable"] == []


def test_check_over_cap_pytest_failures_exit_failure(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
    write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    nodes = [
        f"tests/ace/tui/visual/test_a.py::test_{index}"
        for index in range(CHECK_RECAPTURE_NODE_LIMIT + 1)
    ]
    runner = FakeRunner(
        captures=[
            *[
                ScriptedCapture(node_id, f"n{index}", "ace", red)
                for index, node_id in enumerate(nodes)
            ],
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
        attempts=[AttemptScript(exit_code=1, failed=tuple(nodes))],
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert len(runner.calls) == 1
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any("exceed the" in error for error in manifest["errors"])


def test_check_persistent_test_failure_exits_failure(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    red, ace, runner = _pair(tmp_path, candidate=red)
    runner.attempts = [AttemptScript(exit_code=1, failed=(ACE_NODE,))]
    runner.verify_attempts = [
        AttemptScript(exit_code=1, failed=(ACE_NODE,)),
        AttemptScript(exit_code=1, failed=(ACE_NODE,)),
    ]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    assert len(runner.calls) == 3
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any(ACE_NODE in str(error) for error in manifest["errors"])
    assert manifest["counts"]["updated"] == 0
    assert manifest["counts"]["created"] == 0
    assert manifest["unstable"] == []


def test_check_recovered_node_does_not_hide_skipped_node(tmp_path: Path) -> None:
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.attempts = [
        AttemptScript(exit_code=1, failed=(ACE_NODE,), skipped=(SKIP_NODE,))
    ]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any("skipped_node:" in str(error) for error in manifest["errors"])
    unstable = manifest["unstable"]
    assert len(unstable) == 1
    assert unstable[0]["node_id"] == ACE_NODE


def test_check_recovered_node_does_not_hide_uninventoried_node(
    tmp_path: Path,
) -> None:
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.attempts = [
        AttemptScript(exit_code=1, failed=(ACE_NODE,), unexecuted=(UNINVENTORIED_NODE,))
    ]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any(
        UNINVENTORIED_NODE in str(error) or "unaccounted_node:" in str(error)
        for error in manifest["errors"]
    )


def test_check_budget_exhaustion_keeps_first_pass_and_writes_manifest(
    tmp_path: Path,
) -> None:
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
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
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "drift"
    assert manifest["exit_code"] == EXIT_DRIFT
    assert manifest["recapture_budget_seconds"] == 0
    assert any("budget exhausted" in str(warning) for warning in manifest["warnings"])
    assert (tmp_path / ".pytest_cache/sase-visual/runs").is_dir()
    assert _manifest(tmp_path)["status"] == "drift"


def test_check_budget_env_zero_skips_recapture(tmp_path: Path) -> None:
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
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
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    index = git_index(tmp_path)
    runner.attempts = [AttemptScript(exit_code=3, session_exitstatus=3)]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any("child_exit_code:3" in str(error) for error in manifest["errors"])
    assert any("session_exitstatus:3" in str(error) for error in manifest["errors"])


def test_check_exit_disagreement_recovery_still_fails(tmp_path: Path) -> None:
    """Child exit 3 with a clean session record stays a failure after retry."""
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    index = git_index(tmp_path)
    runner.attempts = [AttemptScript(exit_code=3, session_exitstatus=0)]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert any("exit_disagreement" in str(error) for error in manifest["errors"])


def test_check_targeted_recapture_ignores_missing_root(tmp_path: Path) -> None:
    """A targeted run that recaptures its drift is clean without both roots."""
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
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
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "clean"
    assert manifest["complete"] is True
    assert not any(
        "visual_root_unexecuted" in str(error) for error in manifest["errors"]
    )


def test_check_ordinary_failure_recovery_stays_clean(tmp_path: Path) -> None:
    """An ordinary test failure cured by an exact-match retry is clean."""
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    index = git_index(tmp_path)
    runner.attempts = [AttemptScript(exit_code=1, failed=(ACE_NODE,))]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == red
    assert git_index(tmp_path) == index
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "clean"
    unstable = manifest["unstable"]
    assert len(unstable) == 1
    assert unstable[0]["node_id"] == ACE_NODE


def test_check_broken_retry_cannot_cure_first_pass(tmp_path: Path) -> None:
    """A matching image from an abnormal-exit retry does not recover the node."""
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
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
    manifest = _manifest(tmp_path)
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
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.verify_attempts = [AttemptScript(exit_code=3, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["unstable"] == []
    assert any("retry verify" in str(error) for error in manifest["errors"])


def test_check_protocol_broken_retry_cannot_cure_first_pass(
    tmp_path: Path,
) -> None:
    """A matching image from an incomplete retry does not recover the node."""
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.verify_attempts = [
        AttemptScript(exit_code=0, pngs={ACE_NODE: red}, incomplete=True),
        AttemptScript(exit_code=0, pngs={ACE_NODE: red}),
    ]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    manifest = _manifest(tmp_path)
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
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
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
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "drift"
    assert any("budget exhausted" in str(warning) for warning in manifest["warnings"])


def test_check_timed_out_retry_keeps_first_pass_and_writes_manifest(
    tmp_path: Path,
) -> None:
    """A retry stopped at the deadline keeps drift with a readable manifest."""
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
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
    manifest = _manifest(tmp_path)
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
    red, ace, runner = _pair(tmp_path, candidate=make_png(1, 1, (255, 0, 0, 255)))
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
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any("budget exhausted" in str(warning) for warning in manifest["warnings"])
    assert any(ACE_NODE in str(error) for error in manifest["errors"])
    assert manifest["unstable"] == []
    verify = next(
        attempt for attempt in manifest["attempts"] if attempt["label"] == "verify"
    )
    assert verify["child_exit_code"] == 124


def _strict_inventory(
    *,
    reasons: tuple[str, ...] = (),
    errors: tuple[str, ...] = (),
    session_exitstatus: int = 0,
    scope: str = "full",
) -> InventoryReport:
    """Build the strict-policy inputs without running the visual suite."""
    return InventoryReport(
        run_id="strict-test",
        requested_scope=scope,
        full_inventory=False,
        pruning_allowed=False,
        complete=False,
        session_exitstatus=session_exitstatus,
        collectonly=False,
        reasons=reasons,
        errors=errors,
        workers_expected=("controller",),
        workers_seen=("controller",),
        lost_workers=(),
        captures=(),
        worker_sessions=(),
        collected_visual_node_ids=(),
        executed_visual_node_ids=(),
        skipped_visual_node_ids=(),
        xfailed_visual_node_ids=(),
        failed_visual_node_ids=(),
        deselected_visual_node_ids=(),
        roots_executed=(),
    )


def test_strict_ignores_cured_failure_and_ordinary_session_status() -> None:
    inventory = _strict_inventory(
        reasons=("failed_node:X", "session_exitstatus:1", "requested_scope_targeted"),
        scope="targeted",
    )
    assert check_mode_strict_errors(inventory, recovered=["X"]) == ()


def test_strict_keeps_uncured_failed_node() -> None:
    inventory = _strict_inventory(
        reasons=("failed_node:X", "session_exitstatus:1"),
    )
    errors = check_mode_strict_errors(inventory, recovered=[])
    assert any("failed_node:X" in error for error in errors)
    assert not any("session_exitstatus:1" in error for error in errors)


def test_strict_flags_internal_error_and_child_exit() -> None:
    inventory = _strict_inventory(
        reasons=("session_exitstatus:3",), session_exitstatus=3
    )
    errors = check_mode_strict_errors(inventory, recovered=["X"], child_exit_code=3)
    assert any("session_exitstatus:3" in error for error in errors)
    assert any("child_exit_code:3" in error for error in errors)


def test_strict_flags_exit_disagreement() -> None:
    inventory = _strict_inventory(reasons=(), session_exitstatus=0)
    errors = check_mode_strict_errors(inventory, recovered=[], child_exit_code=3)
    assert any("exit_disagreement" in error for error in errors)


def test_strict_targeted_scope_ignores_missing_root() -> None:
    inventory = _strict_inventory(reasons=("visual_root_unexecuted:pager",))
    assert check_mode_strict_errors(inventory, recovered=[], scope="targeted") == ()
    assert check_mode_strict_errors(inventory, recovered=[], scope="full") != ()


def test_strict_flags_collection_mismatch_and_unexpected_worker() -> None:
    inventory = _strict_inventory(
        reasons=("collection_mismatch", "unexpected_worker:controller-1"),
    )
    errors = check_mode_strict_errors(inventory, recovered=["X"])
    assert any("collection_mismatch" in error for error in errors)
    assert any("unexpected_worker" in error for error in errors)


def test_strict_flags_skipped_nodes_and_protocol_errors() -> None:
    inventory = _strict_inventory(
        reasons=("skipped_node:S",),
        errors=("worker_error:controller:boom",),
    )
    errors = check_mode_strict_errors(inventory, recovered=["S"])
    assert any("skipped_node:S" in error for error in errors)
    assert any("worker_error" in error for error in errors)
