"""Shared helpers for host-owned workflow completion tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.llm_provider.deferred import ProviderEvidence, digest_response
from sase.macro.workflow_completion import WorkflowReviewIdentity
from tests._failed_close_recovery_helpers import commit_config, use_config
from tests.finalizers_protocol_harness_test_helpers import prepare_agent_env

RUN_ID = "20261030120000"
PROVIDER_RESPONSE = "ordinary final response"


def workflow_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path]:
    """Return ``(repo, artifacts)`` with agent identity and finalizer plan."""
    artifacts = tmp_path / RUN_ID
    artifacts.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", RUN_ID)
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent-1", "workspace_num": 23}),
        encoding="utf-8",
    )
    use_config(monkeypatch, commit_config())
    return repo, artifacts


def agent_identity() -> WorkflowReviewIdentity:
    return WorkflowReviewIdentity(
        workflow="review-doc",
        step="draft",
        step_type="agent",
    )


def agent_evidence(content: str = PROVIDER_RESPONSE) -> ProviderEvidence:
    digest, chars = digest_response(content)
    return ProviderEvidence(
        agent_type="workflow-review-doc-draft",
        turn_nonce="nonce-test",
        response_sha256=digest,
        response_chars=chars,
    )
