"""Settlement success, ineligible recovery, and policy fall-through."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.types import InvokeResult
from sase.monitor.delivery import load_delivery_record, load_host_completion_receipt
from sase.monitor.host_completion import (
    COMPLETED_BY_HOST_STATUS,
    HOST_COMPLETED_OUTCOME,
    HOST_COMPLETION_IDENTITY,
)
from sase.monitor.host_completion_state import install_prepared_declaration
from sase.monitor.output import OutputCapture
from sase.turns.followup import FollowupLaunchResult

from ._host_completion import (
    make_meta,
    patch_mod,
    patch_success_path,
    production_recovery,
    sandbox_home as sandbox_home,
    settle,
)

__all__ = [
    "test_eligible_success_invokes_no_model_finalizers_and_zero_llm",
    "test_ineligible_success_launches_one_recovery_with_production_kwargs",
    "test_non_complete_policy_falls_through",
    "test_two_argument_recovery_callback_is_rejected",
]


def _ineligible_decision(reason: str) -> dict[str, Any]:
    return {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "eligible": False,
        "action": "recover",
        "reason": reason,
        "reasons": [reason],
        "rendered_message": None,
    }


def test_eligible_success_invokes_no_model_finalizers_and_zero_llm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    provider_invocations: list[object] = []
    finalizers = patch_success_path(monkeypatch)

    def run_finalizers(**kwargs: object) -> InvokeResult:
        assert kwargs.get("mode") == "no_model"
        from sase.finalizers.controller_context import should_skip_finalizers

        assert os.environ.get("SASE_AGENT_TIMESTAMP") == artifacts.name
        assert os.environ.get("SASE_ARTIFACTS_DIR") == str(artifacts)
        assert not should_skip_finalizers(str(artifacts))
        provider = kwargs["provider"]
        with pytest.raises(RuntimeError, match="must not invoke a provider"):
            provider.invoke("prompt")
        provider_invocations.append("checked")
        return InvokeResult(content="")

    finalizers.side_effect = run_finalizers
    submitted: list[dict[str, Any]] = []

    def submit_manifest(envelope: dict[str, Any], *, artifacts_dir: str) -> None:
        assert os.environ.get("SASE_AGENT_TIMESTAMP") == Path(artifacts_dir).name
        assert os.environ.get("SASE_ARTIFACTS_DIR") == artifacts_dir
        submitted.append(envelope)

    monkeypatch.setattr(
        "sase.monitor.host_completion_state.submit_final_manifest", submit_manifest
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion_execute._install_prepared_declaration",
        install_prepared_declaration,
    )
    releases: list[str] = []
    recoveries: list[dict[str, Any]] = []
    meta = make_meta()

    result = settle(
        artifacts,
        meta,
        launch_recovery=production_recovery(recoveries, launched=False),
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
    assert os.environ["SASE_AGENT_TIMESTAMP"] == artifacts.name
    assert len(submitted) == 1
    assert submitted[0]["run_id"] == artifacts.name
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
    patch_success_path(
        monkeypatch, decision=_ineligible_decision("stale_worktree_fingerprint")
    )
    patch_mod(
        monkeypatch,
        "invalidate_conditional_completion",
        lambda request: {**request["intent"], "status": "invalidated"},
    )
    recoveries: list[dict[str, Any]] = []
    capture = OutputCapture()

    result = settle(
        artifacts,
        make_meta(),
        launch_recovery=production_recovery(recoveries),
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
    patch_success_path(
        monkeypatch, decision=_ineligible_decision("stale_worktree_fingerprint")
    )
    patch_mod(
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
        settle(
            artifacts,
            make_meta(),
            launch_recovery=two_arg_recovery,
            release_claim=lambda *_a, **_k: None,
        )


def test_non_complete_policy_falls_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    recoveries: list[dict[str, Any]] = []
    result = settle(
        artifacts,
        make_meta(monitor_profile="verify", monitor_completion_ref="cci:test"),
        launch_recovery=production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        monitor_state="failed",
        exit_code=1,
        elapsed_seconds=12,
    )
    assert result is None
    assert recoveries == []
