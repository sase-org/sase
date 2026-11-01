"""Host recovery service: one entry point for all staged-handoff kinds."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.staged_handoff import (
    read_adoption_receipt,
    write_adoption_receipt,
    write_staged_handoff,
    write_staged_handoff_response,
)
from sase.axe._run_agent_exec_staged_shared import StagedInlineContinuation
from sase.axe.run_agent_exec_staged import (
    STAGED_HANDOFF_ADOPTERS,
    recover_staged_handoff,
)
from tests._axe_run_agent_exec_helpers import make_exec_ctx
from sase.axe.run_agent_exec import LoopState

STAGED_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
OTHER_ID = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"


def _record(tmp_path: Path, kind: str = "plan") -> dict[str, object]:
    from sase.agent.staged_handoff import (
        build_gate_staged_record,
        build_monitor_staged_record,
        build_pipe_staged_record,
        build_plan_staged_record,
    )

    if kind == "gate":
        from sase.core.staged_handoff import build_gate_staged_payload

        payload = build_gate_staged_payload(
            {
                "request_id": "stage-1",
                "spec": {"request_id": "stage-1", "resources": []},
                "auto": {"decision": {}, "policy_block": {}, "auto_execute": False},
                "resources": [],
                "creator": {
                    "project": "proj",
                    "project_file": "/tmp/proj.sase",
                    "artifacts_dir": "/tmp/a",
                    "timestamp": "20261029T000000Z",
                    "agent": "agent-1",
                },
                "workspace_mode": "inherit",
            }
        )
        return build_gate_staged_record(
            staged_id=STAGED_ID,
            created_at="2026-10-28T12:00:00Z",
            payload=payload,
            successor_workspace="inherit",
            carry_allowed=True,
        )
    if kind == "monitor":
        return build_monitor_staged_record(
            staged_id=STAGED_ID,
            created_at="2026-10-28T12:00:00Z",
            payload={"monitor_id": "monitor-1"},
        )
    if kind == "pipe":
        return build_pipe_staged_record(
            payload={"prompt": "piped prompt", "reason": "hand off"},
            staged_id=STAGED_ID,
            created_at="2026-10-28T12:00:00Z",
        )
    return build_plan_staged_record(
        plan_file=str(tmp_path / "plan.md"),
        original_file=str(tmp_path / "scratch.md"),
        dirty_obligations_at_stage=[],
        staged_id=STAGED_ID,
        created_at="2026-10-28T12:00:00Z",
    )


def _write_meta(
    artifacts: Path, *, pid: int | None = None, name: str = "agent"
) -> None:
    meta: dict[str, object] = {
        "name": name,
        "workspace_dir": str(artifacts.parent),
        "finalizer_status": {
            "phase": "settled",
            "status": "success",
            "run_id": "controller-run-1",
            "plan_digest": "digest-1",
            "started_at": datetime(2026, 10, 28, 12, 1, tzinfo=UTC).timestamp(),
        },
    }
    if pid is not None:
        meta["pid"] = pid
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    (artifacts / "finalizer_result.json").write_text(
        json.dumps({"status": "success", "instances": []}), encoding="utf-8"
    )


def _continuation(tmp_path: Path, artifacts: Path):
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    state = LoopState(
        current_prompt="planner prompt",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="planner prompt",
    )
    return StagedInlineContinuation(ctx=ctx, state=state)


def _settle_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_facts.finalizer_settlement_refusal",
        lambda *_args, **_kwargs: None,
    )


def _patch_read_staged_successor(monkeypatch: pytest.MonkeyPatch, impl) -> None:
    for target in (
        "sase.axe.run_agent_exec_staged_recovery.read_staged_successor",
        "sase.axe.run_agent_exec_staged_recovery_facts.read_staged_successor",
        "sase.axe.run_agent_exec_staged_recovery_deliver.read_staged_successor",
    ):
        monkeypatch.setattr(target, impl)


def test_missing_stage_is_refused(tmp_path: Path) -> None:
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    result = recover_staged_handoff(str(artifacts), mode="explicit")
    assert not result.adopted and result.action == "refuse"
    assert "no staged handoff" in (result.reason or "")


def test_unknown_mode_is_refused(tmp_path: Path) -> None:
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    result = recover_staged_handoff(str(artifacts), mode="someday")
    assert result.action == "refuse" and "unknown recovery mode" in (
        result.reason or ""
    )


def test_mismatched_receipt_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    write_adoption_receipt(
        {
            "staged_id": OTHER_ID,
            "adopted_at": "2026-10-28T12:01:00Z",
            "outcome": "adopted",
            "refs": {},
        },
        artifacts_dir=str(artifacts),
    )
    _write_meta(artifacts)
    result = recover_staged_handoff(str(artifacts), mode="explicit")
    assert result.action == "refuse"
    assert "different stage" in (result.reason or "") or "unusable" in (
        result.reason or ""
    )


def test_killed_stage_is_refused(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    write_staged_handoff_response(STAGED_ID, "response", artifacts_dir=str(artifacts))
    _write_meta(artifacts)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent",
                "workspace_dir": str(tmp_path),
                "handoff_protocol": "killed",
                "finalizer_status": {
                    "phase": "settled",
                    "status": "success",
                    "run_id": "controller-run-1",
                    "plan_digest": "digest-1",
                    "started_at": datetime(2026, 10, 28, 12, 1, tzinfo=UTC).timestamp(),
                },
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "finalizer_result.json").write_text(
        json.dumps({"status": "success", "instances": []}), encoding="utf-8"
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.was_killed_or_discarded",
        lambda *_a, **_k: True,
    )
    _settle_ok(monkeypatch)
    result = recover_staged_handoff(str(artifacts), mode="explicit")
    assert result.action == "refuse"
    assert "kill" in (result.reason or "")


def test_held_settlement_stays_held_and_names_repair(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    write_staged_handoff_response(STAGED_ID, "response", artifacts_dir=str(artifacts))
    _write_meta(artifacts, pid=999999)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_facts.finalizer_settlement_refusal",
        lambda *_a, **_k: "finalizer instance 'commit' did not settle successfully",
    )
    result = recover_staged_handoff(str(artifacts), mode="explicit")
    assert not result.adopted and result.action == "hold"
    assert result.repair_action is not None and "commit" in result.repair_action
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "handoff_not_adopted"


def test_already_adopted_wins_without_rechecking_dirt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    write_adoption_receipt(
        {
            "staged_id": STAGED_ID,
            "adopted_at": "2026-10-28T12:01:00Z",
            "outcome": "adopted",
            "refs": {"loop_outcome": "completed"},
        },
        artifacts_dir=str(artifacts),
    )
    _write_meta(artifacts)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_facts.finalizer_settlement_refusal",
        lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("settlement must not be rechecked after adoption")
        ),
    )
    result = recover_staged_handoff(str(artifacts), mode="automatic")
    assert result.adopted and result.already_adopted


def test_live_runner_automatic_is_held(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    write_staged_handoff_response(STAGED_ID, "response", artifacts_dir=str(artifacts))
    _write_meta(artifacts)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner",
        lambda *_a, **_k: "alive",
    )
    _settle_ok(monkeypatch)
    result = recover_staged_handoff(str(artifacts), mode="automatic")
    assert not result.adopted and result.action == "hold"
    assert (
        "live" in (result.reason or "").lower()
        or "proven-dead" in (result.reason or "").lower()
    )


def test_gate_detached_adoption_reuses_request_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path, kind="gate"), artifacts_dir=str(artifacts))
    write_staged_handoff_response(STAGED_ID, "response", artifacts_dir=str(artifacts))
    _write_meta(artifacts, pid=999999)
    _settle_ok(monkeypatch)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner",
        lambda *_a, **_k: "dead",
    )

    import types

    calls: list[str] = []

    def fake_publish(payload, *, staged_id, artifacts_dir):
        calls.append(staged_id)
        record = types.SimpleNamespace(
            gate_id="gate-1",
            artifacts_dir=str(tmp_path / "member"),
            workspace_policy="inherit",
        )
        gate = types.SimpleNamespace(request_id="req-1", notification_id="note-1")
        return types.SimpleNamespace(record=record, gate=gate)

    monkeypatch.setattr("sase.gate_turn.publisher.publish_staged_gate", fake_publish)
    result = recover_staged_handoff(str(artifacts), mode="explicit")
    assert result.adopted and result.kind == "gate"
    assert result.destination is not None
    assert result.destination.get("gate_id") == "gate-1"
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "adopted"
    assert calls == [STAGED_ID]


def test_monitor_detached_adoption_reuses_member(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    member = tmp_path / "member"
    member.mkdir()
    write_staged_handoff(
        _record(tmp_path, kind="monitor"), artifacts_dir=str(artifacts)
    )
    write_staged_handoff_response(STAGED_ID, "response", artifacts_dir=str(artifacts))
    _write_meta(artifacts, pid=999999)
    _settle_ok(monkeypatch)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner",
        lambda *_a, **_k: "dead",
    )
    monkeypatch.setattr(
        "sase.monitor.staged_owner.read_staged_owner_index",
        lambda _monitor_id: {"staged_id": STAGED_ID, "artifacts_dir": str(member)},
    )

    class _LaunchRecord:
        monitor_id = "monitor-1"
        artifacts_dir = str(member)

    monkeypatch.setattr(
        "sase.monitor.start_stage_adopt.launch_from_persisted_payload",
        lambda _member_dir, **_kwargs: _LaunchRecord(),
    )
    result = recover_staged_handoff(str(artifacts), mode="explicit")
    assert result.adopted and result.kind == "monitor"
    assert result.destination is not None
    assert result.destination.get("member_artifacts_dir") == str(member)


def test_successor_detached_delivery_writes_one_receipt(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path, kind="pipe"), artifacts_dir=str(artifacts))
    write_staged_handoff_response(STAGED_ID, "response", artifacts_dir=str(artifacts))
    _write_meta(artifacts, pid=999999)
    _settle_ok(monkeypatch)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner",
        lambda *_a, **_k: "dead",
    )
    _patch_read_staged_successor(
        monkeypatch,
        lambda _origin, staged_id=None: {
            "successor": {
                "agent_name": "agent--1",
                "artifacts_dir": str(tmp_path / "child"),
                "launch_identity": "launch-1",
                "prompt_ref": "prompt-1",
            },
            "delivery_state": "created",
        },
    )

    from sase.axe.run_agent_successor import SuccessorDeliveryResult

    def fake_deliver(_origin: str, _staged_id: str) -> SuccessorDeliveryResult:
        return SuccessorDeliveryResult("submitted", "agent--1", str(tmp_path / "child"))

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_deliver.deliver_staged_successor_detached",
        fake_deliver,
    )
    result = recover_staged_handoff(str(artifacts), mode="explicit")
    assert result.adopted and not result.already_adopted
    assert result.destination is not None
    assert result.destination.get("successor_artifacts_dir") == str(tmp_path / "child")
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "adopted"
    assert receipt["refs"]["successor_artifacts_dir"] == str(tmp_path / "child")


def test_already_adopted_delivery_only_reuses_child(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    child = tmp_path / "child"
    child.mkdir()
    write_staged_handoff(_record(tmp_path, kind="pipe"), artifacts_dir=str(artifacts))
    write_adoption_receipt(
        {
            "staged_id": STAGED_ID,
            "adopted_at": "2026-10-28T12:01:00Z",
            "outcome": "adopted",
            "refs": {"successor_artifacts_dir": str(child)},
        },
        artifacts_dir=str(artifacts),
    )
    _write_meta(artifacts)

    from sase.axe.run_agent_successor import SuccessorDeliveryResult

    seen: list[str] = []

    def fake_deliver(origin: str, staged_id: str) -> SuccessorDeliveryResult:
        seen.append(staged_id)
        return SuccessorDeliveryResult("owned", "agent--1", str(child))

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_deliver.deliver_staged_successor_detached",
        fake_deliver,
    )
    result = recover_staged_handoff(str(artifacts), mode="automatic")
    assert result.adopted and result.already_adopted
    assert seen == [STAGED_ID]


def test_live_continuation_adopts_settled_plan(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        STAGED_ID, "planner response", artifacts_dir=str(artifacts)
    )
    _write_meta(artifacts)
    _settle_ok(monkeypatch)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner",
        lambda *_a, **_k: "dead",
    )
    calls: list[str] = []
    monkeypatch.setitem(
        STAGED_HANDOFF_ADOPTERS,
        "plan",
        lambda _record, _meta, _cont, response: calls.append(response),
    )
    continuation = _continuation(tmp_path, artifacts)
    with patch("sase.axe.run_agent_helpers.update_meta_field"):
        result = recover_staged_handoff(
            str(artifacts), mode="explicit", continuation=continuation
        )
    assert result.adopted
    assert calls == ["planner response"]
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "adopted"


def test_two_repo_commit_preserves_first_receipt(tmp_path: Path, monkeypatch) -> None:
    """A commits and B fails: A survives, repair only touches B, then adopts."""
    monkeypatch.setenv("SASE_AGENT", "1")
    artifacts = tmp_path / "20261028120000"
    artifacts.mkdir()
    write_staged_handoff(_record(tmp_path), artifacts_dir=str(artifacts))
    write_staged_handoff_response(
        STAGED_ID, "planner response", artifacts_dir=str(artifacts)
    )
    _write_meta(artifacts, pid=999999)
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery.observe_runner",
        lambda *_a, **_k: "dead",
    )
    commit_results = artifacts / "commit_results.json"
    commit_results.write_text(
        json.dumps(
            [
                {
                    "cwd": "/repo/a",
                    "result": "ok",
                    "commit_sha": "1" * 40,
                    "commit_tree": "a" * 40,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_facts.finalizer_settlement_refusal",
        lambda *_a, **_k: "finalizer instance 'commit' did not settle successfully",
    )
    held = recover_staged_handoff(str(artifacts), mode="explicit")
    assert not held.adopted and held.action == "hold"
    # A's commit evidence survives the held attempt.
    surviving = json.loads(commit_results.read_text(encoding="utf-8"))
    assert surviving[0]["commit_sha"] == "1" * 40
    assert read_adoption_receipt(str(artifacts))["outcome"] == "handoff_not_adopted"

    # Repair only B: append B's commit, then settlement proves clean.
    payload = json.loads(commit_results.read_text(encoding="utf-8"))
    payload.append(
        {
            "cwd": "/repo/b",
            "result": "ok",
            "commit_sha": "2" * 40,
            "commit_tree": "b" * 40,
        }
    )
    commit_results.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_facts.finalizer_settlement_refusal",
        lambda *_a, **_k: None,
    )
    _patch_read_staged_successor(
        monkeypatch,
        lambda _origin, staged_id=None: {
            "successor": {
                "agent_name": "agent--1",
                "artifacts_dir": str(tmp_path / "child"),
                "launch_identity": "launch-1",
                "prompt_ref": "prompt-1",
            },
            "delivery_state": "created",
        },
    )
    from sase.axe.run_agent_successor import SuccessorDeliveryResult

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_staged_recovery_deliver.deliver_staged_successor_detached",
        lambda _origin, _staged: SuccessorDeliveryResult(
            "submitted", "agent--1", str(tmp_path / "child")
        ),
    )
    # The staged record is a plan without a successor identity on disk, so
    # switch it to a pipe stage that carries the mocked successor above.
    from sase.agent.staged_handoff import build_pipe_staged_record

    (artifacts / ".sase_handoff_staged.json").write_text(
        json.dumps(
            build_pipe_staged_record(
                payload={"prompt": "piped prompt", "reason": "hand off"},
                staged_id=STAGED_ID,
                created_at="2026-10-28T12:00:00Z",
            )
        ),
        encoding="utf-8",
    )
    adopted = recover_staged_handoff(str(artifacts), mode="explicit")
    assert adopted.adopted
    final_payload = json.loads(commit_results.read_text(encoding="utf-8"))
    assert [row["commit_sha"] for row in final_payload] == ["1" * 40, "2" * 40]
    receipt = read_adoption_receipt(str(artifacts))
    assert receipt is not None and receipt["outcome"] == "adopted"
