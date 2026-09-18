"""Outcome-matrix tests for screenshot maintenance application."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    encoding_pair,
    git_index,
    init_repo,
    make_png,
    silent_hooks,
    write_golden,
)
from tests.ace.tui.visual._visual_capture_paths import atomic_write_bytes, sha256_bytes
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_DRIFT,
    EXIT_FAILURE,
    EXIT_SUCCESS,
    MaintenanceError,
    main,
)
from tests.ace.tui.visual._visual_maintenance_apply import (
    JOURNAL_PLANNED,
    apply_changes,
    recover_unfinished_journals,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    KIND_CREATED,
    KIND_STALE,
    KIND_UPDATED,
    ChangeRecord,
)


def _manifest(repo: Path) -> dict[object, object]:
    paths = sorted(
        (repo / ".pytest_cache/sase-visual/runs").glob("*/manifest.json"),
        key=lambda path: path.stat().st_mtime_ns,
    )
    assert paths
    return json.loads(paths[-1].read_text(encoding="utf-8"))


def _clean_pair(repo: Path) -> tuple[bytes, FakeRunner]:
    red = make_png(1, 1, (255, 0, 0, 255))
    write_golden(repo, "ace", "keep.png", red)
    write_golden(repo, "pager", "keep.png", red)
    commit_all(repo)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "keep", "ace", red),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=repo,
    )
    return red, runner


def test_clean_check_and_update_are_noops(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red, runner = _clean_pair(tmp_path)
    ace = tmp_path / "tests/ace/tui/visual/snapshots/png/keep.png"
    mtime = ace.stat().st_mtime_ns
    index = git_index(tmp_path)
    assert main(
        ["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={}
    ) == (EXIT_SUCCESS)
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == red
    assert ace.stat().st_mtime_ns == mtime
    assert git_index(tmp_path) == index
    assert _manifest(tmp_path)["status"] == "clean"


def test_missing_golden_is_created_on_update_and_drift_on_check(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "new", "ace", red),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=tmp_path,
    )
    created = tmp_path / "tests/ace/tui/visual/snapshots/png/new.png"
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_DRIFT
    )
    assert not created.exists()
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert created.read_bytes() == red
    assert _manifest(tmp_path)["status"] == "applied"
    assert any(item["kind"] == KIND_CREATED for item in _manifest(tmp_path)["changes"])


def test_mismatch_updates_pixels(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
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
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    change = next(
        item for item in _manifest(tmp_path)["changes"] if item["kind"] == KIND_UPDATED
    )
    assert change["path"].endswith("shot.png")
    assert change["byte_equal"] is False
    assert change["encoding_only"] is False


def test_encoding_only_does_not_rewrite_or_touch_mtime(tmp_path: Path) -> None:
    init_repo(tmp_path)
    first, second = encoding_pair()
    ace = write_golden(tmp_path, "ace", "shot.png", first)
    write_golden(tmp_path, "pager", "shot.png", first)
    commit_all(tmp_path)
    mtime = ace.stat().st_mtime_ns
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", second),
            ScriptedCapture(PAGER_NODE, "shot", "pager", first),
        ],
        repo_root=tmp_path,
    )
    assert main(
        ["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={}
    ) == (EXIT_SUCCESS)
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == first
    assert ace.stat().st_mtime_ns == mtime
    change = next(
        item
        for item in _manifest(tmp_path)["changes"]
        if item["root_identity"] == "ace" and item["path"].endswith("shot.png")
    )
    assert change["kind"] == "unchanged"
    assert change["encoding_only"] is True
    assert change["byte_equal"] is False


def test_dimension_only_is_updated_even_if_padding_matches(tmp_path: Path) -> None:
    init_repo(tmp_path)
    small = make_png(1, 1, (255, 0, 0, 255))
    wide = make_png(
        2,
        1,
        pixels=((255, 0, 0, 255), (0, 0, 0, 0)),
    )
    ace = write_golden(tmp_path, "ace", "shot.png", small)
    write_golden(tmp_path, "pager", "shot.png", small)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", wide),
            ScriptedCapture(PAGER_NODE, "shot", "pager", small),
        ],
        repo_root=tmp_path,
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_DRIFT
    )
    assert ace.read_bytes() == small
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == wide
    change = next(
        item for item in _manifest(tmp_path)["changes"] if item["kind"] == KIND_UPDATED
    )
    assert change["dimension_mismatch"] is True


def test_stale_removed_only_for_full_inventory(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    write_golden(tmp_path, "ace", "keep.png", red)
    stale = write_golden(tmp_path, "ace", "orphan.png", red)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "keep", "ace", red),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=tmp_path,
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_DRIFT
    )
    assert stale.exists()
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert not stale.exists()
    assert any(item["kind"] == KIND_STALE for item in _manifest(tmp_path)["changes"])


def test_targeted_run_does_not_report_or_delete_orphans(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    target = write_golden(tmp_path, "ace", "shot.png", red)
    orphan = write_golden(tmp_path, "ace", "orphan.png", red)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[ScriptedCapture(ACE_NODE, "shot", "ace", blue)],
        repo_root=tmp_path,
    )
    assert (
        main(
            ["--", "tests/ace/tui/visual/test_a.py"],
            repo_root=tmp_path,
            hooks=silent_hooks(runner),
            environ={},
        )
        == EXIT_SUCCESS
    )
    assert target.read_bytes() == blue
    assert orphan.exists()
    kinds = {item["kind"] for item in _manifest(tmp_path)["changes"]}
    assert KIND_STALE not in kinds


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
        exit_code=1,
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert target.read_bytes() == red
    assert _manifest(tmp_path)["child_exit_code"] == 1
    assert _manifest(tmp_path)["status"] == "failed"


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
        return 0

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


def test_failed_verification_aborts_update(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    target = write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
        verify_png=green,
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert target.read_bytes() == red
    assert any(str(call["run_id"]).endswith("-verify") for call in runner.calls)


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


def test_concurrent_edit_refuses_apply(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    target = write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)

    class MutatingRunner(FakeRunner):
        def __call__(self, **kwargs: object) -> int:  # type: ignore[override]
            result = super().__call__(**kwargs)
            if not str(kwargs["run_id"]).endswith("-verify"):
                target.write_bytes(green)
            return result

    runner = MutatingRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", blue),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert target.read_bytes() == green


def test_report_is_rendered_before_apply_and_preserved_on_apply_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
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
    )

    def fail_after_report(*args: object, **kwargs: object) -> Path:
        run_dir = args[0]
        assert isinstance(run_dir, Path)
        assert (run_dir / "report/visual-failure-report.html").is_file()
        raise MaintenanceError("boom")

    monkeypatch.setattr(
        "tests.ace.tui.visual._visual_maintenance_run.apply_changes",
        fail_after_report,
    )

    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert target.read_bytes() == red
    manifest = _manifest(tmp_path)
    assert manifest["status"] == "failed"
    assert any(item["kind"] == KIND_UPDATED for item in manifest["changes"])
    assert manifest["report"]["html"].endswith("visual-failure-report.html")
    assert (tmp_path / manifest["report"]["html"]).is_file()


def test_write_failure_rolls_back_applied_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    ace = write_golden(tmp_path, "ace", "one.png", red)
    pager = write_golden(tmp_path, "pager", "two.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "one", "ace", blue),
            ScriptedCapture(PAGER_NODE, "two", "pager", blue),
        ],
        repo_root=tmp_path,
    )
    real = atomic_write_bytes
    calls = {"n": 0, "fail": True}

    def boom(path: Path, data: bytes) -> None:
        path_s = path.as_posix()
        if (
            calls["fail"]
            and "snapshots/png" in path_s
            and "backups" not in path.parts
            and ".pytest_cache" not in path.parts
        ):
            calls["n"] += 1
            if calls["n"] >= 2:
                calls["fail"] = False
                raise OSError("disk full")
        real(path, data)

    monkeypatch.setattr(
        "tests.ace.tui.visual._visual_maintenance_apply.atomic_write_bytes",
        boom,
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == red
    assert pager.read_bytes() == red


def test_unfinished_journal_recovers_on_update_and_check_refuses(
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    ace = write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    run_dir = tmp_path / ".pytest_cache/sase-visual/runs/oldrun"
    run_dir.mkdir(parents=True)
    backup = run_dir / "backups/tests/ace/tui/visual/snapshots/png/shot.png"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(red)
    ace.write_bytes(blue)
    journal = {
        "schema_version": 1,
        "kind": "visual_maintenance_journal",
        "run_id": "oldrun",
        "status": JOURNAL_PLANNED,
        "entries": [
            {
                "path": "tests/ace/tui/visual/snapshots/png/shot.png",
                "action": "update",
                "before_sha256": sha256_bytes(red),
                "after_sha256": sha256_bytes(blue),
                "backup_relpath": "backups/tests/ace/tui/visual/snapshots/png/shot.png",
                "candidate_png_relpath": "unused.png",
                "state": "applied",
            }
        ],
    }
    (run_dir / "apply-journal.json").write_text(json.dumps(journal), encoding="utf-8")
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", red),
            ScriptedCapture(PAGER_NODE, "shot", "pager", red),
        ],
        repo_root=tmp_path,
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == blue
    recovered = recover_unfinished_journals(
        tmp_path / ".pytest_cache/sase-visual",
        tmp_path,
        allow_writes=True,
    )
    assert recovered
    assert ace.read_bytes() == red
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )


def test_journal_conflict_refuses_recovery(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    ace = write_golden(tmp_path, "ace", "shot.png", red)
    write_golden(tmp_path, "pager", "shot.png", red)
    commit_all(tmp_path)
    run_dir = tmp_path / ".pytest_cache/sase-visual/runs/oldrun"
    run_dir.mkdir(parents=True)
    backup = run_dir / "backups/tests/ace/tui/visual/snapshots/png/shot.png"
    backup.parent.mkdir(parents=True)
    backup.write_bytes(red)
    ace.write_bytes(green)
    journal = {
        "schema_version": 1,
        "kind": "visual_maintenance_journal",
        "run_id": "oldrun",
        "status": JOURNAL_PLANNED,
        "entries": [
            {
                "path": "tests/ace/tui/visual/snapshots/png/shot.png",
                "action": "update",
                "before_sha256": sha256_bytes(red),
                "after_sha256": sha256_bytes(blue),
                "backup_relpath": "backups/tests/ace/tui/visual/snapshots/png/shot.png",
                "state": "applied",
            }
        ],
    }
    (run_dir / "apply-journal.json").write_text(json.dumps(journal), encoding="utf-8")
    with pytest.raises(Exception, match="conflicts"):
        recover_unfinished_journals(
            tmp_path / ".pytest_cache/sase-visual",
            tmp_path,
            allow_writes=True,
        )
    assert ace.read_bytes() == green


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


def test_apply_changes_unit_creates_and_deletes(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1)
    stale = write_golden(tmp_path, "ace", "old.png", red)
    capture_dir = tmp_path / "capture"
    capture_dir.mkdir()
    candidate = capture_dir / "new.png"
    candidate.write_bytes(red)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    changes = (
        ChangeRecord(
            kind=KIND_CREATED,
            path="tests/ace/tui/visual/snapshots/png/new.png",
            root_identity="ace",
            node_id=ACE_NODE,
            snapshot_name="new",
            baseline_sha256=None,
            candidate_sha256=sha256_bytes(red),
            baseline_width=None,
            baseline_height=None,
            candidate_width=1,
            candidate_height=1,
            changed_pixels=None,
            total_pixels=1,
            material_diff_pixels=None,
            byte_equal=False,
            encoding_only=False,
            dimension_mismatch=False,
            candidate_png_relpath="new.png",
            candidate_svg_relpath=None,
            artifact_id="a",
        ),
        ChangeRecord(
            kind=KIND_STALE,
            path="tests/ace/tui/visual/snapshots/png/old.png",
            root_identity="ace",
            node_id=None,
            snapshot_name=None,
            baseline_sha256=sha256_bytes(red),
            candidate_sha256=None,
            baseline_width=1,
            baseline_height=1,
            candidate_width=None,
            candidate_height=None,
            changed_pixels=None,
            total_pixels=1,
            material_diff_pixels=None,
            byte_equal=False,
            encoding_only=False,
            dimension_mismatch=False,
            candidate_png_relpath=None,
            candidate_svg_relpath=None,
            artifact_id=None,
        ),
    )
    apply_changes(
        run_dir,
        changes,
        repo_root=tmp_path,
        capture_dir=capture_dir,
        run_id="unit",
    )
    assert (tmp_path / "tests/ace/tui/visual/snapshots/png/new.png").read_bytes() == red
    assert not stale.exists()
