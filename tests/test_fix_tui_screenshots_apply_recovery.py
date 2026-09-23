"""Apply-robustness and journal-recovery tests for screenshot maintenance."""

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
    init_repo,
    make_png,
    silent_hooks,
    write_golden,
)
from tests.ace.tui.visual._visual_capture_paths import atomic_write_bytes, sha256_bytes
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_FAILURE,
    EXIT_SUCCESS,
    EXIT_USAGE,
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
        "tests.ace.tui.visual._visual_maintenance_salvage.apply_changes",
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


def _write_conflicting_planned_journal(repo: Path) -> tuple[Path, Path]:
    red = make_png(1, 1)
    blue = make_png(1, 1, (0, 0, 255, 255))
    green = make_png(1, 1, (0, 255, 0, 255))
    ace = write_golden(repo, "ace", "shot.png", red)
    write_golden(repo, "pager", "shot.png", red)
    commit_all(repo)
    run_dir = repo / ".pytest_cache/sase-visual/runs/oldrun"
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
    journal_path = run_dir / "apply-journal.json"
    journal_path.write_text(json.dumps(journal), encoding="utf-8")
    return ace, journal_path


def test_update_mode_journal_conflict_exits_usage(tmp_path: Path) -> None:
    init_repo(tmp_path)
    ace, journal_path = _write_conflicting_planned_journal(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", make_png(1, 1)),
            ScriptedCapture(PAGER_NODE, "shot", "pager", make_png(1, 1)),
        ],
        repo_root=tmp_path,
    )
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_USAGE
    )
    assert ace.read_bytes() == make_png(1, 1, (0, 255, 0, 255))
    payload = json.loads(journal_path.read_text(encoding="utf-8"))
    assert payload["status"] == "conflict"


def test_check_mode_unfinished_journal_still_exits_failure(
    tmp_path: Path,
) -> None:
    init_repo(tmp_path)
    ace, _journal_path = _write_conflicting_planned_journal(tmp_path)
    before = ace.read_bytes()
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "shot", "ace", make_png(1, 1)),
            ScriptedCapture(PAGER_NODE, "shot", "pager", make_png(1, 1)),
        ],
        repo_root=tmp_path,
    )
    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_FAILURE
    )
    assert ace.read_bytes() == before


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
