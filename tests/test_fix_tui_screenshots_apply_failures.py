"""Skipped-run outcome tests for screenshot maintenance application."""

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
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    main,
)
from tests.ace.tui.visual._visual_maintenance_types import KIND_UPDATED


def _manifest(repo: Path) -> dict[object, object]:
    paths = sorted(
        (repo / ".pytest_cache/sase-visual/runs").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    assert paths
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def test_pytest_failure_does_not_apply(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    target = write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
        attempts=[
            AttemptScript(exit_code=1, failed=(ACE_NODE,)),
            AttemptScript(exit_code=1, failed=(ACE_NODE,)),
            AttemptScript(exit_code=1, failed=(ACE_NODE,)),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == red
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "partial"
    assert manifest["child_exit_code"] == 1
    labels = [attempt["label"] for attempt in manifest["attempts"]]
    assert labels == ["capture", "recover-1", "recover-2"]
    skips = manifest["skipped"]
    assert len(skips) == 1
    assert skips[0]["kind"] == "node"
    assert skips[0]["node_id"] == ACE_NODE
    assert skips[0]["reason"] == "test_failed"
    assert skips[0]["attempts"] == 3
    assert "FAILED" in skips[0]["detail"]
    assert manifest["warnings"]
    assert any(item["kind"] == "unchanged" for item in manifest["changes"])
    assert not any(item["kind"] == KIND_UPDATED for item in manifest["changes"])


def test_zero_tests_are_an_error(tmp_path: Path) -> None:
    init_repo(tmp_path)
    write_golden(tmp_path, "ace", "keep.png", make_png(1, 1))
    commit_all(tmp_path)

    def empty_runner(**kwargs: object) -> int:
        capture_dir = kwargs["capture_dir"]  # type: ignore[assignment]
        assert isinstance(capture_dir, Path)
        log_path = kwargs["log_path"]
        assert isinstance(log_path, Path)
        log_path.write_text("empty\n", encoding="utf-8")
        from tests.ace.tui.visual._visual_capture import (
            WorkerSessionRecord,
            evaluate_inventory,
            write_inventory,
        )

        inventory = evaluate_inventory(
            run_id=str(kwargs["run_id"]),
            requested_scope="full",
            session_exitstatus=0,
            collectonly=False,
            expected_workers=("controller",),
            worker_sessions=(
                WorkerSessionRecord(
                    run_id=str(kwargs["run_id"]),
                    worker_id="controller",
                    completed=True,
                    collectonly=False,
                    exitstatus=0,
                    collected_node_ids=(),
                    executed_node_ids=(),
                    skipped_node_ids=(),
                    xfailed_node_ids=(),
                    xpassed_node_ids=(),
                    failed_node_ids=(),
                    error_node_ids=(),
                    deselected_node_ids=(),
                    capture_count=0,
                ),
            ),
            captures=(),
        )
        write_inventory(capture_dir, inventory)
        return 5

    hooks = silent_hooks(FakeRunner(captures=[], repo_root=tmp_path))
    hooks = type(hooks)(
        preflight=hooks.preflight,
        run_pytest=empty_runner,
        is_ci=hooks.is_ci,
        renderer_identity=hooks.renderer_identity,
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=hooks, environ={}) == EXIT_FAILURE
    )
    assert main([], repo_root=tmp_path, hooks=hooks, environ={}) == EXIT_SUCCESS
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "clean"
    assert manifest["child_exit_code"] == 5
    assert any(
        "selection matched no visual tests" in warning
        for warning in manifest["warnings"]
    )


def test_failed_verification_skips_unstable_update(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    yellow = make_png(1, 1, (255, 255, 0, 255))
    cyan = make_png(1, 1, (0, 255, 255, 255))
    target = write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
        verify_attempts=[
            AttemptScript(exit_code=0, pngs={ACE_NODE: green}),
            AttemptScript(exit_code=0, pngs={ACE_NODE: yellow}),
            AttemptScript(exit_code=0, pngs={ACE_NODE: cyan}),
        ],
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == red
    assert any("-verify" in str(call["run_id"]) for call in runner.calls)
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "partial"
    assert any(
        item["reason"] == "unstable" and item["node_id"] == ACE_NODE
        for item in manifest["skipped"]
    )


def test_pre_existing_dirty_paths_are_recorded_separately(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    dirty = write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    dirty.write_bytes(blue)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
    )
    assert main(
        ["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={}
    ) == (EXIT_SUCCESS)
    manifest = _manifest(tmp_path)
    assert any(path.endswith("shot.png") for path in manifest["dirty_before"])
    assert manifest["status"] == "clean"


def test_concurrent_edit_skips_only_the_conflicting_path(
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    target = write_golden(tmp_path, "ace", "shot.png", red)
    other = write_golden(tmp_path, "ace", "other.png", red)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)

    class MutatingRunner(FakeRunner):
        def __call__(self, **kwargs: object) -> int:  # type: ignore[override]
            result = super().__call__(**kwargs)
            if not str(kwargs["run_id"]).endswith("-verify"):
                target.write_bytes(green)
            return result

    other_node = "tests/ace/tui/visual/test_a.py::test_other"
    runner = MutatingRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(other_node, "other", "ace", blue),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=tmp_path,
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == green
    assert other.read_bytes() == blue
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "partial"
    skips = [
        item for item in manifest["skipped"] if item["reason"] == "concurrent_edit"
    ]
    assert len(skips) == 1
    assert skips[0]["path"] is not None and skips[0]["path"].endswith("shot.png")
    assert any(
        item["kind"] == KIND_UPDATED and item["path"].endswith("other.png")
        for item in manifest["changes"]
    )


def test_check_does_not_run_verification_pass(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_DRIFT
    )
    assert len(runner.calls) == 1
    assert not str(runner.calls[0]["run_id"]).endswith("-verify")
