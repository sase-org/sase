"""Basic outcome-matrix tests for screenshot maintenance application."""

from __future__ import annotations

import json
from pathlib import Path

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
from tests.ace.tui.visual._visual_maintenance import (
    EXIT_DRIFT,
    EXIT_SUCCESS,
    main,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    KIND_CREATED,
    KIND_STALE,
    KIND_UPDATED,
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
