"""Commit workflow integration tests for runtime tags."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.workflows.commit.workflow import CommitWorkflow, RunResult
from _commit_runtime_tags_test_support import (
    clean_runtime_env as clean_runtime_env,
    owner_target,
)

_PROVIDER_TARGET = "sase.workflows.commit.workflow.get_vcs_provider"
_PROJECT_NAME_TARGET = "sase.workflows.utils.get_project_from_workspace"


def _run_workflow(payload: dict, method: str, provider: MagicMock) -> RunResult:
    wf = CommitWorkflow(payload, method)
    with (
        patch("sase.workflows.commit.workflow.handle_beads"),
        patch("sase.workflows.commit.workflow.handle_sase_plan"),
        patch(
            "sase.workflows.commit.workflow.run_before_commit_hook", return_value=True
        ),
        patch(
            "sase.workflows.commit.workflow.run_after_commit_hook", return_value=True
        ),
        patch("sase.workflows.commit.workflow.resolve_cl_name", return_value=None),
        patch("sase.workflows.commit.workflow.resolve_project_file", return_value=None),
        patch(
            "sase.workflows.commit.workflow.capture_pre_commit_diff",
            return_value=None,
        ),
        patch("sase.workflows.commit.workflow.checkpoint_save"),
        patch("sase.workflows.commit.workflow.checkpoint_delete"),
        patch("sase.workflows.commit.workflow.append_commits_entry", return_value=None),
        patch("sase.workflows.commit.workflow.create_patch", return_value=None),
        patch(_PROJECT_NAME_TARGET, return_value=None),
        patch(_PROVIDER_TARGET, return_value=provider),
    ):
        return wf.run()


def _make_provider() -> MagicMock:
    provider = MagicMock()
    provider.create_commit.return_value = (True, "abc123")
    provider.create_proposal.return_value = (True, "proposal.diff")
    provider.create_pull_request.return_value = (True, "https://example.test/pr/1")
    provider.revision_id.return_value = "a" * 40
    return provider


def test_create_commit_provider_receives_runtime_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    payload = {"message": "fix: bug"}
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    assert _run_workflow(payload, "create_commit", provider) == RunResult.OK

    provider.create_commit.assert_called_once_with(payload, ANY)
    assert payload["message"] == (
        "fix: bug\n\nSASE_TYPE=stitch\nSASE_AGENT=alice.machine_a.agent-a"
    )


def test_create_pull_request_tags_override_inherited_runtime_tags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    payload = {"name": "feat-x", "message": "feat: child PR"}
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-current")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path))
    (tmp_path / "agent_meta.json").write_text(
        json.dumps({"llm_provider": "test", "model": "m1", "name": "agent-current"}),
        encoding="utf-8",
    )

    with (
        patch(
            owner_target,
            return_value=AgentOwnerIdentity("alice", "machine_current"),
        ),
        patch(
            "sase.workflows.commit.pr_operations._fetch_parent_pr_tags",
            return_value={
                "TEAM": "infra",
                "AGENT": "agent-parent",
                "MACHINE": "machine-parent",
            },
        ),
        patch(
            "sase.vcs_provider.config.get_pr_tags",
            return_value={"MACHINE": "machine-config", "REVIEW": "true"},
        ),
    ):
        assert _run_workflow(payload, "create_pull_request", provider) == RunResult.OK

    provider.create_pull_request.assert_called_once_with(payload, ANY)
    message = payload["message"]
    assert "TEAM=infra" in message
    assert "REVIEW=true" in message
    assert "AGENT=alice.machine_current.agent-current" in message
    assert "MODEL=test/m1" in message
    assert "MACHINE=" not in message
    assert "agent-parent" not in message
    assert "machine-parent" not in message
    assert "machine-config" not in message
    assert "AGENT=alice.machine_current.agent-current" in payload["_pr_body"]
    assert "MODEL=test/m1" in payload["_pr_body"]
    assert "MACHINE=" not in payload["_pr_body"]


def test_create_proposal_does_not_add_runtime_tags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _make_provider()
    payload = {"message": "chore: propose change\n\nSASE_MODEL=legacy/model"}
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-a")

    assert _run_workflow(payload, "create_proposal", provider) == RunResult.OK

    provider.create_proposal.assert_called_once_with(payload, ANY)
    assert payload["message"] == "chore: propose change\n\nSASE_MODEL=legacy/model"
