"""Candidate recording, root separation, and duplicate handling."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests._visual_capture_helpers import (
    _ACE_NODE,
    _PAGER_NODE,
    _prepare_repo,
    _session,
    _worker,
    make_png,
)
from tests.ace.tui.visual._visual_capture import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    VisualCaptureError,
    hash_file_tree,
    merge_capture_dir,
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
    assert first.source_file.endswith("test_visual_capture_record.py")


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
