"""Inventory merge/evaluate rules: completeness, pruning, and deselection."""

from __future__ import annotations

import json
from pathlib import Path

from tests._visual_capture_helpers import (
    _ACE_NODE,
    _PAGER_NODE,
    _session,
    _worker,
)
from tests.ace.tui.visual._visual_capture import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    CaptureRecord,
    ComparisonSettings,
    evaluate_inventory,
    merge_capture_dir,
    write_inventory,
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
