"""Stranded-collector and origin-reporting cases for inactive settlement."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

from sase.bead.stranded import load_stranded_report
from sase.bead.stranded_facts import collect_stranded_work_input
from sase.core.agent_scan_wire import (
    AgentSessionTurnWire,
    DoneMarkerWire,
)
from tests._staged_inactive_host_helpers import (
    FAILED_AT,
    MONITOR_ID,
    NOW,
    STAGED_ID,
    artifact_dir,
    write_held_receipt,
    write_monitor_stage,
    write_origin_meta,
)
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    epic,
    phase,
    record,
    wire_collector,
)


def _failed_origin_records(artifact: Path, name: str = "sase-1.2"):
    return [
        record(
            artifact,
            name=name,
            session=name,
            done=DoneMarkerWire(outcome="failed", finished_at=FAILED_AT),
        )
    ]


def _monitor_member_record(
    artifact: Path,
    *,
    name: str = "sase-1.2--mon",
    session: str = "sase-1.2",
    pid: int | None = None,
    run_started_at: str | None = None,
    turn_state: str = "staged",
    timestamp: str = "20231022120000",
) -> Any:
    base = record(
        artifact,
        name=name,
        session=session,
        pid=pid,
        run_started_at=run_started_at,
        timestamp=timestamp,
    )
    meta = dataclasses.replace(
        base.agent_meta,
        agent_session_role="monitor",
        agent_session_turn=AgentSessionTurnWire(
            kind="monitor", id=MONITOR_ID, state=turn_state
        ),
    )
    return dataclasses.replace(base, agent_meta=meta)


def _collect(
    monkeypatch: Any, tmp_path: Path, issues: list, records: list
) -> dict[str, Any]:
    wire_collector(monkeypatch, tmp_path, issues, records)
    return collect_stranded_work_input(PROJECT, now=NOW)


def _verdict(tmp_path: Path, bead_id: str = "sase-1.2"):
    report = load_stranded_report(PROJECT, now=NOW)
    return next(item for item in report.report.verdicts if item.bead_id == bead_id)


def test_failed_origin_monitor_stage_reports_origin_failed(
    monkeypatch, tmp_path
) -> None:
    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    payload = _collect(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _failed_origin_records(artifact),
    )
    member = bead_facts(payload, "sase-1.2")["members"][0]
    assert member["inactive_stage"]["origin_outcome"] == "failed"
    assert member["inactive_stage"]["stage_validity"] == "valid"
    assert member["inactive_stage"]["stage_id"] == STAGED_ID
    assert member["inactive_stage"]["receipt_outcome"] == "held"


def test_failed_origin_strands_and_blocks_waiting_ancestor(
    monkeypatch, tmp_path
) -> None:
    from sase.core.agent_scan_wire import WaitingMarkerWire

    land_dir = artifact_dir(tmp_path, "sase-1-land")
    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    records = _failed_origin_records(artifact)
    records.append(
        _monitor_member_record(
            artifact_dir(tmp_path, "sase-1.2--mon"), session="sase-1.2"
        )
    )
    records.append(
        record(
            land_dir,
            name="sase-1-land",
            session="sase-1-land",
            timestamp="20231022120000",
            waiting=WaitingMarkerWire(
                waiting_for=["phase"],
                wait_for_beads=["sase-1.2"],
                slot_requested_at="2023-10-22T12:00:00Z",
            ),
        )
    )
    _collect(
        monkeypatch,
        tmp_path,
        [
            epic("sase-1", assignee="sase-1-land"),
            phase("sase-1.2", assignee="sase-1.2", parent_id="sase-1"),
        ],
        records,
    )
    verdict = _verdict(tmp_path)
    assert verdict.state == "stranded", verdict
    assert verdict.reason == "failed", verdict
    assert "handoff" not in (verdict.reason or "")
    ancestor = _verdict(tmp_path, "sase-1")
    assert ancestor.state == "blocked", ancestor
    assert "sase-1.2" in ancestor.blocked_by


def test_member_order_does_not_change_stranded_verdict(monkeypatch, tmp_path) -> None:
    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    member_dir = artifact_dir(tmp_path, "sase-1.2--mon")
    origin_records = _failed_origin_records(artifact)
    monitor_record = _monitor_member_record(member_dir, session="sase-1.2")
    for ordered in (
        origin_records + [monitor_record],
        [monitor_record] + origin_records,
    ):
        _collect(
            monkeypatch,
            tmp_path,
            [phase("sase-1.2", assignee="sase-1.2")],
            list(ordered),
        )
        verdict = _verdict(tmp_path)
        assert verdict.state == "stranded", verdict
        assert verdict.reason == "failed", verdict


def test_unstarted_monitor_is_not_process_live(tmp_path) -> None:
    from sase.bead._stranded_facts_members import member_facts

    member_dir = artifact_dir(tmp_path, "sase-1.2--mon")
    facts = member_facts(
        _monitor_member_record(member_dir, session="sase-1.2"),
    )
    assert facts["process_live"] is False


def test_started_monitor_stays_process_live(tmp_path) -> None:
    from sase.bead._stranded_facts_members import member_facts

    member_dir = artifact_dir(tmp_path, "sase-1.2--mon")
    facts = member_facts(
        _monitor_member_record(
            member_dir, session="sase-1.2", pid=4242, turn_state="running"
        ),
    )
    assert facts["process_live"] is True


def test_receipt_only_failed_origin_is_inactive_but_not_eligible(
    monkeypatch, tmp_path
) -> None:
    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_held_receipt(artifact)
    write_origin_meta(artifact, "sase-1.2")
    payload = _collect(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _failed_origin_records(artifact),
    )
    member = bead_facts(payload, "sase-1.2")["members"][0]
    assert member["inactive_stage"]["stage_validity"] == "absent"
    assert member["inactive_stage"]["receipt_outcome"] == "held"
    verdict = _verdict(tmp_path)
    assert verdict.state == "stranded", verdict
    assert verdict.reason == "failed", verdict


def test_live_origin_keeps_pending_handoff_ownership(monkeypatch, tmp_path) -> None:
    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    (artifact / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    live = record(artifact, name="sase-1.2", session="sase-1.2")
    _collect(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        [live],
    )
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned", verdict
    assert verdict.reason == "handoff", verdict


def test_running_origin_without_terminal_marker_stays_pending(
    monkeypatch, tmp_path
) -> None:
    artifact = artifact_dir(tmp_path, "sase-1.2")
    write_monitor_stage(artifact)
    write_held_receipt(artifact)
    payload = _collect(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _failed_origin_records(artifact),
    )
    member = bead_facts(payload, "sase-1.2")["members"][0]
    assert member["inactive_stage"]["origin_outcome"] == "unknown"
