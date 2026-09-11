"""Runtime tests for runner-slot family weight capacity handling."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe import run_agent_wait_markers, run_agent_wait_slots

from tests._runner_slot_fixtures import artifact, record


def test_serial_child_reuses_active_family_weighted_claim(
    tmp_path: Path,
) -> None:
    parent = artifact(
        tmp_path,
        "20260910130000",
        100,
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    child = artifact(
        tmp_path,
        "20260910130001",
        101,
        parent_timestamp=parent.name,
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(parent, started=True), record(child)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(child),
            cl_name="cl",
            timestamp=child.name,
            directive_threshold=None,
            directive_queue_weight=2.0,
            directive_queue_weight_explicit=True,
            claim=lambda: "child-started",
        )

    assert result == "child-started"
    assert not parked
    assert not (child / "waiting.json").exists()


def test_serial_child_publishes_inherited_active_family_weight(
    tmp_path: Path,
) -> None:
    parent = artifact(
        tmp_path,
        "20260910130500",
        100,
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    child = artifact(
        tmp_path,
        "20260910130501",
        101,
        parent_timestamp=parent.name,
        agent_family="fam",
        queue_weight=1.0,
        queue_weight_explicit=False,
    )
    child_meta: dict[str, object] = {
        "pid": 101,
        "parent_timestamp": parent.name,
        "agent_family": "fam",
        "queue_weight": 1.0,
        "queue_weight_explicit": False,
    }

    def claim() -> str:
        assert child_meta["queue_weight"] == 2.0
        assert child_meta["queue_weight_explicit"] is False
        return "child-started"

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(parent, started=True), record(child)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(child),
            cl_name="cl",
            timestamp=child.name,
            directive_threshold=None,
            directive_queue_weight=1.0,
            directive_queue_weight_explicit=False,
            agent_meta=child_meta,
            claim=claim,
        )

    meta = json.loads((child / "agent_meta.json").read_text())
    assert result == "child-started"
    assert not parked
    assert meta["queue_weight"] == 2.0
    assert meta["queue_weight_explicit"] is False
    assert not (child / "waiting.json").exists()


def test_conflicting_active_family_weight_fails_clearly(tmp_path: Path) -> None:
    parent = artifact(
        tmp_path,
        "20260910131000",
        100,
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    child = artifact(
        tmp_path,
        "20260910131001",
        101,
        parent_timestamp=parent.name,
        agent_family="fam",
        queue_weight=1.0,
        queue_weight_explicit=True,
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(parent, started=True), record(child)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
        pytest.raises(run_agent_wait_slots._RunnerSlotAdmissionError) as exc_info,
    ):
        run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(child),
            cl_name="cl",
            timestamp=child.name,
            directive_threshold=None,
            directive_queue_weight=1.0,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
        )

    assert "different explicit weight than its active lineage claim" in str(
        exc_info.value
    )
    assert not (child / "waiting.json").exists()


def test_released_serial_successor_reacquires_capacity(
    tmp_path: Path,
) -> None:
    occupied = artifact(tmp_path, "20260910132000", 100, queue_weight=1.0)
    successor = artifact(
        tmp_path,
        "20260910132001",
        101,
        parent_timestamp="20260910129999",
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=False,
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(occupied, started=True), record(successor)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(successor),
            cl_name="cl",
            timestamp=successor.name,
            directive_threshold=None,
            directive_queue_weight=2.0,
            directive_queue_weight_explicit=False,
            claim=lambda: "unexpected",
        )

    assert result is None
    assert parked
    marker = json.loads((successor / "waiting.json").read_text())
    assert marker["queue_weight"] == 2.0
    assert marker["queue_weight_explicit"] is False


def test_prestamped_released_serial_successor_does_not_reuse_itself(
    tmp_path: Path,
) -> None:
    occupied = artifact(tmp_path, "20260910133000", 100, queue_weight=2.0)
    successor = artifact(
        tmp_path,
        "20260910133001",
        101,
        parent_timestamp="20260910129999",
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=False,
    )
    claims: list[str] = []

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[
                record(occupied, started=True),
                record(successor, started=True),
            ],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(successor),
            cl_name="cl",
            timestamp=successor.name,
            directive_threshold=None,
            directive_queue_weight=2.0,
            directive_queue_weight_explicit=False,
            claim=lambda: claims.append("claimed") or "unexpected",
        )

    assert result is None
    assert parked
    assert claims == []
    marker = json.loads((successor / "waiting.json").read_text())
    assert marker["queue_weight"] == 2.0
    assert marker["queue_weight_explicit"] is False
