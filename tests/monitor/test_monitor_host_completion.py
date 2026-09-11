"""Host completion receiver: no-model success and durable recovery."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.types import InvokeResult
from sase.monitor.delivery import (
    load_host_completion_receipt,
    persist_host_completion_receipt,
)
from sase.monitor.host_completion import (
    COMPLETED_BY_HOST_STATUS,
    HOST_COMPLETED_OUTCOME,
    HOST_COMPLETION_IDENTITY,
    settle_host_completion,
)
from sase.shells.followup import FollowupLaunchResult


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260911120000")
    monkeypatch.setenv("SASE_AGENT_NAME", "acme--1")


def _meta(**overrides: object) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "monitor_id": "monitor-1",
        "monitor_completion_ref": "cci:test",
        "monitor_profile": "verify",
        "monitor_command": "just check-full",
        "monitor_execution_argv": ["just", "check-full"],
        "workspace_dir": "/ws/20",
        "workspace_num": 20,
        "continuation_monitor_result_id": "result-1",
        "monitor_diagnostic_manifest_ref": "file:explicit:diag",
        "name": "acme--1",
    }
    meta.update(overrides)
    return meta


def _eligible_decision() -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "eligible": True,
        "action": "complete",
        "reason": None,
        "reasons": [],
        "rendered_message": "Required checks passed in 3m 02s.",
    }


def _ineligible_decision(reason: str) -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "eligible": False,
        "action": "recover",
        "reason": reason,
        "reasons": [reason],
        "rendered_message": None,
    }


def _intent() -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": "cci:test",
        "kind": "conditional_completion",
        "status": "bound",
        "success_message": "Required checks passed in {duration}.",
        "declaration": {"payloads": []},
        "seal": {"creator": {"workspace_id": "20"}, "plan_digest": "p" * 64},
        "verification": {"command": ["just", "check-full"]},
    }


def _patch_success_path(
    monkeypatch: pytest.MonkeyPatch,
    *,
    decision: dict[str, Any] | None = None,
    run_finalizers: MagicMock | None = None,
) -> MagicMock:
    plan = MagicMock()
    plan.plan_digest = "p" * 64
    plan.entries = [MagicMock(instance_id="commit", provider_ref="builtin@commit")]
    publication = MagicMock()
    publication.context.context_digest = "c" * 64
    publication.context.obligations = []
    monkeypatch.setattr(
        "sase.monitor.host_completion.load_prepared_completion",
        lambda *_args, **_kwargs: _intent(),
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion._ensure_finalizer_plan", lambda *_a, **_k: plan
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.observe_completion_repositories",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.publish_final_context",
        lambda **_k: publication,
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.diagnostic_manifest",
        lambda *_a, **_k: {"stages": []},
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.evaluate_conditional_completion",
        lambda *_a, **_k: decision or _eligible_decision(),
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion._install_prepared_declaration",
        lambda *_a, **_k: None,
    )
    finalizers = run_finalizers or MagicMock(return_value=InvokeResult(content=""))
    monkeypatch.setattr("sase.monitor.host_completion.run_finalizers", finalizers)
    monkeypatch.setattr(
        "sase.monitor.host_completion.consume_conditional_completion",
        lambda request: {**request["intent"], "status": "consumed"},
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.persist_prepared_completion",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.load_commit_results", lambda *_a, **_k: []
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.update_meta_field", lambda *_a, **_k: None
    )
    return finalizers


def test_eligible_success_invokes_no_model_finalizers_and_zero_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    provider_invocations: list[object] = []
    finalizers = _patch_success_path(monkeypatch)

    def run_finalizers(**kwargs: object) -> InvokeResult:
        assert kwargs.get("mode") == "no_model"
        provider = kwargs["provider"]
        with pytest.raises(RuntimeError, match="must not invoke a provider"):
            provider.invoke("prompt")
        provider_invocations.append("checked")
        return InvokeResult(content="")

    finalizers.side_effect = run_finalizers
    releases: list[str] = []
    meta = _meta()

    result = settle_host_completion(
        str(artifacts),
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=182,
        project_name="proj",
        launch_recovery=lambda *_a, **_k: FollowupLaunchResult(launched=False),
        release_claim=lambda _meta, _project: releases.append("released") or None,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    assert result.launch_result.agent_name == HOST_COMPLETION_IDENTITY
    assert provider_invocations == ["checked"]
    assert releases == ["released"]
    assert meta["monitor_host_completion_status"] == COMPLETED_BY_HOST_STATUS
    assert meta["monitor_followup_outcome"] == HOST_COMPLETED_OUTCOME
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "completed"
    assert receipt["published_message"] == "Required checks passed in 3m 02s."
    assert finalizers.call_count == 1


def test_ineligible_success_launches_one_recovery_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _patch_success_path(
        monkeypatch, decision=_ineligible_decision("stale_worktree_fingerprint")
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.invalidate_conditional_completion",
        lambda request: {**request["intent"], "status": "invalidated"},
    )
    recoveries: list[str] = []

    def launch_recovery(
        artifacts_dir: str, meta: dict[str, Any]
    ) -> FollowupLaunchResult:
        recoveries.append(artifacts_dir)
        return FollowupLaunchResult(launched=True, agent_name="acme--2")

    result = settle_host_completion(
        str(artifacts),
        _meta(),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=launch_recovery,
        release_claim=lambda *_a, **_k: None,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.launched is True
    assert recoveries == [str(artifacts)]
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "recovery"
    assert receipt["reason"] == "stale_worktree_fingerprint"


def test_completed_receipt_does_not_rerun_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    persist_host_completion_receipt(
        artifacts,
        {"schema_version": 1, "status": "completed", "published_message": "done"},
    )
    finalizers = MagicMock(side_effect=AssertionError("must not rerun finalizers"))
    monkeypatch.setattr("sase.monitor.host_completion.run_finalizers", finalizers)
    monkeypatch.setattr(
        "sase.monitor.host_completion.update_meta_field", lambda *_a, **_k: None
    )

    result = settle_host_completion(
        str(artifacts),
        _meta(),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=lambda *_a, **_k: FollowupLaunchResult(launched=False),
        release_claim=lambda *_a, **_k: None,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    finalizers.assert_not_called()
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "completed"


def test_non_complete_policy_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    result = settle_host_completion(
        str(artifacts),
        _meta(monitor_profile="verify", monitor_completion_ref="cci:test"),
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=lambda *_a, **_k: FollowupLaunchResult(launched=True),
        release_claim=lambda *_a, **_k: None,
    )
    assert result is None


def test_no_model_controller_refuses_missing_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sase.finalizers.controller import FinalizerControllerError, run_finalizers

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    entry = MagicMock()
    entry.instance_id = "commit"
    entry.provider_ref = "builtin@commit"
    entry.resolved_index = 0
    monkeypatch.setattr(
        "sase.finalizers.controller.authenticate_resolved_finalizer_plan_full",
        lambda *_a, **_k: MagicMock(
            plan=MagicMock(entries=(entry,), plan_digest="p" * 64),
            drift=(),
        ),
    )
    publication = MagicMock()
    publication.submission_required = True
    publication.payload = {"selected_instances": [{"instance_id": "commit"}]}
    monkeypatch.setattr(
        "sase.finalizers.declaration.publish_final_context",
        lambda **_k: publication,
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.final_submission_is_current",
        lambda **_k: False,
    )
    monkeypatch.setattr(
        "sase.finalizers.controller._write_aggregate_result", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "sase.finalizers.controller._project_drift_to_agent_meta",
        lambda *_a, **_k: None,
    )

    with pytest.raises(FinalizerControllerError, match="accepted declaration"):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="done",
            invoke_result=InvokeResult(content=""),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
            mode="no_model",
        )
