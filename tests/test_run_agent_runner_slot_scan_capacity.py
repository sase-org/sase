"""Runner-slot admission against parked markers read back by the Rust agent scan.

Other runner-slot tests build scan records from marker JSON in Python. These run
the real scanner, which is how every other waiter sees a parked launch's
authored capacity.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.feature_flags import override_flags

from tests._runner_slot_fixtures import artifact


@pytest.mark.parametrize(
    ("budget_enabled", "drain_capacity"),
    [(True, 1), (False, 0)],
)
def test_capacity_blocked_waiter_does_not_park_the_queue_behind_it(
    tmp_path: Path,
    budget_enabled: bool,
    drain_capacity: int,
) -> None:
    artifact(
        tmp_path,
        "20260913090000",
        100,
        run_started_at="2026-09-13T09:00:00+00:00",
    )
    drain = artifact(tmp_path, "20260913090001", 101)
    later = artifact(tmp_path, "20260913090002", 102)

    with (
        override_flags(queue_capacity_budget=budget_enabled),
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            side_effect=run_agent_wait_slots._collect_runner_slot_records,
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=8),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        drained, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(drain),
            cl_name="cl",
            timestamp=drain.name,
            directive_threshold=drain_capacity,
            claim=lambda: "unexpected",
        )
        assert drained is None
        assert parked
        (scanned,) = [
            record.waiting
            for record in run_agent_wait_slots._collect_runner_slot_records()
            if record.artifact_dir == str(drain)
        ]
        assert scanned is not None
        assert scanned.queue_capacity == drain_capacity
        assert scanned.queue_capacity_explicit is True

        started, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(later),
            cl_name="cl",
            timestamp=later.name,
            directive_threshold=None,
            claim=lambda: "started",
        )

    assert started == "started"
    assert not parked
    assert not (later / "waiting.json").exists()
