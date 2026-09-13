"""Runner-slot admission against parked markers read back by the Rust agent scan.

Other runner-slot tests build scan records from marker JSON in Python. These run
the real scanner, which is how every other waiter sees a parked launch's
authored capacity.
"""

from __future__ import annotations

import json
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
        marker = json.loads((drain / "waiting.json").read_text())
        assert marker["queue_capacity"] == drain_capacity
        assert "wait_runners" not in marker

        started, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(later),
            cl_name="cl",
            timestamp=later.name,
            directive_threshold=100,
            claim=lambda: "started",
        )

    assert started == "started"
    assert not parked
    assert not (later / "waiting.json").exists()


def test_canonical_only_metadata_survives_real_scan_without_waiting_marker(
    tmp_path: Path,
) -> None:
    running = artifact(
        tmp_path,
        "20260913091000",
        200,
        queue_capacity=100,
        queue_capacity_explicit=True,
        queue_weight=2,
        queue_weight_explicit=True,
        run_started_at="2026-09-13T09:10:00+00:00",
    )
    with patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}):
        (scanned,) = [
            record
            for record in run_agent_wait_slots._collect_runner_slot_records()
            if record.artifact_dir == str(running)
        ]
    assert scanned.waiting is None
    assert scanned.agent_meta is not None
    assert scanned.agent_meta.queue_capacity == 100
    assert scanned.agent_meta.queue_capacity_explicit is True
    assert scanned.agent_meta.queue_weight == 2


def test_index_rebuild_keeps_metadata_capacity_after_waiting_marker_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        query_agent_artifact_index,
        rebuild_agent_artifact_index,
    )
    from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire

    waiter = artifact(
        tmp_path,
        "20260913092000",
        201,
        queue_capacity=100,
        queue_capacity_explicit=True,
    )
    run_agent_wait_markers.write_waiting_marker(
        str(waiter),
        {
            "cl_name": "cl",
            "timestamp": waiter.name,
            **run_agent_wait_markers.queue_capacity_marker_fields(100, explicit=True),
            "slot_requested_at": "2026-09-13T09:20:00+00:00",
        },
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    projects_root = tmp_path / ".sase" / "projects"
    index_path = default_agent_artifact_index_path()
    rebuild_agent_artifact_index(index_path, projects_root)
    run_agent_wait_markers.remove_waiting_marker(str(waiter))
    rebuild_agent_artifact_index(index_path, projects_root)
    snapshot = query_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            freshness="cached",
        ),
    )
    (indexed,) = [
        record for record in snapshot.records if record.artifact_dir == str(waiter)
    ]
    assert indexed.waiting is None
    assert indexed.agent_meta is not None
    assert indexed.agent_meta.queue_capacity == 100
    assert indexed.agent_meta.queue_capacity_explicit is True


@pytest.mark.parametrize("budget_enabled", [True, False])
def test_capacity_blocked_head_then_high_budget_launch_uses_real_scan(
    tmp_path: Path,
    budget_enabled: bool,
) -> None:
    artifact(
        tmp_path,
        "20260913093000",
        300,
        run_started_at="2026-09-13T09:30:00+00:00",
    )
    drain = artifact(tmp_path, "20260913093001", 301)
    later = artifact(tmp_path, "20260913093002", 302)

    with (
        override_flags(queue_capacity_budget=budget_enabled),
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            side_effect=run_agent_wait_slots._collect_runner_slot_records,
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
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
            directive_threshold=1 if budget_enabled else 0,
            claim=lambda: "unexpected",
        )
        assert drained is None
        assert parked

        started, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(later),
            cl_name="cl",
            timestamp=later.name,
            directive_threshold=100,
            claim=lambda: "started",
        )

    if budget_enabled:
        assert started == "started"
        assert not parked
        assert not (later / "waiting.json").exists()
    else:
        assert started is None
        assert parked
        later_marker = json.loads((later / "waiting.json").read_text())
        assert later_marker["queue_capacity"] == 100
        assert later_marker["queue_capacity_explicit"] is True
        assert "wait_runners" not in later_marker
