"""Assertion-style hijack lock-order traces for latch and spawn admission."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import latch, ledger
from sase.agent.hijack._stop_models import HijackTarget
from sase.agent.hijack.locks import (
    HIJACK_LOCK_ORDER,
    _state,
    acquire_hijack_lock,
    record_lock_hold,
)
from sase.agent.hijack.spawn_guard import (
    latch_guard_from_predecessor,
    spawn_admission,
)


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


def _target(
    artifacts: Path,
    *,
    name: str = "agent.1",
    pid: int = 42,
    identity: str = "boot:123",
    session: str = "session-1",
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
        agent_session=session,
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


def _subject(target: HijackTarget) -> SimpleNamespace:
    return SimpleNamespace(
        target=target,
        selected=SimpleNamespace(settled=False, process_alive=True),
        occupant_name=target.name,
        session=SimpleNamespace(base_name=target.agent_session),
        is_remote=False,
        is_bulk=False,
        is_named_proc=False,
        is_clan_container=False,
    )


def _start_lock_trace() -> None:
    _state.tracing = True
    _state.held = []
    _state.events = []


def _stop_lock_trace() -> list[tuple[str, str]]:
    events = list(getattr(_state, "events", []))
    _state.tracing = False
    _state.held = []
    _state.events = []
    return events


def _lock_trace_events() -> list[tuple[str, str]]:
    return list(getattr(_state, "events", []))


def _install_subjects(
    monkeypatch: pytest.MonkeyPatch,
    *subjects: SimpleNamespace,
) -> None:
    values = iter(subjects)
    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_hijack_subject",
        lambda _name, *, deps=None: next(values, subjects[-1]),
    )
    monkeypatch.setattr(latch, "_owner_identity", lambda target: target.test_identity)


def test_lock_order_names_match_parent_contract() -> None:
    assert HIJACK_LOCK_ORDER == (
        "adoption",
        "gate_lane",
        "monitor_lane",
        "gate_followup",
        "target_index",
        "apply",
        "record",
        "patch_lock",
    )


def test_tracing_rejects_target_index_inside_patch_lock(tmp_path: Path) -> None:
    _start_lock_trace()
    try:
        with pytest.raises(AssertionError, match="lock order violation"):
            with record_lock_hold("patch_lock"):
                with acquire_hijack_lock("target_index", tmp_path / "idx.lock"):
                    pass
    finally:
        _stop_lock_trace()


def test_tracing_allows_record_then_target_index_terminal_cleanup(
    tmp_path: Path,
) -> None:
    _start_lock_trace()
    try:
        with acquire_hijack_lock("record", tmp_path / "rec.lock"):
            with acquire_hijack_lock("target_index", tmp_path / "idx.lock"):
                pass
        events = _lock_trace_events()
    finally:
        _stop_lock_trace()
    assert ("acquire", "record") in events
    assert ("acquire", "target_index") in events


def test_request_apply_cancel_and_callback_traces(
    latch_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    del latch_store
    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    monkeypatch.setattr(latch, "pin_claim", lambda _target: True)
    monkeypatch.setattr(
        latch, "apply_latched_settlement", lambda *_args, **_kwargs: None
    )
    monkeypatch.setattr(
        latch,
        "collect_and_attach_evidence",
        lambda hijack_id, _target, *, deps, existing_snapshots: (
            ledger.load_record(hijack_id),
            None,
            None,
        ),
    )
    monkeypatch.setattr(
        latch.core,
        "hijack_latch_force_eligibility",
        lambda *_args: {"eligible": True},
    )

    callback_guard = latch_guard_from_predecessor(
        project_file=target.project_file,
        session_or_agent=target.agent_session,
        artifacts_dir=target.artifacts_dir,
        member=target.name,
    )
    _start_lock_trace()
    try:
        with spawn_admission(callback_guard, boundary="spawn_callback"):
            pass
        callback = [
            name for action, name in _lock_trace_events() if action == "acquire"
        ]
        requested = latch.request_latch(target.name)
        assert requested["verdict"] == "pending"
        registration = [
            name for action, name in _lock_trace_events() if action == "acquire"
        ]
        applied = latch.apply_latch_at_boundary(
            str(requested["target_key"]),
            "staged_adoption",
            "handoff",
            target=target,
        )
        assert applied["verdict"] == "applied"
        application = [
            name for action, name in _lock_trace_events() if action == "acquire"
        ]
    finally:
        _stop_lock_trace()

    assert callback[:2] == ["target_index", "patch_lock"]
    assert "target_index" in registration
    assert "record" in registration
    assert "apply" in application
    assert "patch_lock" in application

    other = _target(
        tmp_path / "other",
        name="agent.2",
        pid=99,
        identity="boot:999",
        session="session-2",
    )
    _install_subjects(monkeypatch, _subject(other))
    _start_lock_trace()
    try:
        pending = latch.request_latch(other.name)
        cancelled = latch.cancel_latch(str(pending["target_key"]))
        assert cancelled["verdict"] == "cancelled"
        cleanup = list(_lock_trace_events())
    finally:
        _stop_lock_trace()
    acquired = [name for action, name in cleanup if action == "acquire"]
    assert "record" in acquired
    assert "target_index" in acquired
