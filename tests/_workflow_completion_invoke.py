"""Invoke and prepare coverage for host-owned workflow reviews."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.staged_handoff import release_staging_reservation
from sase.llm_provider.deferred import (
    ProviderEvidence,
    digest_response,
    record_deferred_provider_evidence,
    take_deferred_provider_evidence,
)
from sase.llm_provider.messages import AIMessage
from sase.llm_provider.preprocessing import _PreprocessResult
from sase.llm_provider.types import InvokeResult
from sase.macro.workflow_completion import (
    WorkflowReviewIdentity,
    _WorkflowCompletionError,
    invoke_provider_for_review,
    prepare_workflow_review,
)
from tests._workflow_completion_helpers import (
    PROVIDER_RESPONSE,
    RUN_ID,
    agent_evidence,
    agent_identity,
    workflow_env,
)


def _fake_agent_invoke(
    monkeypatch: pytest.MonkeyPatch,
    content: str = PROVIDER_RESPONSE,
) -> None:
    """Stand in for ``invoke_agent`` with the deferred branch's evidence."""

    def fake(prompt: object, **kwargs: object) -> AIMessage:
        assert kwargs.get("defer_finalizers") is True
        token = kwargs.get("evidence_token")
        assert isinstance(token, str) and token
        digest, chars = digest_response(content)
        record_deferred_provider_evidence(
            token,
            ProviderEvidence(
                agent_type=str(kwargs.get("agent_type")),
                turn_nonce="nonce-live",
                response_sha256=digest,
                response_chars=chars,
            ),
        )
        return AIMessage(content=content)

    monkeypatch.setattr("sase.llm_provider.invoke_agent", fake)


def test_deferred_evidence_registry_round_trip() -> None:
    assert take_deferred_provider_evidence("missing") is None
    first = agent_evidence("one")
    second = agent_evidence("two")
    record_deferred_provider_evidence("tok", first)
    record_deferred_provider_evidence("tok", second)
    assert take_deferred_provider_evidence("tok") == second
    assert take_deferred_provider_evidence("tok") is None


def test_deferred_invoke_skips_finalizers_and_records_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.llm_provider._invoke import invoke_agent

    artifacts = tmp_path / RUN_ID
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.delenv("SASE_FINAL_TURN_NONCE", raising=False)
    with (
        patch(
            "sase.llm_provider._invoke.preprocess_prompt",
            return_value=_PreprocessResult(prompt="preprocessed"),
        ),
        patch("sase.llm_provider._invoke.get_provider"),
        patch(
            "sase.llm_provider._invoke.invoke_with_instructions",
            return_value=InvokeResult(content="review output"),
        ),
        patch("sase.llm_provider._invoke.postprocess_success"),
        patch(
            "sase.finalizers.run_finalizers",
            side_effect=AssertionError("finalizers must be deferred"),
        ),
    ):
        result = invoke_agent(
            "prompt",
            agent_type="workflow-x",
            artifacts_dir=str(artifacts),
            provider_name="fakey",
            suppress_output=True,
            defer_finalizers=True,
            evidence_token="tok-deferred",
        )
    assert result.content == "review output"
    from sase.axe.runner_lifecycle_phase import current_lifecycle_phase

    assert current_lifecycle_phase() == "provider_done"
    from sase.finalizers.declaration import SASE_FINAL_TURN_NONCE_ENV

    assert SASE_FINAL_TURN_NONCE_ENV not in os.environ
    evidence = take_deferred_provider_evidence("tok-deferred")
    assert evidence is not None
    assert evidence.agent_type == "workflow-x"
    assert evidence.turn_nonce
    digest, chars = digest_response("review output")
    assert evidence.response_sha256 == digest
    assert evidence.response_chars == chars


def test_invoke_provider_for_review_returns_completed_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fake_agent_invoke(monkeypatch)
    response, evidence = invoke_provider_for_review(
        "do work",
        agent_type="workflow-review-doc-draft",
        artifacts_dir=str(tmp_path),
        workflow="review-doc",
    )
    assert response.content == PROVIDER_RESPONSE
    assert evidence.turn_nonce == "nonce-live"
    digest, _chars = digest_response(PROVIDER_RESPONSE)
    assert evidence.response_sha256 == digest


def test_invoke_provider_for_review_refuses_missing_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_no_evidence(prompt: object, **kwargs: object) -> AIMessage:
        return AIMessage(content=PROVIDER_RESPONSE)

    monkeypatch.setattr("sase.llm_provider.invoke_agent", fake_no_evidence)
    with pytest.raises(
        _WorkflowCompletionError,
        match="no completed-provider evidence",
    ):
        invoke_provider_for_review(
            "do work",
            agent_type="workflow-review-doc-draft",
            artifacts_dir=str(tmp_path),
        )


def test_prepare_agent_review_requires_provider_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, _artifacts = workflow_env(tmp_path, monkeypatch)
    with pytest.raises(
        _WorkflowCompletionError,
        match="completed-provider evidence",
    ):
        prepare_workflow_review(
            identity=agent_identity(),
            output={"text": "draft"},
            artifacts_dir=str(_artifacts),
            has_output=True,
        )


def test_prepare_script_review_needs_no_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, artifacts = workflow_env(tmp_path, monkeypatch)
    for step_type in ("bash", "python"):
        identity = WorkflowReviewIdentity(
            workflow="review-doc",
            step="build",
            step_type=step_type,
        )
        review = prepare_workflow_review(
            identity=identity,
            output={"exit_code": 0},
            artifacts_dir=str(artifacts),
        )
        assert review.successor_workspace == "inherit"
        assert review.carry_allowed is True
        assert review.evidence_wire is None
        release_staging_reservation(
            review.reservation_id,
            artifacts_dir=str(artifacts),
        )


def test_prepare_review_rejects_unknown_step_type(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, artifacts = workflow_env(tmp_path, monkeypatch)
    with pytest.raises(_WorkflowCompletionError, match="step type"):
        prepare_workflow_review(
            identity=WorkflowReviewIdentity(
                workflow="review-doc",
                step="build",
                step_type="shell",
            ),
            output={},
            artifacts_dir=str(artifacts),
        )
