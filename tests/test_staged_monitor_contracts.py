"""Contracts-phase tests: staged monitor payload, membership, liveness,
self-wait, atomic staged joins, and prepared reservation ownership.

These cover the Rust-owned contracts from ``sase-1pj.5.1.1`` through thin
Python adapters. Public monitor starts stay on their existing path: no test
here stages or launches a monitor.
"""

from __future__ import annotations

import json
import os
from hashlib import sha256
from pathlib import Path

import pytest

from sase.config.core import clear_config_cache
from sase.core.continuation_facade import evaluate_prepared_reservation_access
from sase.core.continuation_facade import seal_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.staged_handoff import (
    STAGED_MONITOR_LAUNCH_PAYLOAD_SCHEMA_VERSION,
    StagedHandoffContractError,
    evaluate_staged_monitor_membership,
    evaluate_staged_owner_liveness,
    evaluate_staged_self_wait,
    staged_monitor_launch_payload_schema_version,
    validate_staged_handoff,
    validate_staged_monitor_launch_payload,
)
from sase.core.tool_run import (
    tool_run_activate_staged_join,
    tool_run_claim,
    tool_run_release_staged_join,
    tool_run_reserve_staged_join,
)
from sase.finalizers._prepare_reservations import (
    load_prepared_intent_reservations,
    release_prepared_intent,
    reserve_prepared_intent,
)
from sase.finalizers.declaration import FinalizerDeclarationError
from sase.tool.argv import resolve_run_argv
from sase.tool.executor_recording import finish_tool_run
from sase.tool.handoff import reserve_handoff_run

pytestmark = pytest.mark.skipif(
    not hasattr(__import__("sase_core_rs"), "tool_run_reserve_staged_join"),
    reason="staged-join bindings are not in this wheel",
)

STAGED_A = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
STAGED_B = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("SASE_HOME", str(home))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_MONITOR_ID",
        "SASE_PROC_ID",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_EVENTS",
    ):
        monkeypatch.delenv(key, raising=False)
    clear_config_cache()
    return home


def _payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "staged_id": STAGED_A,
        "monitor_id": "monitor-1",
        "member_id": "member-1",
        "request_fingerprint": "fp-1",
        "command": ["sase", "tool", "run", "check"],
        "execution_argv": ["sase", "tool", "run", "check"],
        "label": "check",
        "policy_digest": "a" * 64,
        "lane": "followup",
        "cwd": "/tmp/work",
        "starter": {
            "agent_id": "agent-1",
            "run_id": "run-1",
            "artifacts_dir": "/tmp/artifacts/1",
        },
        "workspace": {"mode": "inherit"},
        "continuation": {"parent_node_ids": [], "protocol": "legacy"},
        "resources": {"tool_run_id": "run-abc"},
    }
    payload.update(overrides)
    return payload


def test_launch_payload_round_trips_and_versions() -> None:
    assert staged_monitor_launch_payload_schema_version() == (
        STAGED_MONITOR_LAUNCH_PAYLOAD_SCHEMA_VERSION
    )
    assert validate_staged_monitor_launch_payload(_payload()) == _payload()


def test_launch_payload_rejects_bad_fields() -> None:
    with pytest.raises(StagedHandoffContractError):
        validate_staged_monitor_launch_payload(_payload(command=[]))
    with pytest.raises(StagedHandoffContractError):
        validate_staged_monitor_launch_payload(_payload(policy_digest="nope"))
    with pytest.raises(StagedHandoffContractError):
        validate_staged_monitor_launch_payload(_payload(workspace={"mode": "none"}))
    continuation = {"parent_node_ids": [], "protocol": "someday"}
    with pytest.raises(StagedHandoffContractError):
        validate_staged_monitor_launch_payload(_payload(continuation=continuation))


def test_historic_minimal_monitor_records_still_validate() -> None:
    record = {
        "schema_version": 1,
        "staged_id": STAGED_A,
        "kind": "monitor",
        "created_at": "2026-10-28T12:00:00Z",
        "payload": {},
        "successor_workspace": "inherit",
        "carry_allowed": False,
        "dirty_obligations_at_stage": [],
    }
    assert validate_staged_handoff(record)["kind"] == "monitor"


def _membership(state: str, supervisor: bool) -> dict[str, object]:
    return evaluate_staged_monitor_membership(
        {
            "schema_version": 1,
            "monitor_state": state,
            "supervisor_present": supervisor,
        }
    )


def test_staged_membership_facts() -> None:
    staged = _membership("staged", False)
    assert staged["nonterminal"] is True
    assert staged["blocks_lane_start"] is True
    assert staged["has_supervisor"] is False
    assert staged["occupies_runner_capacity"] is False
    with pytest.raises(StagedHandoffContractError):
        _membership("staged", True)
    running = _membership("running", True)
    assert running["nonterminal"] is True
    assert running["has_supervisor"] is True
    assert running["occupies_runner_capacity"] is True
    for state in ("completed", "failed", "timeout", "stopped", "lost"):
        terminal = _membership(state, False)
        assert terminal["nonterminal"] is False
        assert terminal["blocks_lane_start"] is False
    with pytest.raises(StagedHandoffContractError):
        _membership("adrift", False)


def _liveness(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "schema_version": 1,
        "owner_kind": "monitor",
        "owner_id": "monitor-1",
        "staged_id": STAGED_A,
        "stage_record_present": True,
        "proc_exists": False,
    }
    request.update(overrides)
    return evaluate_staged_owner_liveness(request)


def test_staged_owner_stays_pending_before_proc() -> None:
    decision = _liveness()
    assert decision["pending_owner"] is True
    assert decision.get("reason") is None


def test_liveness_fails_closed() -> None:
    assert _liveness(owner_id="")["pending_owner"] is False
    assert _liveness(staged_id="nope")["pending_owner"] is False
    decision = _liveness(stage_record_present=False)
    assert decision["pending_owner"] is False
    assert decision["reason"] == "no_durable_staged_record"
    assert _liveness(proc_exists=True)["pending_owner"] is False
    decision = _liveness(owner_kind="proc")
    assert decision["pending_owner"] is False
    assert decision["reason"] == "owner_is_not_a_monitor"


def _self_wait(
    caller_owner_id: str = "monitor-1",
    caller_staged_id: str | None = STAGED_A,
    run_staged_id: str | None = STAGED_A,
    run_proc_exists: bool = False,
) -> dict[str, object]:
    return evaluate_staged_self_wait(
        {
            "schema_version": 1,
            "caller_owner_kind": "monitor",
            "caller_owner_id": caller_owner_id,
            "caller_staged_id": caller_staged_id,
            "caller_agent_name": "agent-1",
            "run_owner_kind": "monitor",
            "run_owner_id": "monitor-1",
            "run_staged_id": run_staged_id,
            "run_starter_agent_name": "agent-1",
            "run_proc_exists": run_proc_exists,
        }
    )


def test_self_wait_on_own_pending_staged_run() -> None:
    decision = _self_wait()
    assert decision["is_self_wait"] is True


def test_self_wait_ignores_agent_name_coincidence() -> None:
    decision = _self_wait(caller_owner_id="monitor-2")
    assert decision["is_self_wait"] is False
    assert decision["reason"] == "different_owner"


def test_self_wait_requires_durable_stage_ownership() -> None:
    assert _self_wait(run_staged_id=None)["is_self_wait"] is False
    assert _self_wait(run_proc_exists=True)["is_self_wait"] is False
    decision = _self_wait(caller_staged_id=None)
    assert decision["is_self_wait"] is False
    assert decision["reason"] == "stage_identity_mismatch"


def _reserve_detached(agent: str = "agent-1") -> str:
    resolved = resolve_run_argv(["--", "true"])
    reservation = reserve_handoff_run(
        resolved,
        owner_kind="proc",
        owner_id="proc-contracts",
        agent=agent,
        starter={
            "agent": agent,
            "pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        },
    )
    assert reservation.reserved, reservation.error
    return reservation.run_id


def _reserve(run_id: str, staged_id: str, monitor: str, agent: str) -> dict:
    return tool_run_reserve_staged_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "staged_id": staged_id,
            "monitor_id": monitor,
            "agent": agent,
        }
    )


def _activate(run_id: str, staged_id: str, monitor: str) -> dict:
    return tool_run_activate_staged_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "staged_id": staged_id,
            "monitor_id": monitor,
        }
    )


def _release(run_id: str, staged_id: str, monitor: str) -> dict:
    return tool_run_release_staged_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "staged_id": staged_id,
            "monitor_id": monitor,
        }
    )


def test_staged_join_reserve_activate_release() -> None:
    run_id = _reserve_detached()
    reserved = _reserve(run_id, STAGED_A, "m-1", "agent-1")
    assert reserved["outcome"] == "reserved"
    assert reserved["replayed"] is False
    assert reserved["run"]["staged_join_reservation"]["staged_id"] == STAGED_A

    replayed = _reserve(run_id, STAGED_A, "m-1", "agent-1")
    assert replayed["outcome"] == "reserved"
    assert replayed["replayed"] is True

    activated = _activate(run_id, STAGED_A, "m-1")
    assert activated["outcome"] == "activated"
    assert activated["run"]["join"]["id"] == "m-1"
    assert activated["run"]["join"]["kind"] == "monitor"
    assert "staged_join_reservation" not in activated["run"]

    again = _activate(run_id, STAGED_A, "m-1")
    assert again["outcome"] == "activated"
    assert again["replayed"] is True

    released = _release(run_id, STAGED_A, "m-1")
    assert released["outcome"] == "not_reserved"
    assert released["run"]["join"]["id"] == "m-1"


def test_staged_join_blocks_other_joiners_and_stages() -> None:
    run_id = _reserve_detached()
    assert _reserve(run_id, STAGED_A, "m-1", "agent-1")["outcome"] == "reserved"

    foreign = _reserve(run_id, STAGED_B, "m-2", "agent-1")
    assert foreign["outcome"] == "refused"
    assert foreign["refusal"] == "reservation_elsewhere"

    stolen = _activate(run_id, STAGED_B, "m-2")
    assert stolen["outcome"] == "refused"
    assert stolen["refusal"] == "reservation_mismatch"

    kept = _release(run_id, STAGED_B, "m-2")
    assert kept["outcome"] == "reserved_elsewhere"
    assert "staged_join_reservation" in kept["run"]

    released = _release(run_id, STAGED_A, "m-1")
    assert released["outcome"] == "released"
    again = _release(run_id, STAGED_A, "m-1")
    assert again["outcome"] == "not_reserved"


def test_staged_join_validates_starter_agent() -> None:
    run_id = _reserve_detached(agent="agent-1")
    refused = _reserve(run_id, STAGED_A, "m-1", "agent-9")
    assert refused["outcome"] == "refused"
    assert refused["refusal"] == "agent_mismatch"

    refused = _activate(run_id, STAGED_A, "m-1")
    assert refused["outcome"] == "refused"
    assert refused["refusal"] == "no_reservation"


def test_terminal_after_reserve_can_activate() -> None:
    run_id = _reserve_detached()
    assert _reserve(run_id, STAGED_A, "m-1", "agent-1")["outcome"] == "reserved"
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": run_id,
            "owner_kind": "proc",
            "owner_id": "proc-contracts",
            "wrapper_pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        }
    )
    assert claimed.get("outcome") == "claimed", claimed
    assert finish_tool_run(
        run_id,
        state="succeeded",
        exit_code=0,
        duration_ms=9,
        terminal_cause="exited",
    )
    activated = _activate(run_id, STAGED_A, "m-1")
    assert activated["outcome"] == "activated"
    assert activated["run"]["state"] == "succeeded"
    assert activated["run"]["join"]["id"] == "m-1"

    # Terminal before reservation is still refused.
    refused = _reserve(run_id, STAGED_B, "m-2", "agent-1")
    assert refused["outcome"] == "refused"
    assert refused["refusal"] == "settled"


def _reservation(staged_id: str, monitor: str) -> dict[str, object]:
    return {
        "staged_id": staged_id,
        "monitor_id": monitor,
        "request_fingerprint": "fp-1",
        "command": ["just", "check"],
    }


def _access(
    intent: str,
    staged_id: str,
    monitor: str,
    action: str,
    existing: list[dict[str, object]],
) -> dict:
    return evaluate_prepared_reservation_access(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent_ref": intent,
            "staged_id": staged_id,
            "monitor_id": monitor,
            "action": action,
            "existing": existing,
        }
    )


def test_prepared_reservation_ownership_matrix() -> None:
    existing = [
        {
            "intent_ref": "intent-1",
            "reservation": _reservation(STAGED_A, "monitor-1"),
        }
    ]
    assert _access("intent-2", STAGED_A, "m-1", "reserve", existing)["allowed"] is True
    assert (
        _access("intent-1", STAGED_A, "monitor-1", "bind", existing)["allowed"] is True
    )
    stolen = _access("intent-1", STAGED_B, "m-9", "bind", existing)
    assert stolen["allowed"] is False
    assert _access("intent-1", STAGED_A, "m-1", "bind", [])["allowed"] is False
    released = _access("intent-1", STAGED_A, "monitor-1", "release", existing)
    assert released["allowed"] is True
    assert _access("intent-1", STAGED_A, "monitor-1", "release", [])["allowed"] is True


def _write_intent_index(artifacts: Path, intent: dict[str, object]) -> str:
    intents = artifacts / "continuation" / "completion_intents"
    intents.mkdir(parents=True, exist_ok=True)
    intent_id = str(intent["intent_id"])
    (intents / f"{intent_id}.json").write_text(json.dumps(intent), encoding="utf-8")
    (intents / "index.json").write_text(
        json.dumps(
            {
                "intents": {
                    intent_id: {
                        "filename": f"{intent_id}.json",
                        "refs": [intent_id],
                    }
                },
                "aliases": {intent_id: intent_id},
            }
        ),
        encoding="utf-8",
    )
    return intent_id


def _prepared_intent() -> dict[str, object]:
    def digest(label: str) -> str:
        return sha256(label.encode()).hexdigest()

    context_digest = digest("context")
    plan_digest = digest("plan")
    return seal_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "creator": {
                "project": "sase",
                "run_id": "run-1",
                "agent_name": "agent-1",
            },
            "context": {
                "run_id": "run-1",
                "agent_id": "agent-1",
                "turn_nonce": "nonce-1",
                "plan_digest": plan_digest,
                "context_digest": context_digest,
                "obligation_ids": ["repo-main"],
            },
            "success_message": "Required checks passed.",
            "verification_command": ["just", "check"],
            "declaration": {
                "schema_version": 2,
                "context_digest": context_digest,
                "plan_digest": plan_digest,
                "payloads": [
                    {
                        "instance_id": "commit",
                        "payload": {
                            "repositories": [
                                {
                                    "repo_id": "repo-main",
                                    "action": "commit",
                                    "message": "fix: preserve prepared work",
                                }
                            ],
                            "deferrals": [],
                        },
                    }
                ],
            },
            "observations": [
                {
                    "repo_id": "repo-main",
                    "kind": "main",
                    "name": "main",
                    "head": digest("head"),
                    "head_tree": digest("head-tree"),
                    "index_tree": digest("index-tree"),
                    "complete": True,
                    "paths": [
                        {
                            "path": "src/app.py",
                            "kind": "file",
                            "protected": False,
                            "foreign": False,
                        }
                    ],
                }
            ],
            "executors": [
                {
                    "instance_id": "commit",
                    "provider_ref": "builtin@commit",
                    "headless": True,
                    "durable_replay": True,
                    "requires_model": False,
                }
            ],
        }
    )


def test_prepared_reservation_persist_round_trip(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    intent_id = _write_intent_index(artifacts, _prepared_intent())

    stored = reserve_prepared_intent(
        intent_id,
        _reservation(STAGED_A, "monitor-1"),
        artifacts_dir=artifacts,
    )
    assert stored["intent_ref"] == intent_id
    loaded = load_prepared_intent_reservations(artifacts_dir=artifacts)
    assert loaded[intent_id]["reservation"]["monitor_id"] == "monitor-1"

    # Another stage cannot steal the persisted intent.
    with pytest.raises(FinalizerDeclarationError):
        reserve_prepared_intent(
            intent_id,
            _reservation(STAGED_B, "monitor-9"),
            artifacts_dir=artifacts,
        )

    with pytest.raises(FinalizerDeclarationError):
        release_prepared_intent(
            intent_id,
            staged_id=STAGED_A,
            monitor_id="monitor-foreign",
            artifacts_dir=artifacts,
        )

    # Matching cleanup releases; repeats are idempotent.
    assert (
        release_prepared_intent(
            intent_id,
            staged_id=STAGED_A,
            monitor_id="monitor-1",
            artifacts_dir=artifacts,
        )
        is True
    )
    assert (
        release_prepared_intent(
            intent_id,
            staged_id=STAGED_A,
            monitor_id="monitor-1",
            artifacts_dir=artifacts,
        )
        is False
    )
    assert load_prepared_intent_reservations(artifacts_dir=artifacts) == {}


def test_corrupt_reservation_store_refuses_new_reservation(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    intent_id = _write_intent_index(artifacts, _prepared_intent())
    reservations = (
        artifacts / "continuation" / "completion_intents" / "reservations.json"
    )
    reservations.write_text("{truncated", encoding="utf-8")

    with pytest.raises(FinalizerDeclarationError, match="unreadable"):
        reserve_prepared_intent(
            intent_id,
            _reservation(STAGED_A, "monitor-1"),
            artifacts_dir=artifacts,
        )
