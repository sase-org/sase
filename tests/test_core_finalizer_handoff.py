"""Parity tests for the finalizer handoff wire and prepared coverage."""

from __future__ import annotations

import json

import pytest

from sase.core.continuation_facade import evaluate_prepared_starter_coverage
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.core.finalizer_facade import (
    check_repository_action,
    finalizer_context_digest,
    resolve_finalizer_plan,
    validate_finalizer_context,
    validate_finalizer_handoff,
)
from sase.core.finalizer_wire import (
    FINALIZER_WIRE_SCHEMA_VERSION,
    FinalizerContextWire,
    FinalizerHandoffWire,
    FinalizerInstancePolicyWire,
    FinalizerInstanceSpecWire,
    FinalizerPayloadRequirementWire,
    FinalizerPlanInputWire,
    RepositoryActionCheckRequestWire,
    finalizer_add,
    finalizer_context_from_dict,
    finalizer_handoff_from_dict,
    finalizer_wire_to_json_dict,
    repository_action_outcome_from_dict,
)


pytestmark = pytest.mark.contract

STAGED = "123e4567-e89b-12d3-a456-426614174000"


def _handoff(kind: str, successor: str, carry: bool, **kwargs) -> dict:
    record: dict = {
        "kind": kind,
        "staged_ref": STAGED,
        "successor_workspace": successor,
        "carry_allowed": carry,
    }
    record.update(kwargs)
    return record


def _plan():
    return resolve_finalizer_plan(
        FinalizerPlanInputWire(
            schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
            instances=[
                FinalizerInstanceSpecWire(
                    schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
                    instance_id="commit",
                    provider_ref="builtin@commit",
                    policy=FinalizerInstancePolicyWire(),
                )
            ],
            selectors=[finalizer_add("commit")],
        )
    )


def _context(plan, handoff=None, submission_required=True):
    context = FinalizerContextWire(
        schema_version=FINALIZER_WIRE_SCHEMA_VERSION,
        run_id="run-1",
        agent_id="agent-1",
        turn_nonce="nonce-1",
        plan_digest=plan.plan_digest,
        requirements=[
            FinalizerPayloadRequirementWire(
                instance_id="commit",
                trigger="dirty_repository",
                submission_required=submission_required,
            )
        ],
        obligations=[],
        handoff=(finalizer_handoff_from_dict(handoff) if handoff is not None else None),
    )
    digest = finalizer_context_digest(context)
    return FinalizerContextWire(
        schema_version=context.schema_version,
        run_id=context.run_id,
        agent_id=context.agent_id,
        turn_nonce=context.turn_nonce,
        plan_digest=context.plan_digest,
        requirements=context.requirements,
        obligations=context.obligations,
        handoff=context.handoff,
        assigned_bead=None,
        context_digest=digest,
    )


def test_handoff_wire_parity_and_action_check() -> None:
    for kind, successor, carry in [
        ("plan", "none", False),
        ("questions", "inherit", True),
        ("pipe", "inherit", True),
        ("monitor", "inherit", False),
        ("monitor", "inherit", True),
        ("gate", "none", False),
        ("gate", "inherit", True),
        ("gate", "inherit", False),
    ]:
        validate_finalizer_handoff(_handoff(kind, successor, carry))

    with pytest.raises(ValueError, match="plan handoffs"):
        validate_finalizer_handoff(_handoff("plan", "none", True))
    with pytest.raises(ValueError, match="require carry_allowed"):
        validate_finalizer_handoff(_handoff("questions", "inherit", False))
    with pytest.raises(ValueError, match="monitor handoffs"):
        validate_finalizer_handoff(_handoff("monitor", "none", False))
    with pytest.raises(ValueError, match="none cannot set carry_allowed"):
        validate_finalizer_handoff(_handoff("gate", "none", True))
    with pytest.raises(ValueError, match="prepared_intent_ref"):
        validate_finalizer_handoff(
            _handoff("questions", "inherit", True, prepared_intent_ref="i-1")
        )
    prepared = _handoff("monitor", "inherit", False, prepared_intent_ref="intent-1")
    validate_finalizer_handoff(prepared)

    outcome = check_repository_action(RepositoryActionCheckRequestWire(action="commit"))
    assert outcome.status == "allowed"
    assert outcome.action == "commit"

    outcome = check_repository_action(
        {
            "action": "carry",
            "handoff": _handoff("questions", "inherit", True),
        }
    )
    assert outcome.status == "allowed"

    outcome = check_repository_action({"action": "carry"})
    assert outcome.status == "rejected"
    assert outcome.code == "carry_requires_handoff"

    outcome = check_repository_action({"action": "defer"})
    assert outcome.status == "rejected"
    assert outcome.code == "unknown_repository_action"

    outcome = check_repository_action(
        {
            "action": "carry",
            "handoff": _handoff("plan", "none", False),
        }
    )
    assert outcome.status == "rejected"

    parsed = repository_action_outcome_from_dict(finalizer_wire_to_json_dict(outcome))
    assert parsed.status == outcome.status


def test_context_digest_preserves_legacy_and_covers_handoff() -> None:
    plan = _plan()
    legacy = _context(plan)
    assert validate_finalizer_context(plan, legacy)

    # Legacy JSON without the new key still parses with handoff None.
    raw = finalizer_wire_to_json_dict(legacy)
    assert "handoff" not in raw
    assert finalizer_context_from_dict(json.loads(json.dumps(raw))).handoff is None

    carrying = _context(
        plan,
        _handoff("questions", "inherit", True),
        submission_required=False,
    )
    assert validate_finalizer_context(plan, carrying)
    assert finalizer_context_digest(carrying) != finalizer_context_digest(legacy)

    tampered = dict(finalizer_wire_to_json_dict(carrying))
    tampered["handoff"]["carry_allowed"] = False
    with pytest.raises(ValueError, match="context_digest"):
        validate_finalizer_context(plan, tampered)

    dirty_optional_without_handoff = _context(plan, None, submission_required=False)
    with pytest.raises(ValueError, match="without a staged handoff"):
        validate_finalizer_context(plan, dirty_optional_without_handoff)

    prepared_handoff = _context(
        plan,
        _handoff("monitor", "inherit", False, prepared_intent_ref="intent-1"),
        submission_required=False,
    )
    assert validate_finalizer_context(plan, prepared_handoff)


def test_handoff_wire_serialization_round_trip() -> None:
    wire = FinalizerHandoffWire(
        kind="gate",
        staged_ref=STAGED,
        successor_workspace="inherit",
        carry_allowed=True,
        prepared_intent_ref=None,
    )
    raw = finalizer_wire_to_json_dict(wire)
    assert "prepared_intent_ref" not in raw
    assert finalizer_handoff_from_dict(raw) == wire
    assert finalizer_handoff_from_dict(None) is None


def _sealed_intent() -> dict:
    from sase.core.continuation_facade import seal_conditional_completion

    declaration = {
        "payloads": [
            {
                "instance_id": "commit",
                "payload": {
                    "repositories": [
                        {
                            "repo_id": "repo:primary",
                            "action": "commit",
                            "message": "m",
                        }
                    ]
                },
            }
        ]
    }
    context_digest = "b" * 64
    plan_digest = "a" * 64
    observations = [
        {
            "repo_id": "repo:primary",
            "kind": "repository",
            "name": "repo:primary",
            "head": "head-1",
            "head_tree": "tree-1",
            "index_tree": "index-1",
            "paths": [],
            "complete": True,
        }
    ]
    intent = seal_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "creator": {
                "project": "sase",
                "run_id": "run-1",
                "agent_name": "agent-1",
                "workspace_id": "ws-1",
            },
            "context": {
                "run_id": "run-1",
                "agent_id": "agent-1",
                "turn_nonce": "nonce-1",
                "plan_digest": plan_digest,
                "context_digest": context_digest,
                "obligation_ids": ["repo:primary"],
            },
            "success_message": "done {duration}",
            "verification_command": ["just", "check"],
            "declaration": declaration,
            "observations": observations,
        }
    )
    return {
        "intent": intent,
        "observations": observations,
        "plan_digest": plan_digest,
    }


def _coverage_request(sealed, **overrides):
    request = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent": sealed["intent"],
        "staged_id": STAGED,
        "staged_kind": "monitor",
        "reservation": {
            "staged_id": STAGED,
            "monitor_id": "monitor-1",
            "request_fingerprint": "fp-1",
            "command": ["just", "check"],
        },
        "starter_run_id": "run-1",
        "starter_agent_id": "agent-1",
        "starter_workspace_id": "ws-1",
        "monitor_id": "monitor-1",
        "command": ["just", "check"],
        "request_fingerprint": "fp-1",
        "current_observations": sealed["observations"],
        "current_plan_digest": sealed["plan_digest"],
        "current_obligation_ids": ["repo:primary"],
    }
    request.update(overrides)
    return request


def test_prepared_starter_coverage_parity() -> None:
    sealed = _sealed_intent()
    decision = evaluate_prepared_starter_coverage(_coverage_request(sealed))
    assert decision["eligible"] is True
    assert decision["covered_repository_ids"] == ["repo:primary"]

    no_reservation = _coverage_request(sealed, reservation=None)
    decision = evaluate_prepared_starter_coverage(no_reservation)
    assert decision["eligible"] is False
    assert "prepared_intent_requires_reservation" in decision["reasons"]

    wrong_monitor = _coverage_request(sealed, monitor_id="monitor-2")
    decision = evaluate_prepared_starter_coverage(wrong_monitor)
    assert decision["eligible"] is False

    wrong_owner = _coverage_request(sealed, starter_run_id="run-2")
    decision = evaluate_prepared_starter_coverage(wrong_owner)
    assert decision["eligible"] is False
    assert "prepared_creator_run_mismatch" in decision["reasons"]

    incomplete = _coverage_request(
        sealed, current_obligation_ids=["repo:primary", "repo:extra"]
    )
    decision = evaluate_prepared_starter_coverage(incomplete)
    assert decision["eligible"] is False
    assert decision["covered_repository_ids"] == ["repo:primary"]
    assert "uncovered_repository:repo:extra" in decision["reasons"]

    stale = _coverage_request(sealed)
    stale_obs = [dict(sealed["observations"][0])]
    stale_obs[0]["head_tree"] = "tree-2"
    stale["current_observations"] = stale_obs
    decision = evaluate_prepared_starter_coverage(stale)
    assert decision["eligible"] is False
    assert "stale_observations" in decision["reasons"]
