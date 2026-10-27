"""List-holder parity: ``sase agent list -j`` reads Rust accounting, not status."""

from __future__ import annotations

from pytest import MonkeyPatch

from sase.agent.running_listing import RunningAgentListing, _running_from_snapshot
from sase.agents.cli_list import _agent_to_json
from sase.config.runner_limit_override import EffectiveRunnerLimitSnapshot
from sase.core.agent_scan_wire import (
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)
from sase.core.runner_slots import machine_capacity_report_from_records
from sase.integrations.agent_list_entries import agent_list_entries
from tests._agent_list_entries_helpers import agent
from tests._runner_slots_helpers import _always_live, _record


def _screenshot_records():
    return [
        _record("/worker-a", name="worker-a", run_started=True),
        _record("/worker-b", name="worker-b", run_started=True),
        _record("/worker-c", name="worker-c", run_started=True),
        _record(
            "/verify-a",
            name="verify-a--mon",
            agent_session="verify-a",
            agent_session_role="monitor",
            monitor_id="verify-a-turn",
            queue_weight=1.0,
            run_started=True,
            start_status="TESTING",
        ),
        _record(
            "/verify-b",
            name="verify-b--mon",
            agent_session="verify-b",
            agent_session_role="monitor",
            monitor_id="verify-b-turn",
            queue_weight=1.0,
            run_started=True,
            start_status="TESTING",
        ),
        _record(
            "/cutover",
            name="cutover--mon",
            agent_session="cutover",
            agent_session_role="monitor",
            monitor_id="cutover-turn",
            queue_weight=0.0,
            queue_weight_explicit=True,
            run_started=True,
            start_status="WAITING CUTOVER",
        ),
    ]


def _scan(records) -> AgentArtifactScanWire:
    return AgentArtifactScanWire(
        schema_version=4,
        projects_root="/tmp/projects",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=records,
    )


def test_screenshot_shape_list_holders_match_report_holding_entries(
    monkeypatch: MonkeyPatch,
) -> None:
    records = _screenshot_records()
    snapshot = _scan(records)
    monkeypatch.setattr(
        "sase.agent.running_listing.is_process_alive",
        lambda *_args: True,
    )
    infos = _running_from_snapshot(snapshot)
    listing = RunningAgentListing(infos, artifact_snapshot=snapshot)
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries.list_running_agents",
        lambda: listing,
    )
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries.get_max_running_agents",
        lambda: 8,
    )

    entries = agent_list_entries()
    report = machine_capacity_report_from_records(
        records,
        _always_live,
        now=2_000.0,
        token="tok",
        scanned_at=2_000.0,
        scan_current=True,
        limit=EffectiveRunnerLimitSnapshot(
            configured_limit=10,
            temporary_override=None,
            captured_at=2_000.0,
        ),
    )

    holding = [entry for entry in report.accounting if entry.get("state") == "holding"]
    assert report.occupied_capacity == 5.0
    assert report.occupied_lanes == 6
    assert len(holding) == 6
    assert {info.name: info.holds_runner_slot for info in infos} == {
        "worker-a": True,
        "worker-b": True,
        "worker-c": True,
        "verify-a--mon": True,
        "verify-b--mon": True,
        "cutover--mon": True,
    }
    assert {
        entry.artifacts_dir for entry in entries if entry.capacity_state == "holding"
    } == {item["artifact_dir"] for item in holding}
    by_name = {entry.name: entry for entry in entries}
    assert by_name["verify-a--mon"].status == "TESTING"
    assert by_name["verify-b--mon"].status == "TESTING"
    assert by_name["cutover--mon"].status == "WAITING CUTOVER"
    holders = by_name["worker-a"].wait.runner_slot_holders
    assert set(holders) == {
        "worker-a",
        "worker-b",
        "worker-c",
        "verify-a--mon",
        "verify-b--mon",
        "cutover--mon",
    }
    assert by_name["worker-a"].wait.runner_slots_in_use == report.occupied_lanes
    cutover = _agent_to_json(by_name["cutover--mon"])
    assert cutover["capacity_state"] == "holding"
    assert cutover["capacity_charged"] == 0.0
    assert cutover["capacity_reason"] == "explicit_zero_weight"
    assert cutover["status"] == "WAITING CUTOVER"
    verify = _agent_to_json(by_name["verify-a--mon"])
    assert verify["capacity_state"] == "holding"
    assert verify["capacity_charged"] == 1.0
    assert verify["capacity_reason"] is None
    assert verify["status"] == "TESTING"


def test_hand_built_running_info_is_not_a_holder_without_explicit_flag(
    monkeypatch: MonkeyPatch,
) -> None:
    running = agent(name="running", status="RUNNING")
    waiter = agent(
        name="waiter",
        status="WAITING",
        artifacts_dir="/tmp/sase/artifacts/ace-run/20260717120002",
        holds_runner_slot=False,
    )
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries.list_running_agents",
        lambda: [running, waiter],
    )
    monkeypatch.setattr(
        "sase.integrations.agent_list_entries._children_by_parent_timestamp",
        lambda **_kwargs: {},
    )

    entries = agent_list_entries()
    by_name = {entry.name: entry for entry in entries}

    assert by_name["waiter"].wait.runner_slot_holders == ()
    assert by_name["waiter"].wait.runner_slots_in_use == 0
    assert by_name["running"].capacity_state is None
