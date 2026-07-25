"""Runtime tests for runner-slot waiting-marker rewrites and directive edits."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots

from tests._runner_slot_fixtures import artifact, record


def test_repeated_slot_polls_preserve_foreign_waiting_marker_fields(
    tmp_path: Path,
) -> None:
    running = [
        artifact(tmp_path, f"2026071212000{index}", 100 + index) for index in range(2)
    ]
    waiter = artifact(tmp_path, "20260712120002", 102)
    requested_at = "2026-07-12T12:00:02+00:00"
    foreign_fields = {
        "waiting_for": ["upstream"],
        "wait_for_artifacts": [{"artifact_dir": "/upstream"}],
        "wait_for_beads": ["sase-87.2"],
        "wait_duration": 300.0,
        "wait_until": "2026-07-12T13:00:00Z",
        "resolved_deps": ["finished"],
        "extension": {"owner": "another-waiter"},
    }
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                **foreign_fields,
                "cl_name": "stale",
                "timestamp": "stale",
                "wait_runners": 99,
                "wait_runners_explicit": False,
                "wait_priority": -1,
                "slot_requested_at": requested_at,
            }
        )
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            side_effect=lambda: [
                *[record(path, started=True) for path in running],
                record(waiter),
            ],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_slots,
            "get_max_running_agents",
            side_effect=[2, 1],
        ),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        for expected_threshold in (1, 0):
            claimed, parked = run_agent_wait_slots._try_claim_runner_slot(
                artifacts_dir=str(waiter),
                cl_name="fresh-cl",
                timestamp=waiter.name,
                directive_threshold=None,
                directive_priority=4,
                claim=lambda: "unexpected",
            )

            assert claimed is None
            assert parked is False
            marker = json.loads((waiter / "waiting.json").read_text())
            for key, value in foreign_fields.items():
                assert marker[key] == value
            assert marker["cl_name"] == "fresh-cl"
            assert marker["timestamp"] == waiter.name
            assert marker["wait_runners"] == expected_threshold
            assert marker["wait_runners_explicit"] is False
            assert marker["wait_priority"] == 4
            assert marker["wait_priority_explicit"] is True
            assert marker["slot_requested_at"] == requested_at


def test_parked_marker_edit_overrides_original_directive(tmp_path: Path) -> None:
    running = [
        artifact(tmp_path, f"2026071212000{index}", 100 + index) for index in range(2)
    ]
    waiter = artifact(tmp_path, "20260712120002", 102)
    (waiter / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "cl",
                "timestamp": waiter.name,
                "wait_runners": 2,
                "wait_runners_explicit": True,
                "slot_requested_at": "2026-07-12T12:00:02+00:00",
            }
        )
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[
                *[record(path, started=True) for path in running],
                record(waiter),
            ],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents") as get_config,
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=0,
            claim=lambda: "started",
        )

    assert result == "started"
    assert not parked
    get_config.assert_not_called()
