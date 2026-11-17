"""Shared fixtures and builders for agent hijack latch tests."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import core, ledger
from sase.agent.hijack import _latch_apply as latch_apply
from sase.agent.hijack import _latch_common as latch_common
from sase.agent.hijack import _latch_force as latch_force
from sase.agent.hijack import _latch_request as latch_request
from sase.agent.hijack._stop_models import HijackTarget


def advance_record(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    updated = dict(record)
    name = str(event.get("event") or "")
    transitions = {
        ("requested", "latch"): "latched",
        ("latched", "apply_latch"): "stopping",
        ("stopping", "confirmed_stop"): "held",
        ("latched", "cancel_latch"): "cancelled",
        ("latched", "moot_latch"): "finished_first",
    }
    next_state = transitions.get((str(record.get("state") or ""), name))
    if next_state is None:
        raise ValueError(f"illegal transition {record.get('state')} + {name}")
    updated["state"] = next_state
    updated["revision"] = int(record.get("revision") or 0) + 1
    updated["updated_at"] = event.get("at")
    if name == "latch":
        updated["owner_pid"] = event.get("owner_pid")
        updated["owner_identity"] = event.get("owner_identity")
        updated["latched_at"] = event.get("latched_at")
    elif name == "apply_latch":
        updated["applied_at"] = event.get("at")
        updated["boundary"] = event.get("boundary")
        updated["boundary_outcome"] = event.get("boundary_outcome")
        updated["suppressed_followup"] = event.get("suppressed_followup")
        updated["forced"] = bool(event.get("forced"))
    elif name == "moot_latch":
        updated["boundary"] = event.get("boundary")
        updated["boundary_outcome"] = event.get("boundary_outcome")
        updated["suppressed_followup"] = event.get("suppressed_followup")
    elif name == "confirmed_stop":
        updated["error"] = None
    return updated


def observe_record(record: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
    identity_matches = (
        record.get("target_key") == facts.get("target_key")
        and record.get("agent_name") == facts.get("member")
        and record.get("artifacts_dir") == facts.get("artifacts_dir")
        and record.get("owner_pid") == facts.get("owner_pid")
        and record.get("owner_identity") == facts.get("owner_identity")
    )
    if not identity_matches:
        verdict = "ownership_uncertain"
    else:
        verdict = {
            "latched": "pending",
            "stopping": "applied",
            "held": "applied",
            "cancelled": "cancelled",
            "finished_first": "moot",
        }.get(str(record.get("state") or ""), "no_latch")
    return {
        "verdict": verdict,
        "code": verdict,
        "message": verdict,
        "hijack_id": record.get("hijack_id"),
        "target_key": facts.get("target_key"),
        "boundary": facts.get("boundary"),
        "record": record,
    }


@pytest.fixture(name="latch_store")
def shared_latch_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "_hijack_ledger_root", lambda: tmp_path / "ledger")
    monkeypatch.setattr(ledger, "agent_hijack_wire_schema_version", lambda: 1)
    monkeypatch.setattr(ledger, "advance_agent_hijack_record", advance_record)
    monkeypatch.setattr(core, "agent_hijack_latch_wire_schema_version", lambda: 1)
    monkeypatch.setattr(core, "agent_hijack_latch_observe", observe_record)
    return tmp_path / "ledger"


def make_target(
    artifacts: Path,
    *,
    name: str = "agent.1",
    pid: int = 42,
    identity: str = "boot:123",
) -> HijackTarget:
    artifacts.mkdir(parents=True, exist_ok=True)
    target = HijackTarget(
        name=name,
        artifacts_dir=str(artifacts),
        project_name="sample",
        project_file="/tmp/sample.sase",
        artifacts_timestamp="20261116000100",
        is_home=False,
        pid=pid,
        claim_pid=pid,
        claim_pinned=False,
        cl_name="sample-patch",
        workflow="agent",
        workspace_num=4,
        workspace_dir="/tmp/workspace-4",
        status="RUNNING",
        lifecycle_phase="finalizing",
        is_monitor_turn=False,
        is_gate_turn=False,
        gate_state=None,
        agent_session="session-1",
        capabilities=["hijack"],
        model_alias="large",
        model_alias_trail=[],
        model_origin="prompt",
        provider="codex",
        model="gpt-6",
        effort="high",
        run_started_at=10.0,
        done_outcome=None,
        done_recovery=None,
    )
    target.test_identity = identity
    return target


def make_subject(
    target: HijackTarget,
    *,
    settled: bool = False,
    process_alive: bool = True,
    monitor_followup_pending: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        target=target,
        selected=SimpleNamespace(
            settled=settled and not monitor_followup_pending,
            process_alive=process_alive,
            monitor_followup_pending=monitor_followup_pending,
        ),
        occupant_name=target.name,
        session=SimpleNamespace(base_name=target.agent_session),
        is_remote=False,
        is_bulk=False,
        is_named_proc=False,
        is_clan_container=False,
    )


def install_subjects(
    monkeypatch: pytest.MonkeyPatch,
    *subjects: SimpleNamespace,
) -> None:
    values = iter(subjects)
    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_hijack_subject",
        lambda _name, *, deps=None: next(values, subjects[-1]),
    )

    def identity_for(target: HijackTarget) -> str:
        return target.test_identity

    monkeypatch.setattr(latch_common, "owner_identity_for", identity_for)
    monkeypatch.setattr(latch_force, "owner_identity_for", identity_for)
    monkeypatch.setattr(latch_request, "owner_identity_for", identity_for)
    monkeypatch.setattr(latch_apply, "owner_identity_for", identity_for)
