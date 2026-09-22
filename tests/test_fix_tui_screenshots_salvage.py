"""Salvage, recovery, and partial-apply tests for screenshot maintenance."""

from __future__ import annotations

import json
from pathlib import Path

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    AttemptScript,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    init_repo,
    make_png,
    silent_hooks,
    write_golden,
)
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
    main,
)
from tests.ace.tui.visual._visual_maintenance_types import KIND_STALE


def _manifest(repo: Path) -> dict[object, object]:
    paths = sorted(
        (repo / ".pytest_cache/sase-visual/runs").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    assert paths
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def _failing(count: int = 3) -> list[AttemptScript]:
    """Return *count* passes where the ACE node fails."""
    return [AttemptScript(exit_code=1, failed=(ACE_NODE,)) for _ in range(count)]


def _salvage_setup(
    repo: Path,
    *,
    baseline: bytes,
    candidate: bytes,
    pager_name: str = "shot",
    orphan: bool = False,
    attempts: list[AttemptScript] | None = None,
    exit_code: int = 0,
    verify_png: bytes | None = None,
) -> tuple[Path, FakeRunner]:
    """Create ace-shot/pager goldens at *baseline* plus a FakeRunner."""
    init_repo(repo)
    target = write_golden(repo, "ace", "shot.png", baseline)
    write_golden(repo, "pager", f"{pager_name}.png", baseline)
    if orphan:
        write_golden(repo, "ace", "orphan.png", baseline)
    commit_all(repo)
    return target, FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", candidate),
            ScriptedCapture(PAGER_NODE, pager_name, "pager", baseline),
        ],
        repo_root=repo,
        attempts=attempts or [],
        exit_code=exit_code,
        verify_png=verify_png,
    )


def test_recovery_success_applies_second_attempt_candidates(
    tmp_path: Path,
) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    recovered_png = make_png(1, 1, (0, 255, 255, 255))
    target, runner = _salvage_setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        pager_name="keep",
        attempts=[
            AttemptScript(exit_code=1, failed=(ACE_NODE,)),
            AttemptScript(exit_code=0, pngs={ACE_NODE: recovered_png}),
        ],
        verify_png=recovered_png,
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == recovered_png
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["skipped"] == []
    assert manifest["pruning_skipped_reason"] is None
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert "capture" in labels
    assert "recover-1" in labels
    assert "recover-2" not in labels
    recover_calls = [
        call for call in runner.calls if str(call["run_id"]).endswith("recover-1")
    ]
    assert len(recover_calls) == 1
    assert recover_calls[0]["workers"] == 1
    assert recover_calls[0]["scope"] == "targeted"
    assert tuple(recover_calls[0]["pytest_args"]) == (ACE_NODE,)


def test_session_only_nonzero_exit_applies_with_warning(
    tmp_path: Path,
) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _salvage_setup(tmp_path, baseline=red, candidate=blue, exit_code=1)
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["child_exit_code"] == 1
    assert any("temp-leak guard" in warning for warning in manifest["warnings"])
    assert [attempt["label"] for attempt in manifest["attempts"]] == [
        "capture",
        "verify",
    ]


def test_lost_worker_nodes_are_recovered(tmp_path: Path) -> None:
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _salvage_setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        attempts=[
            AttemptScript(
                exit_code=1,
                incomplete=True,
                unexecuted=(ACE_NODE, PAGER_NODE),
            ),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["skipped"] == []
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "recover-1", "verify"]


def test_full_run_with_unrecovered_failure_skips_pruning(
    tmp_path: Path,
) -> None:
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _salvage_setup(
        tmp_path, baseline=red, candidate=blue, orphan=True, attempts=_failing()
    )
    orphan = tmp_path / "tests/ace/tui/visual/snapshots/png/orphan.png"
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == red
    assert orphan.exists()
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "partial"
    assert manifest["pruning_skipped_reason"]
    assert not any(item["kind"] == KIND_STALE for item in manifest["changes"])
    assert any(
        item["reason"] == "test_failed" and item["node_id"] == ACE_NODE
        for item in manifest["skipped"]
    )


def test_full_run_cured_by_recovery_still_prunes(tmp_path: Path) -> None:
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _salvage_setup(
        tmp_path,
        baseline=red,
        candidate=blue,
        orphan=True,
        attempts=[
            AttemptScript(exit_code=1, failed=(ACE_NODE,)),
            AttemptScript(exit_code=0),
        ],
    )
    orphan = tmp_path / "tests/ace/tui/visual/snapshots/png/orphan.png"
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    assert not orphan.exists()
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"
    assert manifest["pruning_skipped_reason"] is None
    assert any(item["kind"] == KIND_STALE for item in manifest["changes"])


def test_no_inventory_twice_is_fatal(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_golden(tmp_path, "ace", "keep.png", make_png(1, 1))
    write_golden(tmp_path, "pager", "keep.png", make_png(1, 1))
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[],
        repo_root=tmp_path,
        attempts=[
            AttemptScript(no_inventory=True, exit_code=1),
            AttemptScript(no_inventory=True, exit_code=1),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert "capture.log" in manifest["errors"][0]
    assert "capture-retry.log" in manifest["errors"][0]
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "capture-retry"]


def test_pytest_usage_error_is_usage(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_golden(tmp_path, "ace", "keep.png", make_png(1, 1))
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[],
        repo_root=tmp_path,
        attempts=[AttemptScript(no_inventory=True, exit_code=4)],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_USAGE
    )
    assert _manifest(tmp_path)["status"] == "refused"


def test_recovery_keeps_governed_workers_for_large_sets(
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    nodes = [
        f"tests/ace/tui/visual/test_many.py::test_{index:02d}" for index in range(26)
    ]
    for node_id in nodes:
        write_golden(tmp_path, "ace", f"shot-{node_id[-2:]}.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(node_id, f"shot-{node_id[-2:]}", "ace", blue)
            for node_id in nodes
        ],
        repo_root=tmp_path,
        attempts=[AttemptScript(exit_code=1, failed=tuple(nodes))],
    )
    assert (
        main(
            ["--", *nodes],
            repo_root=tmp_path,
            hooks=silent_hooks(runner),
            environ={},
        )
        == EXIT_SUCCESS
    )
    recover_calls = [
        call for call in runner.calls if str(call["run_id"]).endswith("recover-1")
    ]
    assert len(recover_calls) == 1
    assert recover_calls[0]["workers"] is None
    assert set(recover_calls[0]["pytest_args"]) == set(nodes)
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "applied"


def test_check_mode_ignores_salvage(tmp_path: Path) -> None:
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    target, runner = _salvage_setup(
        tmp_path, baseline=red, candidate=blue, attempts=_failing(count=1)
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert target.read_bytes() == red
    assert len(runner.calls) == 1
