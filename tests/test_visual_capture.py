"""Regression tests for the isolated visual candidate-capture protocol."""

from __future__ import annotations

import json
import os
from pathlib import Path
import struct
import zlib

import pytest

from tests.ace.tui.visual._visual_capture import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    CaptureRecord,
    ComparisonSettings,
    VisualCaptureError,
    VisualCaptureRoots,
    VisualCaptureSession,
    WorkerSessionRecord,
    capture_artifact_id,
    canonical_golden_path,
    evaluate_inventory,
    hash_file_tree,
    merge_capture_dir,
    png_dimensions,
    write_inventory,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture, assert_png_matches


_ROOT = Path(__file__).resolve().parents[1]
_ACE_NODE = "tests/ace/tui/visual/test_a.py::test_a"
_PAGER_NODE = "tests/pager/visual/test_b.py::test_b"


def make_png(
    width: int,
    height: int,
    rgba: tuple[int, int, int, int] = (255, 0, 0, 255),
) -> bytes:
    """Return a minimal RGBA PNG without importing Pillow."""
    pixel = bytes(rgba)
    raw = b"".join(b"\x00" + pixel * width for _ in range(height))
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def _lossy_slug(value: str) -> str:
    chars = [char if char.isalnum() or char in "._-" else "_" for char in value]
    return "".join(chars).strip("._-") or "snapshot"


def _prepare_repo(tmp_path: Path) -> tuple[Path, VisualCaptureRoots]:
    ace = tmp_path / DEFAULT_ACE_ROOT
    pager = tmp_path / DEFAULT_PAGER_ROOT
    ace.mkdir(parents=True)
    pager.mkdir(parents=True)
    return tmp_path, VisualCaptureRoots(ace=ace, pager=pager)


def _session(
    tmp_path: Path,
    *,
    worker_id: str = "controller",
    run_id: str = "run1",
    roots: VisualCaptureRoots | None = None,
) -> VisualCaptureSession:
    repo_root, resolved_roots = (
        (tmp_path, roots) if roots is not None else _prepare_repo(tmp_path)
    )
    return VisualCaptureSession(
        capture_dir=tmp_path / "capture",
        run_id=run_id,
        worker_id=worker_id,
        repo_root=repo_root,
        roots=resolved_roots,
    )


def _settings() -> ComparisonSettings:
    return ComparisonSettings(
        max_diff_pixels=None,
        max_diff_ratio=None,
        material_diff_threshold=None,
        max_material_diff_pixels=None,
        env_max_diff_ratio=None,
        env_material_diff_threshold=None,
        env_max_material_diff_pixels=None,
    )


def _capture(
    *,
    canonical: str,
    node_id: str,
    root_identity: str,
    worker_id: str = "gw0",
    sequence: int = 1,
    snapshot_name: str = "shot",
) -> CaptureRecord:
    return CaptureRecord(
        run_id="run1",
        worker_id=worker_id,
        sequence=sequence,
        node_sequence=1,
        artifact_id=f"{worker_id}-{sequence}",
        node_id=node_id,
        snapshot_name=snapshot_name,
        canonical_golden_path=canonical,
        root_identity=root_identity,
        test_file=None,
        test_line=None,
        source_file=None,
        source_line=None,
        candidate_png_relpath=f"workers/{worker_id}/candidates/{sequence}.png",
        candidate_svg_relpath=None,
        candidate_sha256="abc",
        png_width=1,
        png_height=1,
        comparison_settings=_settings(),
    )


def _worker(
    *,
    worker_id: str = "controller",
    completed: bool = True,
    collected: tuple[str, ...] = (_ACE_NODE, _PAGER_NODE),
    executed: tuple[str, ...] | None = None,
    skipped: tuple[str, ...] = (),
    xfailed: tuple[str, ...] = (),
    xpassed: tuple[str, ...] = (),
    failed: tuple[str, ...] = (),
    errored: tuple[str, ...] = (),
    deselected: tuple[str, ...] = (),
    collectonly: bool = False,
    exitstatus: int | None = 0,
    capture_count: int = 0,
    errors: tuple[str, ...] = (),
) -> WorkerSessionRecord:
    if executed is None:
        executed = collected
    return WorkerSessionRecord(
        run_id="run1",
        worker_id=worker_id,
        completed=completed,
        collectonly=collectonly,
        exitstatus=exitstatus,
        collected_node_ids=collected,
        executed_node_ids=executed,
        skipped_node_ids=skipped,
        xfailed_node_ids=xfailed,
        xpassed_node_ids=xpassed,
        failed_node_ids=failed,
        error_node_ids=errored,
        deselected_node_ids=deselected,
        capture_count=capture_count,
        errors=errors,
    )


def _fixture(
    tmp_path: Path,
    snapshot_root: Path,
    session: VisualCaptureSession | None = None,
    *,
    node_id: str = _ACE_NODE,
) -> AcePngSnapshotFixture:
    return AcePngSnapshotFixture(
        snapshot_root=snapshot_root,
        artifact_root=tmp_path / "artifacts",
        update=False,
        node_id=node_id,
        test_file="tests/ace/tui/visual/test_a.py",
        test_line=10,
        repo_root=tmp_path,
        capture_session=session,
    )


def test_png_dimensions_read_ihdr_without_pixels() -> None:
    png = make_png(3, 2, (1, 2, 3, 4))
    assert png_dimensions(png) == (3, 2)


def test_png_dimensions_reject_non_png() -> None:
    with pytest.raises(VisualCaptureError, match="not a PNG"):
        png_dimensions(b"not-a-png")


def test_artifact_ids_remain_distinct_when_lossy_slugs_collide() -> None:
    left = "tests/foo.py::test_a"
    right = "tests_foo.py::test_a"
    assert _lossy_slug(left) == _lossy_slug(right)
    assert capture_artifact_id(
        node_id=left,
        canonical_golden_path=f"{DEFAULT_ACE_ROOT}/a.png",
        sequence=1,
        worker_id="gw0",
    ) != capture_artifact_id(
        node_id=right,
        canonical_golden_path=f"{DEFAULT_ACE_ROOT}/a.png",
        sequence=1,
        worker_id="gw0",
    )


def test_absolute_snapshot_name_is_rejected(tmp_path: Path) -> None:
    _, roots = _prepare_repo(tmp_path)
    with pytest.raises(VisualCaptureError, match="invalid snapshot name"):
        canonical_golden_path(
            snapshot_root=roots.ace,
            name=str(tmp_path / "escaped.png"),
            repo_root=tmp_path,
            roots=roots,
        )


def test_parent_traversal_snapshot_name_is_rejected(tmp_path: Path) -> None:
    _, roots = _prepare_repo(tmp_path)
    with pytest.raises(VisualCaptureError, match="invalid snapshot name"):
        canonical_golden_path(
            snapshot_root=roots.ace,
            name="../escape",
            repo_root=tmp_path,
            roots=roots,
        )


def test_symlink_escape_snapshot_name_is_rejected(tmp_path: Path) -> None:
    _, roots = _prepare_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (roots.ace / "link").symlink_to(outside)
    with pytest.raises(VisualCaptureError, match="escapes ace PNG root"):
        canonical_golden_path(
            snapshot_root=roots.ace,
            name="link/evil",
            repo_root=tmp_path,
            roots=roots,
        )


def test_record_capture_writes_candidates_and_leaves_goldens_untouched(
    tmp_path: Path,
) -> None:
    repo, roots = _prepare_repo(tmp_path)
    golden = roots.ace / "existing.png"
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    golden.write_bytes(red)
    before = hash_file_tree(roots.ace)
    session = _session(tmp_path, roots=roots)

    first = session.record_capture(
        name="one",
        png_bytes=red,
        snapshot_root=roots.ace,
        node_id=_ACE_NODE,
        source_svg="<svg>one</svg>",
    )
    second = session.record_capture(
        name="two",
        png_bytes=blue,
        snapshot_root=roots.ace,
        node_id=_ACE_NODE,
        source_svg="<svg>two</svg>",
    )

    assert first.canonical_golden_path == f"{DEFAULT_ACE_ROOT}/one.png"
    assert second.canonical_golden_path == f"{DEFAULT_ACE_ROOT}/two.png"
    assert first.node_sequence == 1
    assert second.node_sequence == 2
    assert first.candidate_sha256 != second.candidate_sha256
    assert (tmp_path / "capture" / first.candidate_png_relpath).read_bytes() == red
    assert (
        tmp_path / "capture" / first.candidate_svg_relpath
    ).read_text() == "<svg>one</svg>"
    assert golden.read_bytes() == red
    assert hash_file_tree(roots.ace) == before
    assert not (repo / DEFAULT_ACE_ROOT / "one.png").exists()
    assert first.source_file is not None
    assert first.source_file.endswith("test_visual_capture.py")


def test_ace_and_pager_roots_keep_identically_named_snapshots_apart(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    png = make_png(1, 1)
    ace = session.record_capture(
        name="shared",
        png_bytes=png,
        snapshot_root=roots.ace,
        node_id=_ACE_NODE,
    )
    pager = session.record_capture(
        name="shared",
        png_bytes=png,
        snapshot_root=roots.pager,
        node_id=_PAGER_NODE,
    )
    assert ace.root_identity == "ace"
    assert pager.root_identity == "pager"
    assert ace.canonical_golden_path != pager.canonical_golden_path
    assert ace.canonical_golden_path == f"{DEFAULT_ACE_ROOT}/shared.png"
    assert pager.canonical_golden_path == f"{DEFAULT_PAGER_ROOT}/shared.png"


def test_duplicate_canonical_path_on_one_worker_is_rejected(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    png = make_png(1, 1)
    session.record_capture(
        name="dup",
        png_bytes=png,
        snapshot_root=roots.ace,
        node_id=_ACE_NODE,
    )
    with pytest.raises(VisualCaptureError, match="duplicate canonical golden path"):
        session.record_capture(
            name="dup",
            png_bytes=png,
            snapshot_root=roots.ace,
            node_id="tests/ace/tui/visual/test_a.py::test_other",
        )


def test_duplicate_canonical_path_across_workers_is_a_protocol_error(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    png = make_png(1, 1)
    left = _session(tmp_path, worker_id="gw0", roots=roots)
    right = _session(tmp_path, worker_id="gw1", roots=roots)
    left.record_capture(
        name="dup", png_bytes=png, snapshot_root=roots.ace, node_id=_ACE_NODE
    )
    right.record_capture(
        name="dup",
        png_bytes=png,
        snapshot_root=roots.ace,
        node_id="tests/ace/tui/visual/test_a.py::test_other",
    )
    left.write_worker_session(_worker(worker_id="gw0", completed=True, capture_count=1))
    right.write_worker_session(
        _worker(worker_id="gw1", completed=True, capture_count=1)
    )

    inventory = merge_capture_dir(
        tmp_path / "capture",
        run_id="run1",
        requested_scope="full",
        expected_workers=("gw0", "gw1"),
        session_exitstatus=0,
    )

    assert any(
        item.startswith(f"duplicate_canonical_path:{DEFAULT_ACE_ROOT}/dup.png")
        for item in inventory.errors
    )
    assert inventory.full_inventory is False
    assert inventory.pruning_allowed is False
    assert inventory.complete is False


def test_incomplete_worker_output_cannot_prove_full_inventory(
    tmp_path: Path,
) -> None:
    session = _session(tmp_path, worker_id="gw0")
    session.write_worker_session(_worker(worker_id="gw0", completed=False))
    (tmp_path / "capture" / "workers" / "gw1").mkdir(parents=True)
    (tmp_path / "capture" / "workers" / "gw1" / "session.json").write_text(
        "{not json",
        encoding="utf-8",
    )

    inventory = merge_capture_dir(
        tmp_path / "capture",
        run_id="run1",
        requested_scope="full",
        expected_workers=("gw0", "gw1"),
        session_exitstatus=0,
    )

    assert "incomplete_worker:gw0" in inventory.reasons
    assert any(item.startswith("malformed_worker:gw1:") for item in inventory.errors)
    assert inventory.full_inventory is False
    assert inventory.complete is False


def test_missing_worker_and_collection_only_fail_closed() -> None:
    missing = evaluate_inventory(
        run_id="run1",
        requested_scope="full",
        session_exitstatus=0,
        collectonly=False,
        expected_workers=("gw0", "gw1"),
        worker_sessions=(_worker(worker_id="gw0"),),
        captures=(),
    )
    assert "missing_worker:gw1" in missing.reasons
    assert missing.full_inventory is False

    collection_only = evaluate_inventory(
        run_id="run1",
        requested_scope="full",
        session_exitstatus=0,
        collectonly=True,
        expected_workers=("controller",),
        worker_sessions=(_worker(collectonly=True, executed=()),),
        captures=(),
    )
    assert "collection_only" in collection_only.reasons
    assert collection_only.full_inventory is False


def test_full_inventory_requires_both_roots_and_clean_execution() -> None:
    inventory = evaluate_inventory(
        run_id="run1",
        requested_scope="full",
        session_exitstatus=0,
        collectonly=False,
        expected_workers=("controller",),
        worker_sessions=(_worker(capture_count=2),),
        captures=(
            _capture(
                canonical=f"{DEFAULT_ACE_ROOT}/a.png",
                node_id=_ACE_NODE,
                root_identity="ace",
            ),
            _capture(
                canonical=f"{DEFAULT_PAGER_ROOT}/b.png",
                node_id=_PAGER_NODE,
                root_identity="pager",
                worker_id="controller",
            ),
        ),
    )
    assert inventory.full_inventory is True
    assert inventory.pruning_allowed is True
    assert inventory.complete is True
    assert inventory.roots_executed == ("ace", "pager")


def test_skipped_or_failed_visual_nodes_block_full_inventory() -> None:
    skipped = evaluate_inventory(
        run_id="run1",
        requested_scope="full",
        session_exitstatus=0,
        collectonly=False,
        expected_workers=("controller",),
        worker_sessions=(
            _worker(
                executed=(_ACE_NODE,),
                skipped=(_PAGER_NODE,),
            ),
        ),
        captures=(),
    )
    assert "skipped_node:tests/pager/visual/test_b.py::test_b" in skipped.reasons
    assert skipped.full_inventory is False

    failed = evaluate_inventory(
        run_id="run1",
        requested_scope="full",
        session_exitstatus=1,
        collectonly=False,
        expected_workers=("controller",),
        worker_sessions=(
            _worker(executed=(_ACE_NODE, _PAGER_NODE), failed=(_ACE_NODE,)),
        ),
        captures=(),
    )
    assert "session_exitstatus:1" in failed.reasons
    assert failed.complete is False
    assert failed.full_inventory is False


def test_non_visual_deselection_does_not_make_full_inventory_incomplete() -> None:
    inventory = evaluate_inventory(
        run_id="run1",
        requested_scope="full",
        session_exitstatus=0,
        collectonly=False,
        expected_workers=("controller",),
        worker_sessions=(
            _worker(
                deselected=("tests/test_unrelated.py::test_fast",),
            ),
        ),
        captures=(
            _capture(
                canonical=f"{DEFAULT_ACE_ROOT}/a.png",
                node_id=_ACE_NODE,
                root_identity="ace",
            ),
            _capture(
                canonical=f"{DEFAULT_PAGER_ROOT}/b.png",
                node_id=_PAGER_NODE,
                root_identity="pager",
            ),
        ),
    )
    assert inventory.full_inventory is True
    assert inventory.deselected_visual_node_ids == ()


def test_visual_deselection_blocks_full_inventory() -> None:
    inventory = evaluate_inventory(
        run_id="run1",
        requested_scope="full",
        session_exitstatus=0,
        collectonly=False,
        expected_workers=("controller",),
        worker_sessions=(
            _worker(
                collected=(_ACE_NODE,),
                executed=(_ACE_NODE,),
                deselected=(_PAGER_NODE,),
            ),
        ),
        captures=(),
    )
    assert (
        "deselected_visual_node:tests/pager/visual/test_b.py::test_b"
        in inventory.reasons
    )
    assert "visual_root_unexecuted:pager" in inventory.reasons
    assert inventory.full_inventory is False


def test_targeted_scope_disables_pruning_even_when_workers_complete() -> None:
    inventory = evaluate_inventory(
        run_id="run1",
        requested_scope="targeted",
        session_exitstatus=0,
        collectonly=False,
        expected_workers=("controller",),
        worker_sessions=(_worker(collected=(_ACE_NODE,), executed=(_ACE_NODE,)),),
        captures=(
            _capture(
                canonical=f"{DEFAULT_ACE_ROOT}/a.png",
                node_id=_ACE_NODE,
                root_identity="ace",
            ),
        ),
    )
    assert "requested_scope_targeted" in inventory.reasons
    assert inventory.pruning_allowed is False
    assert inventory.full_inventory is False
    assert inventory.complete is True


def test_fixture_capture_mode_continues_after_multiple_snapshots(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    fixture = _fixture(tmp_path, roots.ace, session)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    before = hash_file_tree(roots.ace)

    fixture.assert_png("first", red, source_svg="<svg>first</svg>")
    fixture.assert_png("second", blue, source_svg="<svg>second</svg>")

    assert [record.snapshot_name for record in session.captures] == [
        "first",
        "second",
    ]
    assert hash_file_tree(roots.ace) == before
    assert not (tmp_path / "artifacts").exists()


def test_temp_golden_root_does_not_enter_capture_inventory(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    temp_root = tmp_path / "snapshots" / "png"
    temp_root.mkdir(parents=True)
    png = make_png(1, 1)
    (temp_root / "temp.png").write_bytes(png)
    fixture = _fixture(tmp_path, temp_root, session)

    fixture.assert_png("temp", png)

    assert session.captures == ()
    assert list((tmp_path / "capture").glob("workers/*/captures/*.json")) == []


def test_direct_assert_png_matches_never_records_candidates(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    png = make_png(1, 1)
    (roots.ace / "direct.png").write_bytes(png)

    assert_png_matches(
        "direct",
        png,
        snapshot_root=roots.ace,
        artifact_root=tmp_path / "artifacts",
        update=False,
        node_id=_ACE_NODE,
        repo_root=tmp_path,
    )

    assert session.captures == ()
    assert list((tmp_path / "capture").rglob("*.json")) == []


def test_ordinary_comparison_still_fails_without_capture_session(
    tmp_path: Path,
) -> None:
    _, roots = _prepare_repo(tmp_path)
    (roots.ace / "mismatch.png").write_bytes(make_png(1, 1, (255, 0, 0, 255)))
    fixture = _fixture(tmp_path, roots.ace, session=None)

    with pytest.raises(AssertionError, match="ACE PNG snapshot mismatch"):
        fixture.assert_png("mismatch", make_png(1, 1, (0, 0, 255, 255)))


def test_write_and_load_inventory_round_trip(tmp_path: Path) -> None:
    inventory = evaluate_inventory(
        run_id="run1",
        requested_scope="targeted",
        session_exitstatus=0,
        collectonly=False,
        expected_workers=("controller",),
        worker_sessions=(_worker(collected=(_ACE_NODE,), executed=(_ACE_NODE,)),),
        captures=(),
    )
    path = write_inventory(tmp_path, inventory)
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["kind"] == "inventory"
    assert loaded["schema_version"] == 1
    assert loaded["requested_scope"] == "targeted"
    assert loaded["pruning_allowed"] is False


def _capture_pytest_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "PYTHONPATH",
        os.pathsep.join((str(_ROOT / "src"), str(_ROOT))),
    )
    monkeypatch.delenv("PYTEST_XDIST_WORKER", raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)


def _write_capture_project(
    pytester: pytest.Pytester,
    *,
    red_hex: str,
    blue_hex: str,
) -> None:
    pytester.makeini("[pytest]\naddopts =\n")
    (pytester.path / "ace_png").mkdir()
    (pytester.path / "pager_png").mkdir()
    (pytester.path / "ace_png" / "existing.png").write_bytes(bytes.fromhex(red_hex))
    (pytester.path / "pager_png" / "existing.png").write_bytes(bytes.fromhex(red_hex))
    pytester.makeconftest(
        """
        from pathlib import Path
        import pytest
        from tests._visual_capture_plugin import capture_session_from_config
        from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

        def _fixture(request, snapshot_root):
            return AcePngSnapshotFixture(
                snapshot_root=snapshot_root,
                artifact_root=request.config.rootpath / "artifacts",
                update=False,
                node_id=request.node.nodeid,
                test_file=str(request.node.path),
                test_line=1,
                repo_root=request.config.rootpath,
                capture_session=capture_session_from_config(request.config),
            )

        @pytest.fixture
        def ace_png_visual(request):
            return _fixture(request, request.config.rootpath / "ace_png")

        @pytest.fixture
        def pager_png_visual(request):
            return _fixture(request, request.config.rootpath / "pager_png")
        """
    )
    pytester.makepyfile(
        test_ace=f"""
        RED = bytes.fromhex("{red_hex}")
        BLUE = bytes.fromhex("{blue_hex}")

        def test_ace_multi(ace_png_visual):
            ace_png_visual.assert_png("first", RED, source_svg="<svg>first</svg>")
            ace_png_visual.assert_png("second", BLUE, source_svg="<svg>second</svg>")
        """,
        test_pager=f"""
        RED = bytes.fromhex("{red_hex}")

        def test_pager_one(pager_png_visual):
            pager_png_visual.assert_png("first", RED, source_svg="<svg>pager</svg>")
        """,
    )


def _capture_args(
    capture_dir: Path,
    *,
    scope: str = "full",
    extra: tuple[str, ...] = (),
) -> list[str]:
    return [
        "-p",
        "no:randomly",
        "-p",
        "tests._visual_capture_plugin",
        "--sase-visual-capture-dir",
        str(capture_dir),
        "--sase-visual-capture-run-id",
        "run-xdist",
        "--sase-visual-capture-scope",
        scope,
        "--sase-visual-capture-ace-root",
        "ace_png",
        "--sase-visual-capture-pager-root",
        "pager_png",
        *extra,
    ]


def test_pytester_xdist_project_merges_worker_local_records(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("xdist")
    _capture_pytest_env(monkeypatch)
    red = make_png(1, 1, (255, 0, 0, 255))
    blue = make_png(1, 1, (0, 0, 255, 255))
    _write_capture_project(pytester, red_hex=red.hex(), blue_hex=blue.hex())
    capture_dir = pytester.path / "capture"
    ace_root = pytester.path / "ace_png"
    pager_root = pytester.path / "pager_png"
    before = (hash_file_tree(ace_root), hash_file_tree(pager_root))

    result = pytester.runpytest_subprocess(
        *_capture_args(
            capture_dir,
            extra=("-n", "2", "--dist=loadfile"),
        ),
        timeout=60,
    )

    result.assert_outcomes(passed=2)
    inventory = json.loads((capture_dir / "inventory.json").read_text())
    assert inventory["run_id"] == "run-xdist"
    captures = inventory["captures"]
    assert {item["snapshot_name"] for item in captures} == {"first", "second"}
    assert {item["root_identity"] for item in captures} == {"ace", "pager"}
    workers = {item["worker_id"] for item in inventory["worker_sessions"]}
    assert workers == {"gw0", "gw1"}
    assert list(capture_dir.glob("*.jsonl")) == []
    assert (hash_file_tree(ace_root), hash_file_tree(pager_root)) == before
    assert inventory["full_inventory"] is True
    assert inventory["pruning_allowed"] is True


def test_pytester_ordinary_failure_still_fails_and_keeps_goldens(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    _capture_pytest_env(monkeypatch)
    red = make_png(1, 1, (255, 0, 0, 255))
    pytester.makeini("[pytest]\naddopts =\n")
    (pytester.path / "ace_png").mkdir()
    (pytester.path / "pager_png").mkdir()
    (pytester.path / "ace_png" / "existing.png").write_bytes(red)
    before = hash_file_tree(pytester.path / "ace_png")
    pytester.makeconftest(
        """
        from pathlib import Path
        import pytest
        from tests._visual_capture_plugin import capture_session_from_config
        from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture

        @pytest.fixture
        def ace_png_visual(request):
            return AcePngSnapshotFixture(
                snapshot_root=request.config.rootpath / "ace_png",
                artifact_root=request.config.rootpath / "artifacts",
                update=False,
                node_id=request.node.nodeid,
                repo_root=request.config.rootpath,
                capture_session=capture_session_from_config(request.config),
            )
        """
    )
    pytester.makepyfile(
        f"""
        RED = bytes.fromhex("{red.hex()}")

        def test_captures_then_fails(ace_png_visual):
            ace_png_visual.assert_png("ok", RED)
            raise AssertionError("ordinary failure")
        """
    )
    capture_dir = pytester.path / "capture"

    result = pytester.runpytest_subprocess(
        *_capture_args(capture_dir, scope="targeted"),
        timeout=60,
    )

    result.assert_outcomes(failed=1)
    inventory = json.loads((capture_dir / "inventory.json").read_text())
    assert inventory["captures"]
    assert inventory["complete"] is False
    assert hash_file_tree(pytester.path / "ace_png") == before


def test_assert_page_png_still_proves_convergence_before_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.ace.tui.visual import png_diff

    _, roots = _prepare_repo(tmp_path)
    session = _session(tmp_path, roots=roots)
    fixture = _fixture(tmp_path, roots.ace, session)
    png = make_png(1, 1)
    monkeypatch.setattr(png_diff, "render_svg_to_png", lambda svg: png)
    calls: list[object] = []
    monkeypatch.setattr(
        "tests.ace.tui.visual._ace_png_snapshot_waits.assert_visual_frame_converged",
        lambda captured: calls.append(captured),
    )

    class _AcePage:
        def export_svg(self, title: str | None = None, simplify: bool = True) -> str:
            del title, simplify
            return "<svg />"

    monkeypatch.setattr(png_diff, "AcePage", _AcePage)
    ace_page = _AcePage()

    fixture.assert_page_png(ace_page, "converged")

    assert calls == [ace_page]
    assert session.captures[0].snapshot_name == "converged"
