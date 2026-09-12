"""Host completion receiver: no-model success and durable recovery."""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.types import InvokeResult
from sase.monitor.delivery import (
    load_delivery_record,
    load_host_completion_receipt,
    persist_host_completion_receipt,
)
from sase.monitor.followup import launch_followup_agent
from sase.monitor.host_completion import (
    COMPLETED_BY_HOST_STATUS,
    HOST_COMPLETED_OUTCOME,
    HOST_COMPLETION_IDENTITY,
    settle_host_completion,
)
from sase.monitor.output import OutputCapture
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


def _intent(*repo_ids: str) -> dict[str, Any]:
    repositories = [
        {
            "repo_id": repo_id,
            "action": "commit",
            "message": "fix: finish the change",
        }
        for repo_id in repo_ids
    ]
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": "cci:test",
        "kind": "conditional_completion",
        "status": "bound",
        "success_message": "Required checks passed in {duration}.",
        "declaration": {
            "payloads": [
                {
                    "instance_id": "commit",
                    "payload": {"repositories": repositories, "deferrals": []},
                }
            ]
            if repositories
            else []
        },
        "repository_decisions": repositories,
        "seal": {"creator": {"workspace_id": "20"}, "plan_digest": "p" * 64},
        "verification": {"command": ["just", "check-full"]},
    }


def _capture() -> OutputCapture:
    return OutputCapture()


def _production_recovery(
    recoveries: list[dict[str, Any]],
    *,
    launched: bool = True,
) -> Any:
    required = {
        name
        for name, parameter in inspect.signature(
            launch_followup_agent
        ).parameters.items()
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY
        and parameter.default is inspect.Parameter.empty
    }

    def launch_recovery(
        artifacts_dir: str,
        meta: dict[str, Any],
        *,
        monitor_state: str,
        exit_code: int | None,
        elapsed_seconds: float,
        capture: OutputCapture,
        project_name: str,
        timeout_kind: str | None = None,
        transfer_from_pid: int | None = None,
    ) -> FollowupLaunchResult:
        kwargs = {
            "artifacts_dir": artifacts_dir,
            "meta": meta,
            "monitor_state": monitor_state,
            "exit_code": exit_code,
            "elapsed_seconds": elapsed_seconds,
            "capture": capture,
            "project_name": project_name,
            "timeout_kind": timeout_kind,
            "transfer_from_pid": transfer_from_pid,
        }
        missing = required - set(kwargs)
        assert not missing, f"recovery omitted {sorted(missing)}"
        recoveries.append(kwargs)
        if launched:
            return FollowupLaunchResult(launched=True, agent_name="acme--2")
        return FollowupLaunchResult(launched=False)

    return launch_recovery


def _settle(
    artifacts: Path,
    meta: dict[str, Any],
    *,
    launch_recovery: Any,
    release_claim: Any,
    **overrides: object,
) -> Any:
    kwargs: dict[str, Any] = {
        "monitor_state": "completed",
        "exit_code": 0,
        "elapsed_seconds": 182,
        "project_name": "proj",
        "capture": _capture(),
        **overrides,
    }
    return settle_host_completion(
        str(artifacts),
        meta,
        launch_recovery=launch_recovery,
        release_claim=release_claim,
        **kwargs,
    )


def _patch_mod(monkeypatch: pytest.MonkeyPatch, name: str, value: object) -> None:
    monkeypatch.setattr(f"sase.monitor.host_completion.{name}", value, raising=False)
    monkeypatch.setattr(
        f"sase.monitor.host_completion_state.{name}", value, raising=False
    )


def _patch_success_path(
    monkeypatch: pytest.MonkeyPatch,
    *,
    decision: dict[str, Any] | None = None,
    run_finalizers: MagicMock | None = None,
    intent: dict[str, Any] | None = None,
) -> MagicMock:
    plan = MagicMock()
    plan.plan_digest = "p" * 64
    plan.entries = [MagicMock(instance_id="commit", provider_ref="builtin@commit")]
    publication = MagicMock()
    publication.context.context_digest = "c" * 64
    publication.context.run_id = "run-1"
    publication.context.agent_id = "agent-1"
    publication.context.turn_nonce = "nonce-1"
    publication.context.plan_digest = "p" * 64
    publication.context.obligations = []
    publication.payload = {"manifest_template": {"payloads": []}}
    loaded = intent or _intent()
    _patch_mod(
        monkeypatch,
        "load_prepared_completion",
        lambda *_args, **_kwargs: loaded,
    )
    _patch_mod(monkeypatch, "ensure_finalizer_plan", lambda *_a, **_k: plan)
    _patch_mod(monkeypatch, "_ensure_finalizer_plan", lambda *_a, **_k: plan)
    _patch_mod(
        monkeypatch,
        "observe_completion_repositories",
        lambda *_a, **_k: [],
    )
    _patch_mod(
        monkeypatch,
        "publish_final_context",
        lambda **_k: publication,
    )
    monkeypatch.setattr(
        "sase.monitor.diagnostics.diagnostic_manifest",
        lambda *_a, **_k: {"stages": []},
    )
    _patch_mod(
        monkeypatch,
        "evaluate_conditional_completion",
        lambda *_a, **_k: decision or _eligible_decision(),
    )
    _patch_mod(
        monkeypatch,
        "install_prepared_declaration",
        lambda *_a, **_k: None,
    )
    _patch_mod(
        monkeypatch,
        "_install_prepared_declaration",
        lambda *_a, **_k: None,
    )
    finalizers = run_finalizers or MagicMock(return_value=InvokeResult(content=""))
    _patch_mod(monkeypatch, "run_finalizers", finalizers)
    _patch_mod(
        monkeypatch,
        "consume_conditional_completion",
        lambda request: {**request["intent"], "status": "consumed"},
    )
    _patch_mod(
        monkeypatch,
        "persist_prepared_completion",
        lambda *_a, **_k: None,
    )
    _patch_mod(monkeypatch, "load_commit_results", lambda *_a, **_k: [])
    _patch_mod(monkeypatch, "update_meta_field", lambda *_a, **_k: None)
    _patch_mod(monkeypatch, "mint_finalizer_turn_nonce", lambda: "nonce-exec")
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
    recoveries: list[dict[str, Any]] = []
    meta = _meta()

    result = _settle(
        artifacts,
        meta,
        launch_recovery=_production_recovery(recoveries, launched=False),
        release_claim=lambda _meta, _project: releases.append("released") or None,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    assert result.launch_result.agent_name == HOST_COMPLETION_IDENTITY
    assert provider_invocations == ["checked"]
    assert recoveries == []
    assert releases == ["released"]
    assert meta["monitor_host_completion_status"] == COMPLETED_BY_HOST_STATUS
    assert meta["monitor_followup_outcome"] == HOST_COMPLETED_OUTCOME
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "completed"
    assert receipt["published_message"] == "Required checks passed in 3m 02s."
    assert finalizers.call_count == 1
    record = load_delivery_record(
        artifacts,
        {
            "monitor_id": "monitor-1",
            "result_id": "result-1",
            "branch": "complete",
        },
    )
    assert record is not None
    assert record["disposition"] == "settled"
    assert record["acknowledged_by"] == HOST_COMPLETION_IDENTITY


def test_ineligible_success_launches_one_recovery_with_production_kwargs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _patch_success_path(
        monkeypatch, decision=_ineligible_decision("stale_worktree_fingerprint")
    )
    _patch_mod(
        monkeypatch,
        "invalidate_conditional_completion",
        lambda request: {**request["intent"], "status": "invalidated"},
    )
    recoveries: list[dict[str, Any]] = []
    capture = _capture()

    result = _settle(
        artifacts,
        _meta(),
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        elapsed_seconds=12,
        capture=capture,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.launched is True
    assert len(recoveries) == 1
    launched = recoveries[0]
    assert launched["monitor_state"] == "completed"
    assert launched["exit_code"] == 0
    assert launched["elapsed_seconds"] == 12
    assert launched["capture"] is capture
    assert launched["project_name"] == "proj"
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "recovery"
    assert receipt["reason"] == "stale_worktree_fingerprint"


def test_two_argument_recovery_callback_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _patch_success_path(
        monkeypatch, decision=_ineligible_decision("stale_worktree_fingerprint")
    )
    _patch_mod(
        monkeypatch,
        "invalidate_conditional_completion",
        lambda request: {**request["intent"], "status": "invalidated"},
    )

    def two_arg_recovery(
        artifacts_dir: str, meta: dict[str, Any]
    ) -> FollowupLaunchResult:
        del artifacts_dir, meta
        return FollowupLaunchResult(launched=True, agent_name="hidden")

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        _settle(
            artifacts,
            _meta(),
            launch_recovery=two_arg_recovery,
            release_claim=lambda *_a, **_k: None,
        )


def test_partial_repository_receipt_does_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    intent = _intent("repo-a", "repo-b")
    _patch_success_path(monkeypatch, intent=intent)
    _patch_mod(
        monkeypatch,
        "load_commit_results",
        lambda *_a, **_k: [
            {
                "cwd": "/tmp/repo-a",
                "repo_id": "repo-a",
                "result": "ok",
                "commit_sha": "a" * 40,
                "commit_tree": "b" * 40,
            }
        ],
    )
    _patch_mod(
        monkeypatch,
        "invalidate_conditional_completion",
        lambda request: {**request["intent"], "status": "invalidated"},
    )
    recoveries: list[dict[str, Any]] = []

    result = _settle(
        artifacts,
        _meta(),
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is not True
    assert result.launch_result.launched is True
    assert len(recoveries) == 1
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "recovery"
    assert receipt["reason"] == "outstanding_finalizer_actions"
    assert any(
        marker.get("repo_id") == "repo-a"
        for marker in receipt.get("commit_receipts") or []
    )


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
    _patch_mod(monkeypatch, "run_finalizers", finalizers)
    _patch_mod(monkeypatch, "update_meta_field", lambda *_a, **_k: None)
    recoveries: list[dict[str, Any]] = []

    result = _settle(
        artifacts,
        _meta(),
        launch_recovery=_production_recovery(recoveries, launched=False),
        release_claim=lambda *_a, **_k: None,
        elapsed_seconds=12,
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
    recoveries: list[dict[str, Any]] = []
    result = _settle(
        artifacts,
        _meta(monitor_profile="verify", monitor_completion_ref="cci:test"),
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=12,
    )
    assert result is None
    assert recoveries == []


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
