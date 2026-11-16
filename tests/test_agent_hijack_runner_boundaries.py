"""Runner-boundary latch enforcement: staged, in-process, retry, and run end."""

from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import latch, ledger
from sase.agent.hijack._stop_models import HijackTarget
from sase.agent.hijack import runner_boundaries as bounds
from sase.agent.hijack.spawn_guard import HijackLatchedError


def _advance(record: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
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


def _observe(record: dict[str, Any], facts: dict[str, Any]) -> dict[str, Any]:
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


@pytest.fixture
def latch_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(ledger, "_hijack_ledger_root", lambda: tmp_path / "ledger")
    monkeypatch.setattr(ledger, "agent_hijack_wire_schema_version", lambda: 1)
    monkeypatch.setattr(ledger, "advance_agent_hijack_record", _advance)
    monkeypatch.setattr(latch.core, "agent_hijack_latch_wire_schema_version", lambda: 1)
    monkeypatch.setattr(latch.core, "agent_hijack_latch_observe", _observe)
    return tmp_path / "ledger"


def _write_meta(
    artifacts: Path,
    *,
    name: str = "agent.1",
    session: str = "session-1",
    project_file: str = "/tmp/sample.sase",
    workflow_name: str | None = "agent",
) -> dict[str, Any]:
    from sase.core.process_identity import process_identity_token

    pid = os.getpid()
    artifacts.mkdir(parents=True, exist_ok=True)
    meta = {
        "name": name,
        "agent_session": session,
        "project_file": project_file,
        "project_name": "sample",
        "pid": pid,
        "process_identity": process_identity_token(pid),
        "workspace_num": 4,
        "workspace_dir": "/tmp/workspace-4",
        "cl_name": "sample-patch",
        "runner_capabilities": ["hijack"],
    }
    if workflow_name is not None:
        meta["workflow_name"] = workflow_name
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def _target_for(
    artifacts: Path,
    meta: dict[str, Any],
) -> HijackTarget:
    return HijackTarget(
        name=str(meta["name"]),
        artifacts_dir=str(artifacts),
        project_name="sample",
        project_file=str(meta["project_file"]),
        artifacts_timestamp=artifacts.name,
        is_home=False,
        pid=int(meta["pid"]),
        claim_pid=int(meta["pid"]),
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
        agent_session=str(meta["agent_session"]),
        capabilities=["hijack"],
        model_alias=None,
        model_alias_trail=[],
        model_origin="prompt",
        provider="codex",
        model="gpt-6",
        effort=None,
        run_started_at=10.0,
        done_outcome=None,
        done_recovery=None,
    )


def _install_subject(
    monkeypatch: pytest.MonkeyPatch, target: HijackTarget, identity: str
) -> None:
    subject = SimpleNamespace(
        target=target,
        selected=SimpleNamespace(settled=False, process_alive=True),
        occupant_name=target.name,
        session=SimpleNamespace(base_name=target.agent_session),
        is_remote=False,
        is_bulk=False,
        is_named_proc=False,
        is_clan_container=False,
    )
    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_hijack_subject",
        lambda _name, *, deps=None: subject,
    )
    monkeypatch.setattr(latch, "owner_identity_for", lambda _t: identity)


def test_runner_target_recovers_workflow_from_exact_claim_when_meta_omits_it(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.process_identity import process_identity_token

    artifacts = tmp_path / "20261116130000"
    project_file = tmp_path / "sample.sase"
    meta = _write_meta(
        artifacts,
        project_file=str(project_file),
        workflow_name=None,
    )
    project_file.write_text(
        "WORKSPACE_DIR: /tmp\nNAME: sample\nRUNNING:\n"
        f"  #4 | {os.getpid()} | agent | sample-patch | {artifacts.name}\n",
        encoding="utf-8",
    )
    target = _target_for(artifacts, meta)
    identity = process_identity_token(os.getpid())
    _install_subject(monkeypatch, target, identity)

    requested = latch.request_latch(target.name)
    assert requested["verdict"] == "pending", requested

    runner_target = bounds._build_runner_target(str(artifacts))
    assert runner_target is not None
    assert runner_target.workflow == "agent"
    assert runner_target.claim_pid == os.getpid()


def test_staged_adoption_applies_once_and_replays_same_id(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.process_identity import process_identity_token

    member = tmp_path / "member-a"
    meta = _write_meta(member)
    target = _target_for(member, meta)
    identity = process_identity_token(os.getpid())
    _install_subject(monkeypatch, target, identity)
    requested = latch.request_latch(target.name)
    assert requested["verdict"] == "pending"

    monkeypatch.setattr(latch, "pin_claim", lambda _t: True)
    monkeypatch.setattr(latch, "apply_latched_settlement", lambda _t, _hid: None)

    def _attach(
        hijack_id: str,
        _target: HijackTarget,
        *,
        deps: Any,
        existing_snapshots: list[dict[str, Any]],
    ) -> tuple[Any, Any, Any]:
        return ledger.load_record(hijack_id), None, None

    monkeypatch.setattr(latch, "collect_and_attach_evidence", _attach)

    with pytest.raises(HijackLatchedError) as first:
        bounds.enforce_staged_adoption_latch(str(member), "staged-1", "pipe")
    assert first.value.hijack_id == requested["hijack_id"]

    record = ledger.load_record(str(requested["hijack_id"]))
    assert record is not None
    assert record["state"] == "held"
    assert record["suppressed_followup"] == {
        "kind": "pipe",
        "ref": str(member / ".sase_handoff_staged.json"),
    }

    with pytest.raises(HijackLatchedError) as second:
        bounds.enforce_staged_adoption_latch(str(member), "staged-1", "pipe")
    assert second.value.hijack_id == requested["hijack_id"]
    assert len(ledger.list_active_records()) == 1


def test_inprocess_successor_suppresses_without_extra_successor(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.process_identity import process_identity_token

    member = tmp_path / "member-b"
    meta = _write_meta(member, name="agent.2", session="session-2")
    target = _target_for(member, meta)
    identity = process_identity_token(os.getpid())
    _install_subject(monkeypatch, target, identity)
    requested = latch.request_latch(target.name)
    assert requested["verdict"] == "pending"

    monkeypatch.setattr(latch, "pin_claim", lambda _t: True)
    monkeypatch.setattr(latch, "apply_latched_settlement", lambda _t, _hid: None)

    def _attach(
        hijack_id: str,
        _target: HijackTarget,
        *,
        deps: Any,
        existing_snapshots: list[dict[str, Any]],
    ) -> tuple[Any, Any, Any]:
        return ledger.load_record(hijack_id), None, None

    monkeypatch.setattr(latch, "collect_and_attach_evidence", _attach)

    with pytest.raises(HijackLatchedError):
        bounds.enforce_inprocess_successor_latch(str(member), prompt="follow up please")
    record = ledger.load_record(str(requested["hijack_id"]))
    assert record is not None
    assert record["suppressed_followup"] == {
        "kind": "inprocess",
        "ref": str(member / ".sase_suppressed_inprocess_prompt.md"),
    }
    assert (member / ".sase_suppressed_inprocess_prompt.md").read_text(
        encoding="utf-8"
    ) == "follow up please"


def test_run_end_moot_keeps_real_outcome_and_retry_refuses_applied(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.core.process_identity import process_identity_token

    member = tmp_path / "member-c"
    meta = _write_meta(member, name="agent.3", session="session-3")
    target = _target_for(member, meta)
    identity = process_identity_token(os.getpid())
    _install_subject(monkeypatch, target, identity)
    requested = latch.request_latch(target.name)
    mooted = bounds.moot_runner_latch_at_run_end(str(member), "completed")
    assert mooted["verdict"] == "moot"
    assert mooted["record"]["boundary_outcome"] == "completed"
    assert ledger.find_active_record_by_target_key(str(requested["target_key"])) is None

    member2 = tmp_path / "member-d"
    meta2 = _write_meta(member2, name="agent.4", session="session-4")
    target2 = _target_for(member2, meta2)
    _install_subject(monkeypatch, target2, identity)
    requested2 = latch.request_latch(target2.name)
    monkeypatch.setattr(latch, "pin_claim", lambda _t: True)
    monkeypatch.setattr(latch, "apply_latched_settlement", lambda _t, _hid: None)

    def _attach(
        hijack_id: str,
        _target: HijackTarget,
        *,
        deps: Any,
        existing_snapshots: list[dict[str, Any]],
    ) -> tuple[Any, Any, Any]:
        return ledger.load_record(hijack_id), None, None

    monkeypatch.setattr(latch, "collect_and_attach_evidence", _attach)
    with pytest.raises(HijackLatchedError):
        bounds.enforce_staged_adoption_latch(str(member2), "staged-9", "plan")
    with pytest.raises(HijackLatchedError):
        bounds.check_retry_latch(str(member2))
    assert requested2["hijack_id"] is not None
