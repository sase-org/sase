"""Staged-handoff ownership coverage for the stranded-work collector.

Proves the staged fields ride the pinned Rust reducer: a valid staged plan
record, a held receipt, and malformed staged state all own the bead through
``handoff``, while a lone ``adopted`` receipt does not. Adopted-and-delivered
stages no longer own: the successor owns through its own session member when
live, and cold members strand.
"""

from __future__ import annotations

import json
from pathlib import Path

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_FILENAME,
    acquire_adoption_lock,
    build_monitor_staged_record,
    build_plan_staged_record,
    write_adoption_receipt,
    write_staged_successor_locked,
)
from sase.bead.stranded import load_stranded_report
from sase.bead.stranded_facts import collect_stranded_work_input
from sase.core.agent_scan_wire import DoneMarkerWire
from tests._stranded_collector_helpers import (
    PROJECT,
    bead_facts,
    phase,
    record,
    wire_collector,
)

_NOW = 1_700_000_000.0
_STAGED_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
_OTHER_STAGED_ID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"


def _dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "artifacts" / name
    path.mkdir(parents=True)
    return path


def _write_plan_record(artifact: Path) -> None:
    payload = build_plan_staged_record(
        plan_file=str(artifact / "plan.md"),
        original_file=str(artifact / "scratch.md"),
        dirty_obligations_at_stage=[],
        staged_id=_STAGED_ID,
    )
    (artifact / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_monitor_record(artifact: Path) -> None:
    payload = build_monitor_staged_record(
        payload={"monitor_id": "monitor-1"},
        dirty_obligations_at_stage=[],
        staged_id=_STAGED_ID,
    )
    (artifact / STAGED_HANDOFF_FILENAME).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _write_receipt(
    artifact: Path,
    outcome: str,
    reason: str | None = None,
    refs: dict[str, object] | None = None,
    staged_id: str = _STAGED_ID,
) -> None:
    receipt: dict[str, object] = {
        "staged_id": staged_id,
        "adopted_at": "2026-10-28T12:02:00Z",
        "outcome": outcome,
    }
    if reason is not None:
        receipt["reason"] = reason
    if refs is not None:
        receipt["refs"] = refs
    write_adoption_receipt(receipt, artifacts_dir=str(artifact))  # type: ignore[arg-type]


def _write_successor(artifact: Path, delivery_state: str, child: Path) -> None:
    successor = {
        "agent_name": "sase-1.2--1",
        "role_suffix": "--1",
        "artifacts_dir": str(child),
        "artifacts_timestamp": child.name,
        "launch_timestamp": child.name,
        "launch_identity": f"{_STAGED_ID}:{child.name}",
        "prompt_ref": str(artifact / "prompt.md"),
        "prompt_digest": "digest",
        "project_name": PROJECT,
        "project_file": "/tmp/demo/demo.sase",
        "origin_artifacts_timestamp": artifact.name,
        "cl_name": "sase-1.2",
        "workspace_dir": str(artifact.parent),
        "workspace_num": 1,
        "is_home_mode": False,
        "relationships": {},
        "continuation_refs": {},
        "loop_state": {},
    }
    with acquire_adoption_lock(artifact):
        write_staged_successor_locked(
            {
                "schema_version": 1,
                "staged_id": _STAGED_ID,
                "kind": "plan",
                "origin_artifacts_dir": str(artifact),
                "delivery_state": delivery_state,
                "successor": successor,
            },
            artifacts_dir=artifact,
        )


def _done_records(artifact: Path):
    return [
        record(
            artifact,
            name="sase-1.2",
            session="sase-1.2",
            done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 5),
        )
    ]


def _old_done_records(artifact: Path):
    return [
        record(
            artifact,
            name="sase-1.2",
            session="sase-1.2",
            done=DoneMarkerWire(outcome="completed", finished_at=_NOW - 3600),
        )
    ]


def _verdict(tmp_path: Path):
    report = load_stranded_report(PROJECT, now=_NOW)
    return next(item for item in report.report.verdicts if item.bead_id == "sase-1.2")


def test_valid_staged_plan_record_is_owned_through_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_plan_record(artifact)
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_handoff"] == "plan"
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned"
    assert verdict.reason == "handoff"


def test_held_receipt_alone_is_owned_through_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_receipt(artifact, "handoff_not_adopted", reason="no finalizer settlement")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_receipt_outcome"] == "handoff_not_adopted"
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned"
    assert verdict.reason == "handoff"


def test_malformed_staged_record_is_owned_through_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    (artifact / STAGED_HANDOFF_FILENAME).write_text("{}", encoding="utf-8")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_handoff"] == "malformed"
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned"
    assert verdict.reason == "handoff"


def test_adopted_receipt_alone_is_not_owned_through_handoff(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_receipt(artifact, "adopted")
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_receipt_outcome"] == "adopted"
    verdict = _verdict(tmp_path)
    assert not (verdict.state == "owned" and verdict.reason == "handoff")


def test_delivered_monitor_stage_is_stranded_not_owned(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_monitor_record(artifact)
    _write_receipt(
        artifact,
        "adopted",
        refs={"member_artifacts_dir": str(artifact / "member")},
    )
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _old_done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_handoff"] == "monitor"
    assert member["staged_receipt_outcome"] == "adopted"
    assert member["staged_delivered"] is True
    verdict = _verdict(tmp_path)
    assert verdict.state == "stranded"
    assert verdict.reason != "handoff"


def test_delivered_plan_gate_stage_is_stranded_not_owned(
    monkeypatch, tmp_path: Path
) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_plan_record(artifact)
    _write_receipt(
        artifact,
        "adopted",
        refs={"plan_gate_artifacts_dir": str(artifact / "gate")},
    )
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _old_done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_delivered"] is True
    verdict = _verdict(tmp_path)
    assert verdict.state == "stranded"
    assert verdict.reason != "handoff"


def test_plan_successor_pending_or_absent_stays_owned(
    monkeypatch, tmp_path: Path
) -> None:
    for delivery_state in ["created", "prepared"]:
        artifact = _dir(tmp_path, f"sase-1.2-{delivery_state}")
        child = _dir(tmp_path, f"sase-1.2-child-{delivery_state}")
        _write_plan_record(artifact)
        _write_receipt(
            artifact,
            "adopted",
            refs={"successor_artifacts_dir": str(child)},
        )
        _write_successor(artifact, delivery_state, child)
        wire_collector(
            monkeypatch,
            tmp_path,
            [phase("sase-1.2", assignee="sase-1.2")],
            _old_done_records(artifact),
        )
        member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
            "members"
        ][0]
        assert member["staged_delivered"] is False, delivery_state
        verdict = _verdict(tmp_path)
        assert verdict.state == "owned", delivery_state
        assert verdict.reason == "handoff", delivery_state
    artifact = _dir(tmp_path, "sase-1.2-absent")
    child = _dir(tmp_path, "sase-1.2-child-absent")
    _write_plan_record(artifact)
    _write_receipt(
        artifact,
        "adopted",
        refs={"successor_artifacts_dir": str(child)},
    )
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _old_done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_delivered"] is False
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned"
    assert verdict.reason == "handoff"


def test_plan_successor_delivered_states_are_stranded(
    monkeypatch, tmp_path: Path
) -> None:
    for delivery_state in ["submitted", "started", "terminal"]:
        artifact = _dir(tmp_path, f"sase-1.2-{delivery_state}")
        child = _dir(tmp_path, f"sase-1.2-child-{delivery_state}")
        _write_plan_record(artifact)
        _write_receipt(
            artifact,
            "adopted",
            refs={"successor_artifacts_dir": str(child)},
        )
        _write_successor(artifact, delivery_state, child)
        wire_collector(
            monkeypatch,
            tmp_path,
            [phase("sase-1.2", assignee="sase-1.2")],
            _old_done_records(artifact),
        )
        member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
            "members"
        ][0]
        assert member["staged_delivered"] is True, delivery_state
        verdict = _verdict(tmp_path)
        assert verdict.state == "stranded", delivery_state
        assert verdict.reason != "handoff", delivery_state


def test_mismatched_receipt_stays_owned(monkeypatch, tmp_path: Path) -> None:
    artifact = _dir(tmp_path, "sase-1.2")
    _write_plan_record(artifact)
    _write_receipt(
        artifact,
        "adopted",
        refs={"member_artifacts_dir": str(artifact / "member")},
        staged_id=_OTHER_STAGED_ID,
    )
    wire_collector(
        monkeypatch,
        tmp_path,
        [phase("sase-1.2", assignee="sase-1.2")],
        _old_done_records(artifact),
    )
    member = bead_facts(collect_stranded_work_input(PROJECT, now=_NOW), "sase-1.2")[
        "members"
    ][0]
    assert member["staged_delivered"] is False
    verdict = _verdict(tmp_path)
    assert verdict.state == "owned"
    assert verdict.reason == "handoff"
