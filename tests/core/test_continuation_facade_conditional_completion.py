"""Tests for conditional completion sealing, binding, and evaluation."""

from __future__ import annotations

import pytest

from sase.core.continuation_facade import (
    bind_conditional_completion,
    consume_conditional_completion,
    evaluate_conditional_completion,
    invalidate_conditional_completion,
    preview_conditional_completion,
    rollback_conditional_completion_binding,
    seal_conditional_completion,
)
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from tests.core._continuation_facade_helpers import (
    digest,
    make_bound_intent,
    make_passed_stage,
    make_prepare_request,
)


def test_conditional_completion_seal_preview_and_single_use_bind() -> None:
    intent = seal_conditional_completion(make_prepare_request())
    assert intent["status"] == "prepared"
    assert intent["verification"]["level"] == "check_full"
    preview = preview_conditional_completion(intent)
    assert preview["success_action"] == "complete"
    assert preview["eligible"] is True

    bound = bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": intent,
            "monitor_id": "monitor-1",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:abc",
        }
    )
    assert bound["status"] == "bound"
    with pytest.raises(ValueError, match="not reusable"):
        bind_conditional_completion(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "intent": bound,
                "monitor_id": "monitor-2",
                "command": ["just", "check-full"],
                "request_fingerprint": "sha256:def",
            }
        )
    restored = rollback_conditional_completion_binding(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": bound,
            "monitor_id": "monitor-1",
        }
    )
    assert restored["status"] == "prepared"


def test_conditional_completion_rejects_missing_decisions_and_changed_commands() -> (
    None
):
    request = make_prepare_request()
    request["declaration"]["payloads"][0]["payload"]["repositories"] = []
    with pytest.raises(ValueError, match="missing repository decisions"):
        seal_conditional_completion(request)

    intent = seal_conditional_completion(make_prepare_request())
    with pytest.raises(ValueError, match="does not match"):
        bind_conditional_completion(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "intent": intent,
                "monitor_id": "monitor-1",
                "command": ["just", "check"],
                "request_fingerprint": "sha256:abc",
            }
        )


def test_conditional_completion_evaluate_consume_and_recovery_reasons() -> None:
    bound = make_bound_intent()
    observation = make_prepare_request()["observations"][0]
    executors = make_prepare_request()["executors"]
    stages = [
        make_passed_stage("formatting", "fmt (python)"),
        make_passed_stage("ruff", "lint (ruff)"),
        make_passed_stage("mypy", "lint (mypy)"),
        make_passed_stage("validation", "SASE validation"),
        make_passed_stage("full_tests", "test (full)"),
    ]
    eligible = evaluate_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": bound,
            "outcome": "completed",
            "exit_code": 0,
            "command": ["just", "check-full"],
            "observations": [observation],
            "stages": stages,
            "executors": executors,
            "workspace_identity": "/ws/20",
            "original_workspace_identity": "/ws/20",
            "degraded_workspace": False,
            "current_plan_digest": digest("plan"),
            "current_obligation_ids": ["repo-main"],
            "substitutions": {"duration": "3m 02s"},
        }
    )
    assert eligible["eligible"] is True
    assert eligible["action"] == "complete"
    assert eligible["rendered_message"] == "Required checks passed in 3m 02s."

    consumed = consume_conditional_completion(
        {"schema_version": CONTINUATION_WIRE_SCHEMA_VERSION, "intent": bound}
    )
    assert consumed["status"] == "consumed"
    again = consume_conditional_completion(
        {"schema_version": CONTINUATION_WIRE_SCHEMA_VERSION, "intent": consumed}
    )
    assert again["status"] == "consumed"

    missing = evaluate_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": bound,
            "outcome": "completed",
            "exit_code": 0,
            "command": ["just", "check-full"],
            "observations": [observation],
            "stages": stages[:-1],
            "executors": executors,
            "workspace_identity": "/ws/20",
            "original_workspace_identity": "/ws/20",
            "current_plan_digest": digest("plan"),
            "current_obligation_ids": ["repo-main"],
        }
    )
    assert missing["eligible"] is False
    assert missing["action"] == "recover"
    assert any(
        "missing_required_stage:full_tests" in item for item in missing["reasons"]
    )

    invalidated = invalidate_conditional_completion(
        {"schema_version": CONTINUATION_WIRE_SCHEMA_VERSION, "intent": bound}
    )
    assert invalidated["status"] == "invalidated"
