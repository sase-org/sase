"""Runtime tests for runner-slot capacity limits and queue admission."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.core.agent_scan_wire import AgentArtifactRecordWire

from tests._runner_slot_fixtures import artifact, record


def test_live_config_raise_releases_queued_agent(tmp_path: Path) -> None:
    running = artifact(tmp_path, "20260712120000", 100)
    waiter = artifact(tmp_path, "20260712120001", 101)
    config_cap = 1
    started = False

    def scan() -> list[AgentArtifactRecordWire]:
        return [record(running, started=True), record(waiter, started=started)]

    def claim() -> str:
        nonlocal started
        started = True
        return "started"

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_slots,
            "get_max_running_agents",
            side_effect=lambda: config_cap,
        ),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        first, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            directive_priority=7,
            directive_queue_weight=0.25,
            directive_queue_weight_explicit=True,
            claim=claim,
        )
        assert first is None
        assert parked
        marker = json.loads((waiter / "waiting.json").read_text())
        assert marker["queue_capacity"] == 0
        assert marker["queue_capacity_explicit"] is False
        assert marker["wait_priority"] == 7
        assert marker["wait_priority_explicit"] is True
        assert marker["queue_weight"] == 0.25
        assert marker["queue_weight_explicit"] is True

        config_cap = 2
        second, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            directive_priority=7,
            directive_queue_weight=1.0,
            directive_queue_weight_explicit=False,
            claim=claim,
        )

    assert second == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_fractional_agents_fill_capacity_exactly_and_block_next(
    tmp_path: Path,
) -> None:
    agents = [
        artifact(
            tmp_path,
            f"2026091012000{index}",
            100 + index,
            queue_weight=0.25,
            queue_weight_explicit=True,
        )
        for index in range(5)
    ]
    started: set[str] = set()

    def scan() -> list[AgentArtifactRecordWire]:
        return [record(path, started=str(path) in started) for path in agents]

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        for path in agents[:4]:
            result, parked = run_agent_wait_slots._try_claim_runner_slot(
                artifacts_dir=str(path),
                cl_name="cl",
                timestamp=path.name,
                directive_threshold=None,
                directive_queue_weight=0.25,
                directive_queue_weight_explicit=True,
                claim=lambda path=path: started.add(str(path)) or "started",
            )
            assert result == "started"
            assert not parked

        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(agents[4]),
            cl_name="cl",
            timestamp=agents[4].name,
            directive_threshold=None,
            directive_queue_weight=0.25,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
        )

    assert result is None
    assert parked
    assert len(started) == 4
    marker = json.loads((agents[4] / "waiting.json").read_text())
    assert marker["queue_weight"] == 0.25
    assert marker["queue_capacity_explicit"] is False


def test_heavy_weight_cannot_start_with_only_one_unit_free(tmp_path: Path) -> None:
    running = artifact(tmp_path, "20260910121000", 100, queue_weight=1.0)
    heavy = artifact(
        tmp_path,
        "20260910121001",
        101,
        queue_weight=2.0,
        queue_weight_explicit=True,
    )

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(running, started=True), record(heavy)],
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
            artifacts_dir=str(heavy),
            cl_name="cl",
            timestamp=heavy.name,
            directive_threshold=None,
            directive_queue_weight=2.0,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
        )

    assert result is None
    assert parked
    marker = json.loads((heavy / "waiting.json").read_text())
    assert marker["queue_weight"] == 2.0
    assert marker["queue_capacity_explicit"] is False


def test_high_explicit_queue_capacity_can_bypass_global_limit(
    tmp_path: Path,
) -> None:
    running = artifact(tmp_path, "20260910122000", 100)
    waiter = artifact(tmp_path, "20260910122001", 101)

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(running, started=True), record(waiter)],
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
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
            directive_threshold=99,
            directive_queue_weight=0.25,
            directive_queue_weight_explicit=True,
            claim=lambda: "started",
        )

    assert result == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_lighter_waiter_can_pass_non_fitting_heavy_waiter(
    tmp_path: Path,
) -> None:
    occupied = artifact(tmp_path, "20260910123000", 100, queue_weight=0.75)
    heavy = artifact(
        tmp_path,
        "20260910123001",
        101,
        queue_weight=0.5,
        queue_weight_explicit=True,
    )
    light = artifact(
        tmp_path,
        "20260910123002",
        102,
        queue_weight=0.25,
        queue_weight_explicit=True,
    )
    light_started = False

    def scan() -> list[AgentArtifactRecordWire]:
        return [
            record(occupied, started=True),
            record(heavy),
            record(light, started=light_started),
        ]

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        heavy_result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(heavy),
            cl_name="cl",
            timestamp=heavy.name,
            directive_threshold=None,
            directive_queue_weight=0.5,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
        )
        assert heavy_result is None
        assert parked

        light_result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(light),
            cl_name="cl",
            timestamp=light.name,
            directive_threshold=None,
            directive_queue_weight=0.25,
            directive_queue_weight_explicit=True,
            claim=lambda: "started",
        )

    assert light_result == "started"
    assert not parked
    assert (heavy / "waiting.json").exists()
    assert not (light / "waiting.json").exists()


def test_running_monitor_occupying_last_slot_parks_new_launch(tmp_path: Path) -> None:
    monitor = artifact(
        tmp_path,
        "20260812120000",
        500,
        agent_family_role="monitor",
        monitor_id="mon-1",
    )
    newcomer = artifact(tmp_path, "20260812120001", 501)

    def scan() -> list[AgentArtifactRecordWire]:
        return [record(monitor), record(newcomer)]

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        result, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(newcomer),
            cl_name="cl",
            timestamp=newcomer.name,
            directive_threshold=None,
            claim=lambda: "started",
        )

    assert result is None
    assert parked
    marker = json.loads((newcomer / "waiting.json").read_text())
    assert marker["slot_requested_at"]


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
            "active_agent_hold_records",
            return_value=[hold],
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


def test_real_agent_hold_parks_a_waiter_and_release_resumes_it(
    tmp_path: Path,
) -> None:
    """A hold armed through the real store blocks admission until released.

    Unlike ``test_active_holds_are_threaded_into_locked_admission`` (which
    mocks ``active_agent_hold_records`` to prove the wiring), this exercises
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


def test_releasing_monitor_admits_the_parked_waiter(tmp_path: Path) -> None:
    monitor = artifact(
        tmp_path,
        "20260812120000",
        500,
        agent_family_role="monitor",
        monitor_id="mon-1",
    )
    waiter = artifact(tmp_path, "20260812120001", 501)
    monitor_alive = True

    def scan() -> list[AgentArtifactRecordWire]:
        records = [record(waiter)]
        if monitor_alive:
            records.insert(0, record(monitor))
        return records

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        first, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "started",
        )
        assert first is None
        assert parked

        monitor_alive = False
        second, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=None,
            claim=lambda: "started",
        )

    assert second == "started"
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_blocked_claim_without_parking_leaves_no_waiting_marker(
    tmp_path: Path,
) -> None:
    running = artifact(tmp_path, "20260910121000", 100, queue_weight=1.0)
    blocked = artifact(
        tmp_path,
        "20260910121001",
        101,
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    leftover = {
        "cl_name": "stale",
        "timestamp": blocked.name,
        "queue_capacity": 0,
        "queue_capacity_explicit": False,
        "slot_requested_at": "2026-09-10T12:10:01+00:00",
    }
    (blocked / "waiting.json").write_text(json.dumps(leftover), encoding="utf-8")

    with (
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            return_value=[record(running, started=True), record(blocked)],
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
            artifacts_dir=str(blocked),
            cl_name="cl",
            timestamp=blocked.name,
            directive_threshold=None,
            directive_queue_weight=2.0,
            directive_queue_weight_explicit=True,
            claim=lambda: "unexpected",
            park_on_block=False,
        )

    assert result is None
    assert not parked
    assert not (blocked / "waiting.json").exists()
    meta = json.loads((blocked / "agent_meta.json").read_text())
    assert "runner_claim_owner_key" not in meta


def test_unavailable_limit_without_parking_leaves_no_waiting_marker(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260910121002", 102)

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(
            run_agent_wait_slots,
            "get_max_running_agents",
            side_effect=RuntimeError("limit unavailable"),
        ),
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
            claim=lambda: "unexpected",
            park_on_block=False,
        )

    assert result is None
    assert not parked
    assert not (waiter / "waiting.json").exists()


def test_try_claim_without_parking_still_acquires_when_capacity_is_free(
    tmp_path: Path,
) -> None:
    waiter = artifact(tmp_path, "20260910121003", 103)

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", return_value=[]
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        started = run_agent_wait_slots.try_claim_runner_slot_without_parking(
            str(waiter),
            "cl",
            waiter.name,
            {"pid": 103},
            wait_runners=None,
            claim=lambda: "started",
        )

    assert started == "started"
    assert not (waiter / "waiting.json").exists()
    meta = json.loads((waiter / "agent_meta.json").read_text())
    assert meta["runner_claim_owner_key"] == waiter.name
