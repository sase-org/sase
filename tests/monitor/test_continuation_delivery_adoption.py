"""Receiver adoption, provider handoff, and delivery transitions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.core.continuation_facade import transition_continuation_delivery
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.continuation_budget import MONITOR_CONTINUATION_ENV
from sase.llm_provider.types import InvokeResult
from sase.llm_provider.types import LLMInvocationError
from sase.monitor.continuation_delivery import (
    DELIVERY_ARTIFACTS_ENV,
    DELIVERY_IDENTITY_ENV,
    DELIVERY_KEY_ENV,
    adopt_ordinary_continuation_delivery,
    claim_ordinary_continuation_dispatch,
)
from sase.monitor.delivery import load_delivery_record

from ._continuation_delivery import continuation_delivery_sandbox  # noqa: F401

__all__ = [
    "test_budget_refusal_marks_adopted_delivery_needs_attention",
    "test_illegal_skip_of_dispatching_is_rejected",
    "test_invoke_adopts_before_fake_provider",
    "test_receiver_adopts_before_provider_invocation",
    "test_resume_adoption_decision_preserves_acknowledged_records",
    "test_schema_version_used_by_transition_request",
    "test_wrong_receiver_cannot_transition_delivery",
]


def test_receiver_adopts_before_provider_invocation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    claim = claim_ordinary_continuation_dispatch(
        str(artifacts),
        monitor_id="monitor-1",
        result_id="result-1",
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    assert claim.spawn is True
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, str(artifacts))
    monkeypatch.setenv(DELIVERY_KEY_ENV, json.dumps(claim.key, sort_keys=True))
    monkeypatch.setenv(DELIVERY_IDENTITY_ENV, "acme--1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")

    adopted = adopt_ordinary_continuation_delivery()
    assert adopted is not None
    assert adopted["disposition"] == "acknowledged"
    assert adopted["acknowledged_by"] == "acme--1"

    again = adopt_ordinary_continuation_delivery()
    assert again is not None
    assert again["disposition"] == "acknowledged"

    with pytest.raises(ValueError, match="cannot allocate intruder--1"):
        adopt_ordinary_continuation_delivery(agent_name="intruder--1")


def test_invoke_adopts_before_fake_provider(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider._invoke import invoke_agent

    artifacts = tmp_path / "child"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    parent = tmp_path / "monitor"
    parent.mkdir()
    claim = claim_ordinary_continuation_dispatch(
        str(parent),
        monitor_id="monitor-1",
        result_id="result-1",
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, str(parent))
    monkeypatch.setenv(DELIVERY_KEY_ENV, json.dumps(claim.key, sort_keys=True))
    monkeypatch.setenv(DELIVERY_IDENTITY_ENV, "acme--1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="ok")
    provider.resolve_model_name.return_value = "fake-model"

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(
            "sase.llm_provider._invoke.get_provider", lambda *a, **k: provider
        )
        patch.setattr("sase.llm_provider._invoke.postprocess_success", lambda **k: None)
        invoke_agent(
            "continue the work",
            agent_type="agent",
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
            skip_preprocessing=True,
        )

    provider.invoke.assert_called_once()
    record = load_delivery_record(parent, claim.key)
    assert record is not None
    assert record["disposition"] == "acknowledged"
    assert record["acknowledged_by"] == "acme--1"


def test_budget_refusal_marks_adopted_delivery_needs_attention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.llm_provider._invoke import invoke_agent

    artifacts = tmp_path / "child"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text("{}", encoding="utf-8")
    parent = tmp_path / "monitor"
    parent.mkdir()
    claim = claim_ordinary_continuation_dispatch(
        str(parent),
        monitor_id="monitor-1",
        result_id="result-1",
        branch="failed",
        selected_action="continue",
        reserved_identity="acme--1",
    )
    monkeypatch.setenv(DELIVERY_ARTIFACTS_ENV, str(parent))
    monkeypatch.setenv(DELIVERY_KEY_ENV, json.dumps(claim.key, sort_keys=True))
    monkeypatch.setenv(DELIVERY_IDENTITY_ENV, "acme--1")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")
    monkeypatch.setenv(MONITOR_CONTINUATION_ENV, "1")
    monkeypatch.setenv("SASE_CONTINUATION_CONTEXT_LIMIT_BYTES", "32")
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="should not run")
    provider.resolve_model_name.return_value = "fake-model"

    with (
        pytest.raises(LLMInvocationError, match="Continuation context budget exceeded"),
        pytest.MonkeyPatch.context() as patch,
    ):
        patch.setattr(
            "sase.llm_provider._invoke.get_provider", lambda *a, **k: provider
        )
        patch.setattr("sase.llm_provider._invoke.postprocess_error", lambda **k: None)
        patch.setattr(
            "sase.llm_provider._invoke.handle_possible_usage_limit",
            lambda **k: None,
        )
        invoke_agent(
            "x" * 100,
            agent_type="agent",
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
            skip_preprocessing=True,
        )

    provider.invoke.assert_not_called()
    record = load_delivery_record(parent, claim.key)
    assert record is not None
    assert record["disposition"] == "needs_attention"
    assert "context_budget_exceeded" in record["disposition_reason"]


def test_wrong_receiver_cannot_transition_delivery() -> None:
    from sase.monitor.delivery import new_delivery_record, transition_delivery

    record = new_delivery_record(
        {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"},
        selected_action="continue",
    )
    reserved = transition_delivery(record, "reserved", reserved_identity="acme--1")
    dispatching = transition_delivery(reserved, "dispatching")
    with pytest.raises(ValueError, match="intruder--1"):
        transition_delivery(dispatching, "acknowledged", acknowledged_by="intruder--1")
    acknowledged = transition_delivery(
        dispatching, "acknowledged", acknowledged_by="acme--1"
    )
    assert acknowledged["disposition"] == "acknowledged"


def test_illegal_skip_of_dispatching_is_rejected() -> None:
    from sase.monitor.delivery import new_delivery_record, transition_delivery

    record = new_delivery_record(
        {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"},
        selected_action="continue",
    )
    reserved = transition_delivery(record, "reserved", reserved_identity="acme--1")
    with pytest.raises(ValueError, match="dispatching"):
        transition_delivery(reserved, "acknowledged", acknowledged_by="acme--1")


def test_resume_adoption_decision_preserves_acknowledged_records() -> None:
    from sase.core.continuation_facade import decide_resume_adoption
    from sase.monitor.delivery import new_delivery_record, transition_delivery

    record = new_delivery_record(
        {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"},
        selected_action="continue",
    )
    reserved = transition_delivery(record, "reserved", reserved_identity="acme--1")
    dispatching = transition_delivery(reserved, "dispatching")
    acknowledged = transition_delivery(
        dispatching, "acknowledged", acknowledged_by="acme--1"
    )
    decision = decide_resume_adoption(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "records": [acknowledged],
            "request": {
                "kind": "manual_revision",
                "monitor_id": "monitor-1",
                "result_id": "result-1",
                "next_manual_branch": "manual-recovery-1",
            },
            "receiver_proofs": [],
            "recorded_at": "2026-09-13T00:00:00Z",
        }
    )
    assert decision["outcome"] == "already_delivered"
    assert decision["admit"] is False
    assert decision["preserve_keys"] == [acknowledged["key"]]
    assert decision["fence_keys"] == []


def test_schema_version_used_by_transition_request() -> None:
    payload = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "record": {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "key": {
                "monitor_id": "monitor-1",
                "result_id": "result-1",
                "branch": "failed",
            },
            "selected_action": "continue",
            "attempt_history": [
                {
                    "attempt_id": "attempt-1",
                    "status": "pending",
                    "recorded_at": "2026-09-12T00:00:00Z",
                }
            ],
            "disposition": "pending",
        },
        "target": "cancelled",
        "recorded_at": "2026-09-12T00:00:01Z",
    }
    cancelled = transition_continuation_delivery(payload)
    assert cancelled["disposition"] == "cancelled"
