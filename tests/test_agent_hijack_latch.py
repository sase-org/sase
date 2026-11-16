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
    monkeypatch.setattr(latch, "_owner_identity", lambda target: target.test_identity)


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
    monkeypatch.setattr(latch, "_owner_identity", lambda _target: None)
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
