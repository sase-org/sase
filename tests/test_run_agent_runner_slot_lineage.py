"""Runtime tests for Rust-authoritative runner-slot claim lineage.

Covers the admission-authority contract: Rust's ``candidate_decision`` is
the single source of truth for whether a candidate acquires, reuses, or is
blocked from capacity, and its resolved ``runner_claim_owner_key`` is
persisted durably so later admission checks -- even ones a ``capacity_only``
scan can no longer see a released predecessor for -- resolve lineage from a
record's own metadata instead of re-walking a live scan.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.core.agent_scan_facade import scan_agent_artifacts
from sase.core.paths import sase_projects_dir

from tests._runner_slot_fixtures import artifact, record


def test_serial_successor_of_live_parallel_member_reuses_lineage_and_persists_owner(
    tmp_path: Path,
) -> None:
    parallel_member = artifact(
        tmp_path,
        "20260910140000",
        100,
        agent_family="fam",
        agent_family_parallel=True,
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    successor = artifact(
        tmp_path,
        "20260910140001",
        101,
        parent_timestamp=parallel_member.name,
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=False,
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[
                record(parallel_member, started=True),
                record(successor),
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
            claim=lambda: "successor-started",
        )

    assert result == "successor-started"
    assert not parked
    meta = json.loads((successor / "agent_meta.json").read_text())
    assert meta["runner_claim_owner_key"] == "fam:parallel:20260910140000"
    assert meta["queue_weight"] == 2.0


def test_unrelated_serial_branch_does_not_join_persisted_parallel_lineage(
    tmp_path: Path,
) -> None:
    """A live unrelated branch sharing ``agent_family`` must not merge claims.

    The successor already carries its actual (released) parallel
    predecessor's owner key durably on disk -- exactly what
    ``_add_family_metadata``/``create_followup_artifacts`` now persist -- so
    it must resolve its own lineage from that key rather than from the
    coincidentally-shared ``agent_family`` string.
    """
    serial_branch = artifact(
        tmp_path,
        "20260910141000",
        100,
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    successor = artifact(
        tmp_path,
        "20260910141001",
        101,
        parent_timestamp="20260910139999",
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=False,
        runner_claim_owner_key="fam:parallel:20260910139999",
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[
                record(serial_branch, started=True),
                record(successor),
            ],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=4),
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
            claim=lambda: "successor-started",
        )

    # The unrelated branch occupies 2.0 of the 4.0 limit; the successor's own
    # released parallel lineage is independently free, so it acquires its own
    # 2.0 claim instead of either merging with or being blocked by the
    # unrelated same-family branch.
    assert result == "successor-started"
    assert not parked
    meta = json.loads((successor / "agent_meta.json").read_text())
    assert meta["runner_claim_owner_key"] == "fam:parallel:20260910139999"


def test_released_lineage_reacquires_at_new_explicit_weight(
    tmp_path: Path,
) -> None:
    """A released lineage may reacquire at a different explicitly-authored weight."""
    occupied = artifact(tmp_path, "20260910142000", 100, queue_weight=1.0)
    successor = artifact(
        tmp_path,
        "20260910142001",
        101,
        parent_timestamp="20260910139998",
        agent_family="fam",
        queue_weight=0.5,
        queue_weight_explicit=True,
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
            directive_queue_weight=0.5,
            directive_queue_weight_explicit=True,
            claim=lambda: "successor-started",
        )

    assert result == "successor-started"
    assert not parked
    meta = json.loads((successor / "agent_meta.json").read_text())
    assert meta["queue_weight"] == 0.5
    assert meta["queue_weight_explicit"] is True


def test_invalid_ancestor_weight_fails_closed_for_inherited_successor(
    tmp_path: Path,
) -> None:
    """An ancestor's invalid legacy weight must block, not silently default."""
    poisoned_ancestor = artifact(
        tmp_path,
        "20260910143000",
        100,
        agent_family="fam",
        queue_weight="not-a-number",
        queue_weight_invalid=True,
    )
    successor = artifact(
        tmp_path,
        "20260910143001",
        101,
        parent_timestamp=poisoned_ancestor.name,
        agent_family="fam",
        queue_weight=1.0,
        queue_weight_explicit=False,
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(poisoned_ancestor), record(successor)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
        pytest.raises(run_agent_wait_slots._RunnerSlotAdmissionError),
    ):
        run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(successor),
            cl_name="cl",
            timestamp=successor.name,
            directive_threshold=None,
            directive_queue_weight=1.0,
            directive_queue_weight_explicit=False,
            claim=lambda: "unexpected",
        )


def test_malformed_candidate_decision_fails_closed(tmp_path: Path) -> None:
    """A missing/malformed Rust decision must never be treated as permission."""
    waiter = artifact(tmp_path, "20260910144000", 101)

    def broken_snapshot(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "schema_version": 2,
            "effective_limit": 1.0,
            "occupied_lanes": 0,
            "occupied_capacity": 0.0,
            "claims": [],
            "waiters": [],
            "candidate_decision": {"decision": "not-a-real-decision"},
        }

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
        patch(
            "sase.core.runner_slots._admission._core_runner_capacity_snapshot",
            side_effect=broken_snapshot,
        ),
        pytest.raises(run_agent_wait_slots._RunnerSlotAdmissionError, match="decision"),
    ):
        run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "unexpected",
        )


def test_fresh_acquire_persists_runner_claim_owner_key(tmp_path: Path) -> None:
    """A standalone agent's first admission durably stamps its own owner key."""
    solo = artifact(tmp_path, "20260910145000", 101)

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ) as scan,
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(solo),
            cl_name="cl",
            timestamp=solo.name,
            directive_threshold=None,
            claim=lambda: "solo-started",
        )

    assert result == "solo-started"
    assert not parked
    scan.assert_called_once_with()
    meta = json.loads((solo / "agent_meta.json").read_text())
    assert meta["runner_claim_owner_key"] == solo.name


def test_capacity_only_dropped_predecessor_does_not_break_persisted_lineage(
    tmp_path: Path,
) -> None:
    """A done, ``capacity_only``-dropped ancestor must not break lineage.

    ``elder`` is the original parallel member; it has finished (``done.json``
    present), so a ``capacity_only`` scan drops its directory entirely.
    ``holder`` is elder's live serial successor, carrying elder's owner key
    forward durably (as ``_add_family_metadata``/``create_followup_artifacts``
    now do). ``grandchild`` is a *third*-generation continuation that also
    carries that same durable owner key. Even though the real scanner never
    sees ``elder`` at all, ``grandchild`` must resolve onto the *same* claim
    as ``holder`` -- not double-charge capacity, and not fail to admit for
    lack of a live ancestor chain.
    """
    elder = artifact(
        tmp_path,
        "20260910150000",
        100,
        agent_family="fam",
        agent_family_parallel=True,
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    (elder / "done.json").write_text("{}", encoding="utf-8")
    holder = artifact(
        tmp_path,
        "20260910150001",
        101,
        parent_timestamp=elder.name,
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=False,
        runner_claim_owner_key="fam:parallel:20260910150000",
    )
    grandchild = artifact(
        tmp_path,
        "20260910150002",
        102,
        parent_timestamp=holder.name,
        agent_family="fam",
        queue_weight=2.0,
        queue_weight_explicit=False,
        runner_claim_owner_key="fam:parallel:20260910150000",
    )

    with (
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        real_scan = scan_agent_artifacts(
            sase_projects_dir(), run_agent_wait_slots._RUNNER_SLOT_SCAN_OPTIONS
        )
        scanned_timestamps = {record.timestamp for record in real_scan.records}
        assert elder.name not in scanned_timestamps
        assert holder.name in scanned_timestamps

        with patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[
                record(holder, started=True),
                record(grandchild),
            ],
        ):
            result, parked = run_agent_wait_slots._try_claim_runner_slot(
                artifacts_dir=str(grandchild),
                cl_name="cl",
                timestamp=grandchild.name,
                directive_threshold=None,
                directive_queue_weight=2.0,
                directive_queue_weight_explicit=False,
                claim=lambda: "grandchild-started",
            )

    assert result == "grandchild-started"
    assert not parked
    meta = json.loads((grandchild / "agent_meta.json").read_text())
    assert meta["runner_claim_owner_key"] == "fam:parallel:20260910150000"
    assert meta["queue_weight"] == 2.0
