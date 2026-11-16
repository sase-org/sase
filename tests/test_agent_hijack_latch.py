"""Target-indexed latch request, cancellation, moot, and replay contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from sase.agent.hijack import ledger
from sase.agent.hijack._stop_models import HijackTarget
from sase.agent.hijack import latch
from sase.agent.hijack._stop_claim import apply_latched_settlement
from sase.running_field import WorkspaceClaim


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


def _target(
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


def _install_subjects(
    monkeypatch: pytest.MonkeyPatch,
    *subjects: SimpleNamespace,
) -> None:
    values = iter(subjects)
    monkeypatch.setattr(
        "sase.agent.hijack.facts.resolve_hijack_subject",
        lambda _name, *, deps=None: next(values, subjects[-1]),
    )
    monkeypatch.setattr(
        latch, "owner_identity_for", lambda target: target.test_identity
    )


def test_request_deduplicates_by_target_and_rejects_recycled_occupant(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path / "member-a")
    _install_subjects(monkeypatch, _subject(target))
    first = latch.request_latch(target.name)
    assert first["verdict"] == "pending"
    assert first["record"]["owner_identity"] == "boot:123"
    assert first["record"]["provider"] == target.provider
    assert first["record"]["model"] == target.model
    assert first["record"]["effort"] == target.effort

    _install_subjects(monkeypatch, _subject(target))
    second = latch.request_latch(target.name)
    assert second["verdict"] == "pending"
    assert second["hijack_id"] == first["hijack_id"]
    assert len(ledger.list_active_records()) == 1

    replacement = _target(
        tmp_path / "member-b", name=target.name, pid=99, identity="boot:999"
    )
    _install_subjects(monkeypatch, _subject(replacement))
    changed = latch.request_latch(target.name)
    assert changed["verdict"] == "ownership_uncertain"
    assert changed["hijack_id"] == first["hijack_id"]
    assert len(ledger.list_active_records()) == 1


def test_second_resolution_change_releases_unwritten_reservation(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_target = _target(tmp_path / "member-a")
    changed_target = _target(
        tmp_path / "member-b", name="agent.2", pid=99, identity="boot:999"
    )
    _install_subjects(monkeypatch, _subject(first_target), _subject(changed_target))
    result = latch.request_latch(first_target.name)
    assert result["code"] == "occupant_changed"
    assert ledger.list_active_records() == []
    assert (
        ledger.find_active_record_by_target_key(
            ledger.target_key_for("/tmp/sample.sase", "session-1")
        )
        is None
    )


def test_cancel_and_moot_release_only_their_own_target_reservation(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    cancelled = latch.cancel_latch(
        str(requested["target_key"]), hijack_id=str(requested["hijack_id"])
    )
    assert cancelled["verdict"] == "cancelled"
    assert cancelled["record"]["state"] == "cancelled"
    assert ledger.find_active_record_by_target_key(str(requested["target_key"])) is None
    observed = latch.observe_hijack_latch(
        str(requested["target_key"]),
        "run_end",
        member=target.name,
        artifacts_dir=target.artifacts_dir,
        owner_pid=target.pid,
        owner_identity="boot:123",
        hijack_id=str(requested["hijack_id"]),
    )
    assert observed["verdict"] == "cancelled"

    target2 = _target(tmp_path / "member-2", name="agent.2")
    _install_subjects(monkeypatch, _subject(target2))
    requested2 = latch.request_latch(target2.name)
    monkeypatch.setattr(latch, "owner_identity_for", lambda _target: None)
    mooted = latch.moot_latch(
        str(requested2["target_key"]),
        "run_end",
        "completed",
        target=target2,
    )
    assert mooted["verdict"] == "moot"
    assert mooted["record"]["boundary_outcome"] == "completed"
    assert (
        ledger.find_active_record_by_target_key(str(requested2["target_key"])) is None
    )


def test_application_holds_claim_and_retries_snapshot_failure(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    pin_calls: list[int] = []
    settlement_calls: list[str] = []
    evidence_calls: list[list[dict[str, Any]]] = []
    evidence_results = iter(("snapshot failed", None))

    monkeypatch.setattr(
        latch, "pin_claim", lambda value: pin_calls.append(value.pid or 0) or True
    )
    monkeypatch.setattr(
        latch,
        "apply_latched_settlement",
        lambda _target, hijack_id: settlement_calls.append(hijack_id),
    )
    monkeypatch.setattr(
        latch.core,
        "hijack_latch_force_eligibility",
        lambda *_args: pytest.fail(
            "a force retry must not re-evaluate age after apply"
        ),
    )

    def attach_evidence(
        hijack_id: str,
        _target: HijackTarget,
        *,
        deps: Any,
        existing_snapshots: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, str | None, str | None]:
        evidence_calls.append(existing_snapshots)
        error = next(evidence_results)
        record = ledger.load_record(hijack_id)
        return record, None, error

    monkeypatch.setattr(latch, "collect_and_attach_evidence", attach_evidence)
    first = latch.apply_latch_at_boundary(
        str(requested["target_key"]),
        "staged_adoption",
        "handoff",
        target=target,
        suppressed_followup={"kind": "pipe", "ref": "/tmp/followup.json"},
    )
    assert first["verdict"] == "applied"
    assert first["code"] == "snapshot_pending"
    assert first["record"]["state"] == "stopping"
    assert first["record"]["boundary_outcome"] == "handoff"
    assert first["record"]["suppressed_followup"] == {
        "kind": "pipe",
        "ref": "/tmp/followup.json",
    }

    second = latch.apply_latch_at_boundary(
        str(requested["target_key"]),
        "staged_adoption",
        "handoff",
        target=target,
        forced=True,
    )
    assert second["verdict"] == "applied"
    assert second["record"]["state"] == "held"
    assert second["record"]["forced"] is False
    assert pin_calls == [42, 42]
    assert settlement_calls == [requested["hijack_id"], requested["hijack_id"]]
    assert evidence_calls == [[], []]


def test_cancel_race_winner_is_reported_without_releasing_application_custody(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    cancelled = latch.cancel_latch(str(requested["target_key"]))
    assert cancelled["verdict"] == "cancelled"
    applied = latch.apply_latch_at_boundary(
        str(requested["target_key"]),
        "run_end",
        "completed",
        target=target,
    )
    assert applied["verdict"] == "no_latch"
    assert ledger.load_record(str(requested["hijack_id"]))["state"] == "cancelled"


def test_force_refuses_before_timeout_without_signalling(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.hijack import _latch_force

    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    monkeypatch.setattr(
        latch.core,
        "hijack_latch_force_eligibility",
        lambda record, now: {
            "eligible": False,
            "code": "force_too_early",
            "message": "the pending latch is younger than 120 seconds",
            "age_seconds": 119,
            "threshold_seconds": 120,
        },
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.acquire_adoption_lock",
        lambda *_args, **_kwargs: _acquired_lock(),
    )
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_common.terminate_with_retry",
        lambda *_args, **_kwargs: pytest.fail("young latch must not signal"),
    )

    result = _latch_force.force_hijack_latch(str(requested["target_key"]))

    assert result["verdict"] == "refused"
    assert result["code"] == "force_too_early"
    assert result["next_action"].startswith("wait 1 more seconds")
    assert ledger.load_record(str(requested["hijack_id"]))["state"] == "latched"


def test_eligible_force_reuses_latch_id_and_persists_interruption_custody(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.hijack import _latch_force
    from sase.agent._user_kill_intent import hijack_intent_id, has_user_kill_intent

    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    target.claim_pinned = False
    termination_targets: list[HijackTarget] = []
    monkeypatch.setattr(
        latch.core,
        "hijack_latch_force_eligibility",
        lambda record, now: {
            "eligible": True,
            "age_seconds": 120,
            "threshold_seconds": 120,
        },
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.acquire_adoption_lock",
        lambda *_args, **_kwargs: _acquired_lock(),
    )
    monkeypatch.setattr(latch, "pin_claim", lambda _target: True)
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_common.terminate_with_retry",
        lambda value, **_kwargs: (
            termination_targets.append(value) or SimpleNamespace(success=True)
        ),
    )
    monkeypatch.setattr(
        latch,
        "complete_latch_application",
        lambda current, _target, **_kwargs: {
            "verdict": "applied",
            "record": current,
            "ready": True,
        },
    )

    result = _latch_force.force_hijack_latch(str(requested["target_key"]))

    record = ledger.load_record(str(requested["hijack_id"]))
    assert result["verdict"] == "applied"
    assert result["forced"] is True
    assert result["hijack_id"] == requested["hijack_id"]
    assert result["next_action"].startswith("inspect the recovery snapshot")
    assert record["state"] == "stopping"
    assert record["forced"] is True
    assert record["boundary"] == "forced_stop"
    assert record["boundary_outcome"] == "interrupted"
    assert len(termination_targets) == 1
    assert has_user_kill_intent(target.artifacts_dir)
    assert hijack_intent_id(target.artifacts_dir) == requested["hijack_id"]


def test_force_preserves_custody_when_transition_commit_result_is_uncertain(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.hijack import _latch_force
    from sase.agent._user_kill_intent import has_user_kill_intent

    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    monkeypatch.setattr(
        latch.core,
        "hijack_latch_force_eligibility",
        lambda *_args: {"eligible": True, "age_seconds": 120},
    )
    monkeypatch.setattr(
        "sase.agent.staged_handoff.acquire_adoption_lock",
        lambda *_args, **_kwargs: _acquired_lock(),
    )
    pin_calls: list[bool] = []
    monkeypatch.setattr(latch, "pin_claim", lambda _target: True)
    monkeypatch.setattr(latch, "unpin_claim", lambda _target: pin_calls.append(True))
    actual_advance = ledger.cas_advance_record

    def commit_then_raise(
        record: dict[str, Any], event: dict[str, Any]
    ) -> dict[str, Any]:
        actual_advance(record, event)
        raise OSError("simulated lost CAS response")

    monkeypatch.setattr(ledger, "cas_advance_record", commit_then_raise)
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_common.terminate_with_retry",
        lambda *_args, **_kwargs: pytest.fail("uncertain CAS must not signal"),
    )

    result = _latch_force.force_hijack_latch(str(requested["target_key"]))

    record = ledger.load_record(str(requested["hijack_id"]))
    assert result["code"] == "latch_transition_uncertain"
    assert record["state"] == "stopping"
    assert record["forced"] is True
    assert has_user_kill_intent(target.artifacts_dir)
    assert pin_calls == []


def test_force_rejects_a_stale_selected_id_and_cancelled_latch(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.hijack import _latch_force

    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    stale = _latch_force.force_hijack_latch(
        str(requested["target_key"]), hijack_id="hijack-old"
    )
    assert stale["code"] == "hijack_id_mismatch"

    cancelled = latch.cancel_latch(str(requested["target_key"]))
    assert cancelled["verdict"] == "cancelled"
    rejected = _latch_force.force_hijack_latch(
        str(requested["target_key"]), hijack_id=str(requested["hijack_id"])
    )
    assert rejected["code"] == "latch_cancelled"


def test_adopted_successor_moots_latch_after_claim_transfer(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.hijack import _latch_reconcile

    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    hijack_id = str(requested["hijack_id"])
    monkeypatch.setattr(
        _latch_reconcile,
        "_owner_observation",
        lambda _record: ({"lookup_succeeded": True, "pid": None}, "dead"),
    )
    monkeypatch.setattr(
        _latch_reconcile,
        "_successor_observation",
        lambda *_args: ({"kind": "launched", "name": "agent.2"}, None),
    )
    monkeypatch.setattr(
        _latch_reconcile, "_read_real_outcome", lambda _artifacts: "completed"
    )
    monkeypatch.setattr(
        latch.core,
        "hijack_latch_reconcile",
        lambda *_args: {"outcome": "moot_latch"},
    )
    monkeypatch.setattr(
        _latch_reconcile,
        "get_claimed_workspaces",
        lambda *_args: pytest.fail("mooting must not require the transferred claim"),
    )

    _latch_reconcile._reconcile_under_adoption_lock(
        hijack_id,
        str(requested["target_key"]),
        target.artifacts_dir,
        log_fn=None,
    )

    record = ledger.load_record(hijack_id)
    assert record["state"] == "finished_first"
    assert record["boundary_outcome"] == "completed"
    assert ledger.find_active_record_by_target_key(str(requested["target_key"])) is None


def test_stale_reconciliation_applies_dead_owner_once_and_finishes_evidence(
    latch_store: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.agent.hijack import _latch_reconcile
    from sase.agent import _user_kill_intent

    target = _target(tmp_path / "member")
    _install_subjects(monkeypatch, _subject(target))
    requested = latch.request_latch(target.name)
    hijack_id = str(requested["hijack_id"])
    claim = WorkspaceClaim(
        workspace_num=4,
        workflow="agent",
        cl_name="sample-patch",
        pid=42,
        artifacts_timestamp=Path(target.artifacts_dir).name,
        pinned=True,
    )
    termination_calls: list[int] = []
    settlement_calls: list[str] = []
    monkeypatch.setattr(
        _latch_reconcile,
        "_owner_observation",
        lambda _record: ({"lookup_succeeded": True, "pid": None}, "dead"),
    )
    monkeypatch.setattr(
        _latch_reconcile,
        "_successor_observation",
        lambda *_args: ({"kind": "absent"}, None),
    )
    monkeypatch.setattr(_latch_reconcile, "_read_real_outcome", lambda _artifacts: None)
    monkeypatch.setattr(
        latch.core,
        "hijack_latch_reconcile",
        lambda *_args: {"outcome": "apply_latch"},
    )
    monkeypatch.setattr(
        _latch_reconcile,
        "get_claimed_workspaces",
        lambda _project: [claim],
    )
    monkeypatch.setattr(latch, "pin_claim", lambda _target: True)
    monkeypatch.setattr(
        _user_kill_intent,
        "has_user_kill_intent",
        lambda _artifacts: False,
    )
    monkeypatch.setattr(
        _user_kill_intent,
        "write_user_kill_intent",
        lambda *_args, **_kwargs: Path(target.artifacts_dir) / "intent",
    )
    monkeypatch.setattr(
        "sase.agent.hijack._stop_orchestrator_common.terminate_with_retry",
        lambda value, **_kwargs: (
            termination_calls.append(value.pid or 0) or SimpleNamespace(success=True)
        ),
    )
    monkeypatch.setattr(
        latch,
        "apply_latched_settlement",
        lambda _target, operation_id: settlement_calls.append(operation_id),
    )
    monkeypatch.setattr(
        latch,
        "collect_and_attach_evidence",
        lambda operation_id, _target, **_kwargs: (
            ledger.load_record(operation_id),
            None,
            None,
        ),
    )

    for _ in range(2):
        _latch_reconcile._reconcile_under_adoption_lock(
            hijack_id,
            str(requested["target_key"]),
            target.artifacts_dir,
            log_fn=None,
        )

    record = ledger.load_record(hijack_id)
    assert record["state"] == "held"
    assert record["boundary"] == "owner_recovery"
    assert record["boundary_outcome"] == "interrupted"
    assert termination_calls == [42]
    assert settlement_calls == [hijack_id]


def _acquired_lock():
    from contextlib import contextmanager

    @contextmanager
    def _lock():
        yield True

    return _lock()


def test_latched_settlement_rewrites_only_the_matching_artifact_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _target(tmp_path / "member")
    done_path = Path(target.artifacts_dir) / "done.json"
    done_path.write_text(
        '{"project_file":"/tmp/sample.sase",'
        '"artifacts_timestamp":"20261116000100","outcome":"completed"}',
        encoding="utf-8",
    )
    written: list[dict[str, Any]] = []

    def write_marker(_artifacts_dir: str, marker: dict[str, Any]) -> str:
        written.append(marker)
        done_path.write_text(json.dumps(marker), encoding="utf-8")
        return str(done_path)

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_markers.write_done_marker_and_update_index",
        write_marker,
    )
    apply_latched_settlement(target, "hijack-1")
    assert written[0]["outcome"] == "hijacked"
    assert written[0]["recovery"]["hijack_id"] == "hijack-1"

    done_path.write_text(
        '{"project_file":"/tmp/other.sase",'
        '"artifacts_timestamp":"20261116000100","outcome":"completed"}',
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="different project or artifacts generation"):
        apply_latched_settlement(target, "hijack-2")
    assert len(written) == 1
