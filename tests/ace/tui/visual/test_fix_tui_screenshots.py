"""Image-dependent tests for screenshot maintenance comparison."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._fix_tui_screenshots_helpers import (
    ACE_NODE,
    PAGER_NODE,
    FakeRunner,
    ScriptedCapture,
    commit_all,
    encoding_pair,
    init_repo,
    make_png,
    silent_hooks,
    write_golden,
)
from tests.ace.tui.visual._png_diff_comparison import diff_pngs
from tests.ace.tui.visual._visual_capture import (
    DEFAULT_ACE_ROOT,
    VisualCaptureRoots,
    VisualCaptureSession,
    WorkerSessionRecord,
    merge_capture_dir,
)
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_SUCCESS,
    capture_golden_baseline,
    classify_captures,
    main,
)


pytestmark = pytest.mark.visual


def test_padded_dimension_change_can_have_zero_changed_pixels() -> None:
    small = make_png(1, 1, (255, 0, 0, 255))
    wide = make_png(2, 1, pixels=((255, 0, 0, 255), (0, 0, 0, 0)))
    summary, _diff = diff_pngs(small, wide)
    assert summary.expected_size != summary.actual_size
    assert summary.changed_pixels == 0


def test_classify_treats_dimension_padding_as_updated(tmp_path: Path) -> None:
    init_repo(tmp_path)
    small = make_png(1, 1, (255, 0, 0, 255))
    wide = make_png(2, 1, pixels=((255, 0, 0, 255), (0, 0, 0, 0)))
    write_golden(tmp_path, "ace", "shot.png", small)
    write_golden(tmp_path, "pager", "keep.png", small)
    roots = VisualCaptureRoots(
        ace=tmp_path / DEFAULT_ACE_ROOT,
        pager=tmp_path / "tests/pager/visual/snapshots/png",
    )
    capture_dir = tmp_path / "capture"
    session = VisualCaptureSession(
        capture_dir=capture_dir,
        run_id="run1",
        worker_id="controller",
        repo_root=tmp_path,
        roots=roots,
    )
    session.record_capture(
        name="shot",
        png_bytes=wide,
        snapshot_root=roots.ace,
        node_id=ACE_NODE,
    )
    session.record_capture(
        name="keep",
        png_bytes=small,
        snapshot_root=roots.pager,
        node_id=PAGER_NODE,
    )
    session.write_worker_session(
        WorkerSessionRecord(
            run_id="run1",
            worker_id="controller",
            completed=True,
            collectonly=False,
            exitstatus=0,
            collected_node_ids=(ACE_NODE, PAGER_NODE),
            executed_node_ids=(ACE_NODE, PAGER_NODE),
            skipped_node_ids=(),
            xfailed_node_ids=(),
            xpassed_node_ids=(),
            failed_node_ids=(),
            error_node_ids=(),
            deselected_node_ids=(),
            capture_count=2,
        )
    )
    inventory = merge_capture_dir(
        capture_dir,
        run_id="run1",
        requested_scope="full",
        expected_workers=("controller",),
        session_exitstatus=0,
    )
    baseline = capture_golden_baseline(tmp_path)
    changes = classify_captures(
        inventory,
        baseline=baseline,
        repo_root=tmp_path,
        capture_dir=capture_dir,
    )
    updated = next(item for item in changes if item.kind == "updated")
    assert updated.dimension_mismatch is True
    assert updated.path.endswith("shot.png")


def test_encoding_only_pair_does_not_rewrite_golden(tmp_path: Path) -> None:
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
    assert (
        main([], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        == EXIT_SUCCESS
    )
    assert ace.read_bytes() == first
    assert ace.stat().st_mtime_ns == mtime


def test_update_report_writes_representative_contact_sheet(tmp_path: Path) -> None:
    init_repo(tmp_path)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    write_golden(tmp_path, "ace", "one.png", red)
    write_golden(tmp_path, "ace", "two.png", red)
    write_golden(tmp_path, "pager", "keep.png", red)
    commit_all(tmp_path)
    runner = FakeRunner(
        captures=[
            ScriptedCapture(ACE_NODE, "one", "ace", blue),
            ScriptedCapture(
                "tests/ace/tui/visual/test_a.py::test_two",
                "two",
                "ace",
                blue,
            ),
            ScriptedCapture(PAGER_NODE, "keep", "pager", red),
        ],
        repo_root=tmp_path,
    )

    assert (
        main(["--check"], repo_root=tmp_path, hooks=silent_hooks(runner), environ={})
        != EXIT_SUCCESS
    )

    report_dirs = sorted((tmp_path / ".pytest_cache/sase-visual/runs").glob("*/report"))
    assert report_dirs
    assert (report_dirs[-1] / "contact-sheet.png").is_file()
