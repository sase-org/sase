"""General check-mode recapture behavior tests."""

from __future__ import annotations

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
from tests._fix_tui_screenshots_check_recapture_helpers import pair, read_manifest
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    main,
)
from tests.ace.tui.visual._visual_maintenance_verify import (
    CHECK_RECAPTURE_NODE_LIMIT,
    FIRST_ATTEMPT_DIFFS_DIRNAME,
)

SKIP_NODE = "tests/ace/tui/visual/test_c.py::test_c"
UNINVENTORIED_NODE = "tests/ace/tui/visual/test_d.py::test_d"


def _run_dir(repo: Path) -> Path:
    paths = sorted(
        (repo / ".pytest_cache/sase-visual/runs").glob("*"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    assert paths
    return paths[-1]


def test_check_first_pass_match_does_not_recapture(tmp_path: Path) -> None:
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (255, 0, 0, 255)))
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
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "clean"
    assert manifest["unstable"] == []
    assert manifest["exit_code"] == EXIT_SUCCESS


def test_check_retry_match_is_unstable_and_does_not_write(
    tmp_path: Path,
) -> None:
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
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
    manifest = read_manifest(tmp_path)
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
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
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
    manifest = read_manifest(tmp_path)
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
    manifest = read_manifest(tmp_path)
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
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any("exceed the" in error for error in manifest["errors"])


def test_check_persistent_test_failure_exits_failure(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    red, ace, runner = pair(tmp_path, candidate=red)
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
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any(ACE_NODE in str(error) for error in manifest["errors"])
    assert manifest["counts"]["updated"] == 0
    assert manifest["counts"]["created"] == 0
    assert manifest["unstable"] == []


def test_check_recovered_node_does_not_hide_skipped_node(tmp_path: Path) -> None:
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.attempts = [
        AttemptScript(exit_code=1, failed=(ACE_NODE,), skipped=(SKIP_NODE,))
    ]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any("skipped_node:" in str(error) for error in manifest["errors"])
    unstable = manifest["unstable"]
    assert len(unstable) == 1
    assert unstable[0]["node_id"] == ACE_NODE


def test_check_recovered_node_does_not_hide_uninventoried_node(
    tmp_path: Path,
) -> None:
    red, ace, runner = pair(tmp_path, candidate=make_png(1, 1, (0, 0, 255, 255)))
    runner.attempts = [
        AttemptScript(exit_code=1, failed=(ACE_NODE,), unexecuted=(UNINVENTORIED_NODE,))
    ]
    runner.verify_attempts = [AttemptScript(exit_code=0, pngs={ACE_NODE: red})]
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    manifest = read_manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert manifest["exit_code"] == EXIT_FAILURE
    assert any(
        UNINVENTORIED_NODE in str(error) or "unaccounted_node:" in str(error)
        for error in manifest["errors"]
    )
