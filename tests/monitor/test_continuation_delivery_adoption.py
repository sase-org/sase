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
    _ContinuationDeliveryFencedError,
    adopt_ordinary_continuation_delivery,
    claim_ordinary_continuation_dispatch,
    continuation_delivery_env,
    mark_ordinary_continuation_terminal,
)
from sase.monitor.delivery import (
    load_delivery_record,
    new_delivery_record,
    persist_delivery_record,
    transition_delivery,
)

from ._continuation_delivery import continuation_delivery_sandbox  # noqa: F401

__all__ = [
    "test_budget_refusal_marks_adopted_delivery_needs_attention",
    "test_fenced_error_survives_pickle_round_trip",
    "test_fenced_receiver_refusal_names_monitor_reason_and_identity",
    "test_illegal_skip_of_dispatching_is_rejected",
    "test_invoke_adopts_before_fake_provider",
    "test_non_fencing_adoption_refusal_keeps_original_error",
    "test_other_receiver_refusal_names_owner",
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


def test_fenced_receiver_refusal_names_monitor_reason_and_identity(
    tmp_path: Path,
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
    reason = (
        "receiver ownership is ambiguous: dispatching receiver acme--1 has no "
        "live process"
    )
    mark_ordinary_continuation_terminal(
        str(artifacts),
        claim.key,
        "needs_attention",
        selected_action="continue",
        reason=reason,
    )
    env = continuation_delivery_env(str(artifacts), claim.key, "acme--1")

    with pytest.raises(_ContinuationDeliveryFencedError) as excinfo:
        adopt_ordinary_continuation_delivery(env=env)

    error = excinfo.value
    assert isinstance(error, ValueError)
    message = str(error)
    assert "monitor monitor-1 branch failed" in message
    assert "needs_attention" in message
    assert reason in message
    assert "receiver acme--1" in message
    assert "provider was not invoked" in message
    assert "`sase monitor show monitor-1`" in message
    assert (error.disposition, error.reason, error.identity) == (
        "needs_attention",
        reason,
        "acme--1",
    )
    stored = load_delivery_record(artifacts, claim.key)
    assert stored is not None
    assert stored["disposition"] == "needs_attention"


def test_other_receiver_refusal_names_owner(tmp_path: Path) -> None:
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
    env = continuation_delivery_env(str(artifacts), claim.key, "acme--1")
    adopted = adopt_ordinary_continuation_delivery(env=env)
    assert adopted is not None
    assert adopted["disposition"] == "acknowledged"

    with pytest.raises(_ContinuationDeliveryFencedError) as excinfo:
        adopt_ordinary_continuation_delivery(env=env, agent_name="intruder--1")

    message = str(excinfo.value)
    assert "is acknowledged, owned by receiver acme--1" in message
    assert "receiver intruder--1 cannot adopt it" in message
    assert "cannot allocate intruder--1" in message
    again = adopt_ordinary_continuation_delivery(env=env)
    assert again is not None
    assert again["acknowledged_by"] == "acme--1"


def test_non_fencing_adoption_refusal_keeps_original_error(tmp_path: Path) -> None:
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    key = {"monitor_id": "monitor-1", "result_id": "result-1", "branch": "failed"}
    record = new_delivery_record(key, selected_action="continue")
    persist_delivery_record(
        artifacts,
        transition_delivery(record, "reserved", reserved_identity="acme--1"),
    )
    env = continuation_delivery_env(str(artifacts), key, "acme--1")

    with pytest.raises(ValueError, match="must pass through dispatching") as excinfo:
        adopt_ordinary_continuation_delivery(env=env)

    assert not isinstance(excinfo.value, _ContinuationDeliveryFencedError)


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


def test_fenced_error_survives_pickle_round_trip() -> None:
    import pickle

    error = _ContinuationDeliveryFencedError("fenced", disposition="needs_attention")
    restored = pickle.loads(pickle.dumps(error))
    assert isinstance(restored, _ContinuationDeliveryFencedError)
    assert str(restored) == "fenced"
