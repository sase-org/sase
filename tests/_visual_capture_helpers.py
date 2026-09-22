"""Shared builders for visual candidate-capture protocol tests."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from tests.ace.tui.visual._visual_capture import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    VisualCaptureRoots,
    VisualCaptureSession,
    WorkerSessionRecord,
)
from tests.ace.tui.visual.png_diff import AcePngSnapshotFixture


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
