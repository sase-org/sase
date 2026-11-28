"""Failed-origin inactive settlement: host wiring end to end.

Covers the ``inactive-stage-host`` phase: the Rust inactive-stage policy
reaches the stranded collector, admission, lane, owner, and reconciler
paths; a never-started monitor stage settles idempotently once its origin
has failed; and later turns are no longer blocked by the dead stage while
every recovery record survives.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Any

import pytest

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    build_monitor_staged_record,
    build_questions_staged_record,
    write_adoption_receipt,
)
from sase.bead import _stranded_facts_collect as collect
from sase.bead import _stranded_facts_snapshot as snapshot
from sase.bead.model import BeadCompletionFailure, Status
from sase.bead.stranded import load_stranded_report
from sase.bead.stranded_facts import collect_stranded_work_input
from sase.core.agent_scan_wire import (
    AgentSessionTurnWire,
    DoneMarkerWire,
)
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    epic,
    phase,
    record,
    wire_collector,
)

_NOW = 1_700_000_000.0
_STAGED_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
_OTHER_STAGED_ID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"
_MONITOR_ID = "monitor-1"
_FAILED_AT = _NOW - 3600.0


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def _write_origin_meta(artifact: Path, name: str, outcome: str = "failed") -> None:
    (artifact / "agent_meta.json").write_text(
        json.dumps({"name": name, "agent_session": name}), encoding="utf-8"
    )
    (artifact / "done.json").write_text(
        json.dumps({"outcome": outcome, "finished_at": _FAILED_AT}),
        encoding="utf-8",
    )


def _write_monitor_stage(artifact: Path, staged_id: str = _STAGED_ID) -> None:
    payload = build_monitor_staged_record(
        payload={"monitor_id": _MONITOR_ID},
        dirty_obligations_at_stage=[],
        staged_id=staged_id,
    )
    (artifact / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_held_receipt(artifact: Path, staged_id: str = _STAGED_ID) -> None:
    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "handoff_not_adopted",
            "reason": "no finalizer settlement",
        },
        artifacts_dir=str(artifact),
    )


def _write_adopted_receipt(artifact: Path, staged_id: str = _STAGED_ID) -> None:
    write_adoption_receipt(
        {
            "staged_id": staged_id,
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "adopted",
            "refs": {},
        },
        artifacts_dir=str(artifact),
    )


def _failed_origin_records(artifact: Path, name: str = "sase-1.2"):
    return [
        record(
            artifact,
            name=name,
            session=name,
            done=DoneMarkerWire(outcome="failed", finished_at=_FAILED_AT),
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
            kind="monitor", id=_MONITOR_ID, state=turn_state
        ),
    )
    return dataclasses.replace(base, agent_meta=meta)


def _collect(
    monkeypatch: Any, tmp_path: Path, issues: list, records: list
) -> dict[str, Any]:
    wire_collector(monkeypatch, tmp_path, issues, records)
    return collect_stranded_work_input(PROJECT, now=_NOW)


def _verdict(tmp_path: Path, bead_id: str = "sase-1.2"):
    report = load_stranded_report(PROJECT, now=_NOW)
    return next(item for item in report.report.verdicts if item.bead_id == bead_id)


def test_failed_origin_monitor_stage_reports_origin_failed(
    monkeypatch, tmp_path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
    payload = _collect(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _failed_origin_records(artifact),
    )
    member = bead_facts(payload, "sase-1.2")["members"][0]
    assert member["inactive_stage"]["origin_outcome"] == "failed"
    assert member["inactive_stage"]["stage_validity"] == "valid"
    assert member["inactive_stage"]["stage_id"] == _STAGED_ID
    assert member["inactive_stage"]["receipt_outcome"] == "held"


def test_failed_origin_strands_and_blocks_waiting_ancestor(
    monkeypatch, tmp_path
) -> None:
    from sase.core.agent_scan_wire import WaitingMarkerWire

    land_dir = _dir(tmp_path, "sase-1-land")
    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
    records = _failed_origin_records(artifact)
    records.append(
        _monitor_member_record(_dir(tmp_path, "sase-1.2--mon"), session="sase-1.2")
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
    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
    member_dir = _dir(tmp_path, "sase-1.2--mon")
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

    member_dir = _dir(tmp_path, "sase-1.2--mon")
    facts = member_facts(
        _monitor_member_record(member_dir, session="sase-1.2"),
    )
    assert facts["process_live"] is False


def test_started_monitor_stays_process_live(tmp_path) -> None:
    from sase.bead._stranded_facts_members import member_facts

    member_dir = _dir(tmp_path, "sase-1.2--mon")
    facts = member_facts(
        _monitor_member_record(
            member_dir, session="sase-1.2", pid=4242, turn_state="running"
        ),
    )
    assert facts["process_live"] is True


def test_receipt_only_failed_origin_is_inactive_but_not_eligible(
    monkeypatch, tmp_path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
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
    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
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
    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    payload = _collect(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _failed_origin_records(artifact),
    )
    member = bead_facts(payload, "sase-1.2")["members"][0]
    assert member["inactive_stage"]["origin_outcome"] == "unknown"


def test_adopted_stage_never_settles(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_adopted_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
    settlement = settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is False
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False


def test_settlement_is_idempotent_and_keeps_recovery_evidence(
    monkeypatch, tmp_path
) -> None:
    from sase.agent._staged_handoff_inactive import read_inactive_settlement
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
    first = settle_inactive_staged_handoff(str(artifact))
    assert first.settled is True
    assert first.already_settled is False
    assert first.staged_id == _STAGED_ID
    assert first.reason == "origin_failed"
    marker = read_inactive_settlement(str(artifact))
    assert marker is not None
    assert marker["staged_id"] == _STAGED_ID
    # Recovery evidence survives settlement.
    assert (artifact / STAGED_HANDOFF_FILENAME).is_file()
    assert (artifact / ".sase_handoff_adopted.json").is_file()
    second = settle_inactive_staged_handoff(str(artifact))
    assert second.settled is True
    assert second.already_settled is True
    assert second.staged_id == _STAGED_ID


def test_settlement_requires_failed_terminal_evidence(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    (artifact / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    settlement = settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is False
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False


def test_submitted_proc_blocks_settlement(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")

    class _Proc:
        pass

    monkeypatch.setattr("sase.procs.store.get_proc", lambda _pid: _Proc())
    settlement = settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is False
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False


def test_unreadable_proc_store_blocks_settlement(monkeypatch, tmp_path) -> None:
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")

    def _boom(_pid: str):
        raise OSError("proc store unreadable")

    monkeypatch.setattr("sase.procs.store.get_proc", _boom)
    settlement = settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is False
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False


def test_settled_origin_releases_admission_slot(monkeypatch, tmp_path) -> None:
    from sase.agent._staged_handoff_admission import occupying_handoff_names
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
    assert occupying_handoff_names(str(artifact)) == (STAGED_HANDOFF_FILENAME,)
    settlement = settle_inactive_staged_handoff(str(artifact))
    assert settlement.settled is True
    assert occupying_handoff_names(str(artifact)) == ()


def test_replacement_stage_is_not_suppressed_by_old_settlement(
    monkeypatch, tmp_path
) -> None:
    from sase.agent._staged_handoff_admission import occupying_handoff_names
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
    assert settle_inactive_staged_handoff(str(artifact)).settled is True
    _write_monitor_stage(artifact, staged_id=_OTHER_STAGED_ID)
    assert occupying_handoff_names(str(artifact)) == (STAGED_HANDOFF_FILENAME,)


def _patch_owner_home(monkeypatch, home: Path) -> None:
    monkeypatch.setattr("sase.monitor.staged_owner.sase_home", lambda: home)
    monkeypatch.setattr("sase.core.paths.sase_home", lambda: home)


def _write_member_launch(
    member: Path, origin: Path, staged_id: str = _STAGED_ID, **claim: Any
) -> None:
    context = {"starter_artifacts_dir": str(origin)}
    context.update(claim)
    payload = {
        "staged_id": staged_id,
        "monitor_id": _MONITOR_ID,
        "workspace": {"claim_context": context},
    }
    (member / "staged_monitor_launch.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_owner_index(member: Path, origin: Path, staged_id: str = _STAGED_ID) -> None:
    from sase.monitor.staged_owner import write_staged_owner_index

    write_staged_owner_index(
        _MONITOR_ID,
        staged_id=staged_id,
        artifacts_dir=str(member),
        starter_artifacts_dir=str(origin),
    )


def _lane_monitor(member: Path):
    from sase.monitor.models import MonitorRecord

    return MonitorRecord(
        monitor_id=_MONITOR_ID,
        member_agent_name="sase-1.2--mon",
        lane="sase-1.2",
        project_name=PROJECT,
        artifacts_dir=str(member),
        timestamp="20261022120000",
        command="just check",
        cwd=str(member),
        reason="verify",
        label="just check",
        start_status="STAGED",
        stop_status="STAGED",
        timeout_seconds=2700.0,
        tail_lines=200,
        monitor_state="staged",
    )


def test_live_origin_monitor_blocks_lane_and_holds_owner(monkeypatch, tmp_path) -> None:
    from sase.monitor.store_lane import _blocks_lane_start
    from sase.tool.owner import _pending_staged_monitor_owner

    home = tmp_path / ".sase"
    _patch_owner_home(monkeypatch, home)
    origin = _dir(tmp_path, "sase-1.2")
    member = _dir(tmp_path, "sase-1.2--mon")
    _write_monitor_stage(origin)
    _write_held_receipt(origin)
    (origin / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    _write_member_launch(member, origin)
    _write_owner_index(member, origin)
    assert _blocks_lane_start(_lane_monitor(member)) is True
    assert _pending_staged_monitor_owner(_MONITOR_ID) is True


def test_failed_origin_releases_lane_and_pending_owner(monkeypatch, tmp_path) -> None:
    from sase.monitor.store_lane import _blocks_lane_start
    from sase.tool.owner import _pending_staged_monitor_owner

    home = tmp_path / ".sase"
    _patch_owner_home(monkeypatch, home)
    origin = _dir(tmp_path, "sase-1.2")
    member = _dir(tmp_path, "sase-1.2--mon")
    _write_monitor_stage(origin)
    _write_held_receipt(origin)
    _write_origin_meta(origin, "sase-1.2")
    _write_member_launch(member, origin)
    _write_owner_index(member, origin)
    assert _blocks_lane_start(_lane_monitor(member)) is False
    assert _pending_staged_monitor_owner(_MONITOR_ID) is False


def test_settlement_removes_pending_owner_row_and_keeps_lane_clear(
    monkeypatch, tmp_path
) -> None:
    from sase.monitor.staged_owner import read_staged_owner_index
    from sase.monitor.store_lane import _blocks_lane_start
    from sase.tool.owner import _pending_staged_monitor_owner
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    _patch_owner_home(monkeypatch, home)
    origin = _dir(tmp_path, "sase-1.2")
    member = _dir(tmp_path, "sase-1.2--mon")
    _write_monitor_stage(origin)
    _write_held_receipt(origin)
    _write_origin_meta(origin, "sase-1.2")
    _write_member_launch(member, origin)
    _write_owner_index(member, origin)
    settlement = settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is True
    assert settlement.cleared_pending_owner is True
    assert read_staged_owner_index(_MONITOR_ID) is None
    assert _pending_staged_monitor_owner(_MONITOR_ID) is False
    # The lane record survives, but the frozen launch payload still proves
    # the stage is inactive, so the dead monitor keeps the lane clear.
    assert _blocks_lane_start(_lane_monitor(member)) is False


def test_fresh_turn_stages_questions_after_settlement(monkeypatch, tmp_path) -> None:
    from sase.agent._staged_handoff_admission import occupying_handoff_names
    from sase.agent.staged_handoff import write_staged_handoff
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    home = tmp_path / ".sase"
    _patch_owner_home(monkeypatch, home)
    monkeypatch.setenv("SASE_AGENT", "1")
    origin = _dir(tmp_path, "sase-1.2")
    member = _dir(tmp_path, "sase-1.2--mon")
    _write_monitor_stage(origin)
    _write_held_receipt(origin)
    _write_origin_meta(origin, "sase-1.2")
    _write_member_launch(member, origin)
    _write_owner_index(member, origin)
    assert settle_inactive_staged_handoff(str(origin)).settled is True
    fresh = _dir(tmp_path, "sase-1.2--retry")
    staged = build_questions_staged_record(
        questions=[{"question": "ship it?"}],
        dirty_obligations_at_stage=[],
    )
    path = write_staged_handoff(staged, artifacts_dir=str(fresh))
    assert path.is_file()
    assert occupying_handoff_names(str(fresh)) == (STAGED_HANDOFF_FILENAME,)


def test_readopt_invalidates_settlement_exactly_once(monkeypatch, tmp_path) -> None:
    from sase.agent._staged_handoff_inactive import read_inactive_settlement
    from sase.axe._run_agent_exec_staged_recovery_shared import write_adopted_locked
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    origin = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(origin)
    _write_held_receipt(origin)
    _write_origin_meta(origin, "sase-1.2")
    assert settle_inactive_staged_handoff(str(origin)).settled is True
    assert read_inactive_settlement(str(origin)) is not None
    write_adopted_locked(staged_id=_STAGED_ID, refs={}, artifacts_dir=str(origin))
    assert read_inactive_settlement(str(origin)) is None
    # A racing hold for the adopted stage cannot overwrite the receipt.
    from sase.agent._staged_handoff_store import StagedHandoffError
    from sase.agent.staged_handoff import read_adoption_receipt

    with pytest.raises(StagedHandoffError):
        _write_held_receipt(origin)
    assert read_adoption_receipt(str(origin))["outcome"] == "adopted"


def test_settlement_settles_reserved_tool_run_as_never_executed(
    tmp_path, monkeypatch
) -> None:
    import os

    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )
    from sase.core.tool_run import (
        tool_run_reserve_staged_join,
        tool_run_show,
    )
    from sase.tool.handoff import reserve_handoff_run
    from sase.tool.argv import resolve_run_argv

    origin = _dir(tmp_path, "sase-1.2")
    member = _dir(tmp_path, "sase-1.2--mon")
    _write_monitor_stage(origin)
    _write_held_receipt(origin)
    _write_origin_meta(origin, "sase-1.2")
    reservation = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-inactive-contracts",
        agent="sase-1.2--mon",
        starter={
            "agent": "sase-1.2--mon",
            "pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        },
    )
    assert reservation.reserved, reservation.error
    run_id = reservation.run_id
    _patch_owner_home(monkeypatch, tmp_path / ".sase")
    _write_member_launch(member, origin, tool_run_id=run_id)
    _write_owner_index(member, origin)
    settlement = settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is True
    assert settlement.settled_tool_run_id == run_id
    shown = tool_run_show(run_id)["run"]
    assert shown["state"] == "signaled"
    assert shown["terminal_cause"] == "stop_requested"
    assert any(
        "command was not run" in str(line) for line in (shown.get("diagnostics") or [])
    )


def test_settlement_releases_staged_join_reservation(tmp_path, monkeypatch) -> None:
    import os

    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )
    from sase.core.tool_run import (
        tool_run_reserve_staged_join,
        tool_run_show,
    )
    from sase.tool.handoff import reserve_handoff_run
    from sase.tool.argv import resolve_run_argv

    origin = _dir(tmp_path, "sase-1.2")
    member = _dir(tmp_path, "sase-1.2--mon")
    _write_monitor_stage(origin)
    _write_held_receipt(origin)
    _write_origin_meta(origin, "sase-1.2")
    reservation = reserve_handoff_run(
        resolve_run_argv(["--", "true"]),
        owner_kind="proc",
        owner_id="proc-inactive-contracts",
        agent="sase-1.2--mon",
        starter={
            "agent": "sase-1.2--mon",
            "pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        },
    )
    assert reservation.reserved, reservation.error
    run_id = reservation.run_id
    tool_run_reserve_staged_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "staged_id": _STAGED_ID,
            "monitor_id": _MONITOR_ID,
            "agent": "sase-1.2--mon",
        }
    )
    _patch_owner_home(monkeypatch, tmp_path / ".sase")
    _write_member_launch(member, origin, tool_run_id=run_id, join_mode="staged")
    (member / "agent_meta.json").write_text(
        json.dumps({"monitor_id": _MONITOR_ID, "monitor_staged_id": _STAGED_ID}),
        encoding="utf-8",
    )
    _write_owner_index(member, origin)
    settlement = settle_inactive_staged_handoff(str(origin))
    assert settlement.settled is True
    assert settlement.released_join is True
    assert settlement.settled_tool_run_id is None
    assert tool_run_show(run_id)["run"]["state"] not in {"signaled"}


def _reconcile_origin(tmp_path: Path, monkeypatch, stamp: str) -> Path:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / ".sase/projects/proj/artifacts/ace-run" / stamp
    artifacts.mkdir(parents=True)
    payload = build_monitor_staged_record(
        payload={"monitor_id": _MONITOR_ID},
        dirty_obligations_at_stage=[],
        staged_id=_STAGED_ID,
    )
    (artifacts / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )
    write_adoption_receipt(
        {
            "staged_id": _STAGED_ID,
            "adopted_at": "2026-10-28T12:02:00Z",
            "outcome": "handoff_not_adopted",
            "reason": "no finalizer settlement",
        },
        artifacts_dir=str(artifacts),
    )
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "sase-1.2", "agent_session": "sase-1.2"}),
        encoding="utf-8",
    )
    (artifacts / "done.json").write_text('{"outcome":"failed"}')
    return artifacts


def test_reconcile_settles_failed_origin_and_stays_quiet(tmp_path, monkeypatch) -> None:
    from sase.axe.staged_handoff_reconcile import reconcile_staged_handoffs

    artifacts = _reconcile_origin(tmp_path, monkeypatch, "20261028120000")
    notified: list[str] = []
    monkeypatch.setattr(
        "sase.notifications.senders.notify_workflow_complete",
        lambda **kwargs: notified.append(kwargs.get("sender", "")),
    )
    first = reconcile_staged_handoffs()
    assert first.adopted == 0
    assert first.held == 1
    assert not first.errors, first.errors
    marker = json.loads(
        (artifacts / ".sase_handoff_settled_inactive.json").read_text(encoding="utf-8")
    )
    assert marker["staged_id"] == _STAGED_ID
    assert marker["reason"] == "origin_failed"
    # No command ran; every recovery record survives.
    from sase.procs.store import get_proc

    assert get_proc(_MONITOR_ID) is None
    assert (artifacts / STAGED_HANDOFF_FILENAME).is_file()
    assert (artifacts / ".sase_handoff_adopted.json").is_file()
    second = reconcile_staged_handoffs()
    assert second.adopted == 0
    assert second.held == 1
    assert not second.errors, second.errors
    assert notified == []


def test_busy_adoption_lock_skips_settlement_without_blocking(
    tmp_path,
) -> None:
    from sase.agent.staged_handoff import acquire_adoption_lock
    from sase.axe.run_agent_exec_staged_inactive import (
        settle_inactive_staged_handoff,
    )

    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_stage(artifact)
    _write_held_receipt(artifact)
    _write_origin_meta(artifact, "sase-1.2")
    with acquire_adoption_lock(artifact):
        skipped = settle_inactive_staged_handoff(str(artifact), blocking=False)
    assert skipped.settled is False
    assert "another caller owns" in skipped.reason
    assert (artifact / ".sase_handoff_settled_inactive.json").exists() is False
    assert settle_inactive_staged_handoff(str(artifact)).settled is True


def test_malformed_stage_never_settles(monkeypatch, tmp_path) -> None:
    from sase.agent._staged_handoff_inactive import observe_inactive_stage_request
    from sase.core.staged_handoff import evaluate_inactive_staged_handoff

    artifact = _dir(tmp_path, "sase-1.2")
    (artifact / STAGED_HANDOFF_FILENAME).write_text("{broken", encoding="utf-8")
    _write_origin_meta(artifact, "sase-1.2")
    request = observe_inactive_stage_request(str(artifact))
    assert request is not None
    assert request["stage_validity"] == "malformed"
    decision = evaluate_inactive_staged_handoff(request)
    assert decision["pending_owner"] is True
    assert decision["settlement_eligible"] is False
