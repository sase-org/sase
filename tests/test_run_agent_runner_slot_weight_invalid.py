"""Runner-slot admission rejects invalid persisted queue weights."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe import run_agent_wait_markers, run_agent_wait_slots

from tests._runner_slot_fixtures import artifact, record


@pytest.mark.parametrize(
    "queue_weight",
    [None, 0, -1, True, "0.25", float("inf"), float("nan")],
)
def test_invalid_waiting_marker_queue_weight_fails_closed(
    tmp_path: Path,
    queue_weight: object,
) -> None:
    waiter = artifact(tmp_path, "20260910134000", 101)
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                "slot_requested_at": "2026-09-10T13:40:00+00:00",
                "queue_weight": queue_weight,
                "queue_weight_explicit": True,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(waiter)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
        pytest.raises(
            run_agent_wait_slots._RunnerSlotAdmissionError,
            match="Invalid queue_weight in waiting marker",
        ),
    ):
        run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "unexpected",
        )


def test_invalid_scanned_agent_meta_queue_weight_fails_closed(
    tmp_path: Path,
) -> None:
    waiter = artifact(
        tmp_path,
        "20260910135000",
        101,
        queue_weight=True,
        queue_weight_explicit=True,
        queue_weight_invalid=True,
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(waiter)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=2),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
        pytest.raises(
            run_agent_wait_slots._RunnerSlotAdmissionError,
            match="Invalid queue_weight in agent metadata",
        ),
    ):
        run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            directive_queue_weight=1.0,
            directive_queue_weight_explicit=False,
            claim=lambda: "unexpected",
        )
