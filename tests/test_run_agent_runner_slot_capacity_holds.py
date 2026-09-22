"""Runtime tests for runner-slot hold-barrier admission."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.core.agent_scan_wire import AgentArtifactRecordWire

from tests._runner_slot_fixtures import artifact, record


def test_active_holds_are_threaded_into_locked_admission(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260910120500", 505)
    hold = {"armer": {"key": "agent:hold-a"}}
    captured: dict[str, object] = {}

    def snapshot(
        records: list[AgentArtifactRecordWire],
        _is_live: object,
        **kwargs: object,
    ) -> dict[str, object]:
        captured["records"] = records
        captured["active_holds"] = kwargs["active_holds"]
        captured["candidate"] = kwargs["candidate"]
        return {
            "candidate_decision": {
                "artifact_dir": str(waiter),
                "decision": "blocked",
                "owner_key": waiter.name,
                "lineage_key": waiter.name,
                "effective_weight": 1.0,
                "blockers": [
                    {"code": "hold-barrier", "message": "held by agent:hold-a"}
                ],
            }
        }

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ) as scan,
        patch.object(
            run_agent_wait_slots,
            "snapshot_active_agent_holds",
            return_value=([], [hold], []),
        ) as active_holds,
        patch.object(
            run_agent_wait_slots,
            "runner_capacity_snapshot",
            side_effect=snapshot,
        ),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=4),
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
            directive_threshold=None,
            agent_meta={
                "name": "target.agent--code",
                "workflow_name": "build",
                "agent_clan": "blocked-clan",
                "tribe": "ops",
                "agent_family": "target.agent",
            },
            claim=lambda: "unexpected",
        )

    assert result is None
    assert parked
    scan.assert_called_once()
    active_holds.assert_called_once()
    assert active_holds.call_args.args == ([],)
    assert captured["records"] == []
    assert captured["active_holds"] == [hold]
    candidate = captured["candidate"]
    assert isinstance(candidate, dict)
    assert candidate["agent_name"] == "target.agent--code"
    assert candidate["workflow"] == "build"
    assert candidate["clan"] == "blocked-clan"
    assert candidate["tribe"] == "ops"
    marker = json.loads((waiter / "waiting.json").read_text())
    assert marker["slot_requested_at"]


def test_hold_barrier_blocker_writes_held_by_onto_the_waiting_marker(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260911090500", 606)
    decisions = [
        {
            "candidate_decision": {
                "artifact_dir": str(waiter),
                "decision": "blocked",
                "owner_key": waiter.name,
                "lineage_key": waiter.name,
                "effective_weight": 1.0,
                "blockers": [
                    {
                        "code": "hold-barrier",
                        "message": "held by agent:hold-a (expires in 5m)",
                        "held_by": "agent:hold-a",
                        "hold_expires_at": 1_700_000_300.0,
                    }
                ],
            }
        },
        {
            "candidate_decision": {
                "artifact_dir": str(waiter),
                "decision": "blocked",
                "owner_key": waiter.name,
                "lineage_key": waiter.name,
                "effective_weight": 1.0,
                "blockers": [{"code": "insufficient-capacity", "message": "full"}],
            }
        },
    ]

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(
            run_agent_wait_slots,
            "snapshot_active_agent_holds",
            return_value=([], [], []),
        ),
        patch.object(
            run_agent_wait_slots,
            "runner_capacity_snapshot",
            side_effect=lambda *_args, **_kwargs: decisions.pop(0),
        ),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=4),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "unexpected",
        )
        marker = json.loads((waiter / "waiting.json").read_text())
        assert marker["held_by"] == "agent:hold-a"
        assert marker["hold_expires_at"] == 1_700_000_300.0

        # A later poll where the hold has released self-heals the marker: no
        # third party ever writes into it, the candidate clears its own stale
        # held_by/hold_expires_at on its next admission attempt.
        run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "unexpected",
        )
        marker = json.loads((waiter / "waiting.json").read_text())
        assert "held_by" not in marker
        assert "hold_expires_at" not in marker


def test_hold_deadlock_upserts_a_deduped_notification(tmp_path: Path) -> None:
    candidate = artifact(tmp_path, "20260911090000", 700)
    (candidate / "agent_meta.json").write_text(
        json.dumps({"pid": 700, "name": "candidate.agent--code"})
    )
    armer = artifact(tmp_path, "20260911085900", 701)
    (armer / "agent_meta.json").write_text(
        json.dumps({"pid": 701, "name": "armer.agent--code"})
    )
    (armer / "waiting.json").write_text(
        json.dumps({"waiting_for": ["candidate.agent--code"]})
    )

    def scan() -> list[AgentArtifactRecordWire]:
        return [record(candidate), record(armer)]

    decision_payload = {
        "candidate_decision": {
            "artifact_dir": str(candidate),
            "decision": "blocked",
            "owner_key": candidate.name,
            "lineage_key": candidate.name,
            "effective_weight": 1.0,
            "blockers": [
                {
                    "code": "hold-barrier",
                    "message": "held by armer.agent--code (expires in 5m)",
                    "held_by": "agent:armer.agent--code",
                    "hold_expires_at": 1_700_000_300.0,
                }
            ],
        }
    }
    hold = {
        "armer": {
            "kind": "agent",
            "key": "agent:armer.agent--code",
            "done_marker_path": f"{armer}/done.json",
        }
    }

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(
            run_agent_wait_slots,
            "snapshot_active_agent_holds",
            return_value=([], [hold], []),
        ),
        patch.object(
            run_agent_wait_slots,
            "runner_capacity_snapshot",
            return_value=decision_payload,
        ),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=4),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        for _ in range(2):
            run_agent_wait_slots._try_claim_runner_slot(
                artifacts_dir=str(candidate),
                cl_name="cl",
                timestamp=candidate.name,
                directive_threshold=None,
                claim=lambda: "unexpected",
            )

        from sase.notifications.store import load_notifications

        notifications = load_notifications()

    dedup_key = f"runner_slot:hold-deadlock:{candidate}:agent:armer.agent--code"
    matches = [n for n in notifications if n.dedup_key == dedup_key]
    assert len(matches) == 1
    assert matches[0].sender == "runner_slot_admission"
    assert matches[0].plus_one_count == 1
    assert "candidate.agent--code" in matches[0].notes[1]


def test_real_agent_hold_parks_a_waiter_and_release_resumes_it(
    tmp_path: Path,
) -> None:
    """A hold armed through the real store blocks admission until released.

    Unlike ``test_active_holds_are_threaded_into_locked_admission`` (which
    mocks ``snapshot_active_agent_holds`` to prove the wiring), this exercises
    the real Rust hold store end to end: arm, blocked claim, release,
    admitted claim.
    """
    from sase.core.agent_hold_facade import arm_agent_hold, release_agent_hold

    # The armer's own pid must be alive (this test process is) -- an agent
    # armer's fail-open liveness fact is derived from a real is_process_alive
    # check, so an arbitrary/dead pid here would prune the hold before the
    # claim below ever evaluates its selectors. run_started_at must also be
    # recent: with none recorded, is_process_alive falls back to parsing the
    # artifact dir's name as a start time, and this fixture's fixed 2026-09-10
    # timestamp predates the real host's boot time, which would otherwise
    # read as a stale/reused pid from before the last reboot.
    armer_dir = artifact(tmp_path, "20260910120000", os.getpid())
    (armer_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "name": "holdarmer--code",
                "run_started_at": datetime.now(UTC).isoformat(),
            }
        )
    )
    waiter = artifact(tmp_path, "20260910120600", 606)
    agent_meta = {"name": "target.agent--code"}

    def claim() -> str:
        return "started"

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=4),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict(
            "os.environ",
            {
                "SASE_HOME": str(tmp_path / ".sase"),
                "SASE_ARTIFACTS_DIR": str(armer_dir),
            },
        ),
    ):
        result = arm_agent_hold(
            names=["target.agent--code"], scope="project", ttl_seconds=60.0
        )
        armer_key = result.record["armer"]["key"]

        blocked, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            agent_meta=agent_meta,
            claim=claim,
        )
        assert blocked is None
        assert parked

        assert release_agent_hold(armer_key)

        admitted, parked_again = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            agent_meta=agent_meta,
            claim=claim,
        )

    assert admitted == "started"
    assert not parked_again
    assert not (waiter / "waiting.json").exists()
