"""No-new host completion settlement and outcome policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.monitor.host_completion import settle_host_completion
from sase.monitor.no_new_receipt import NoNewEvidence
from sase.monitor.output import OutputCapture
from sase.turns.followup import FollowupLaunchResult

from ._no_new_receipt import make_meta, needs_no_new_core

__all__ = [
    "test_freeze_failed_no_new_enters_host_completion",
    "test_freeze_failed_pass_stays_on_recovery",
    "test_host_completion_no_new_persists_verdict_provenance",
    "test_host_completion_no_new_refusal_recovers_with_typed_reason",
    "test_host_completion_no_new_shortcut_still_runs_precommit_gate",
    "test_host_completion_pass_intent_never_calls_receipt_gate",
    "test_host_completion_resume_reruns_gate_instead_of_trusting_success",
]


def _settle_arguments(
    artifacts: Path,
    meta: dict[str, Any],
    recoveries: list[dict[str, Any]],
    *,
    monitor_state: str = "failed",
    exit_code: int | None = 1,
) -> dict[str, Any]:
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
        recoveries.append({"exit_code": exit_code, "monitor_state": monitor_state})
        return FollowupLaunchResult(launched=True, agent_name="acme--2")

    return {
        "monitor_state": monitor_state,
        "exit_code": exit_code,
        "elapsed_seconds": 60,
        "project_name": "proj",
        "capture": OutputCapture(),
        "launch_recovery": launch_recovery,
        "release_claim": lambda _meta, _project: None,
    }


def _real_bound_intent(*, accept: str = "no_new_failures") -> dict[str, Any]:
    """Seal and bind a real intent so strict Rust validation accepts it."""

    from sase.core.continuation_facade import (
        bind_conditional_completion,
        seal_conditional_completion,
    )
    from tests.core._continuation_facade_helpers import make_prepare_request

    request = make_prepare_request()
    request["accept"] = accept
    prepared = seal_conditional_completion(request)
    return bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": prepared,
            "monitor_id": "monitor-1",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:abc",
        }
    )


def _patch_completion_harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    intent: dict[str, Any],
    verify: tuple[Any, Any],
) -> None:
    import sase.monitor.host_completion_complete as host_complete
    import sase.monitor.host_completion_execute as host_execute
    import sase.monitor.host_completion_run as host_run
    import sase.monitor.host_completion_settle as host_settle

    def _eligible_decision(*_a: object, **_k: object) -> dict[str, Any]:
        return {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "eligible": True,
            "action": "complete",
            "reason": None,
            "reasons": [],
            "rendered_message": "done",
        }

    snapshot = MagicMock()
    snapshot.plan.entries = []
    snapshot.plan.plan_digest = "p" * 64
    snapshot.obligation_ids = ()
    snapshot.observation_fingerprint = ()
    snapshot.publication.context.obligations = []
    for module in (host_settle, host_run, host_complete):
        monkeypatch.setattr(
            module,
            "load_prepared_completion",
            lambda _ref, artifacts_dir=None: dict(intent),
            raising=False,
        )
    for module in (host_run, host_execute):
        monkeypatch.setattr(
            module, "_snapshot_execution_context", lambda *_a, **_k: snapshot
        )
        monkeypatch.setattr(module, "_verify_no_new_receipt", lambda **_k: verify)
    monkeypatch.setattr(host_run, "_evaluate_intent", _eligible_decision)
    monkeypatch.setattr(
        host_complete,
        "consume_conditional_completion",
        lambda request: dict(request.get("intent") or {}),
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion_state.publish_final_context",
        lambda artifacts_dir=None: snapshot.publication,
    )


@needs_no_new_core
def test_host_completion_no_new_persists_verdict_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.monitor.host_completion_execute as host_execute
    from sase.monitor.delivery import load_host_completion_receipt

    intent = _real_bound_intent()
    evidence = NoNewEvidence(
        receipt_id="rc-1",
        run_id="run-1",
        verdict="no_new_failures",
        known_signatures=("known:flake-1",),
        accept="no_new_failures",
        tool_name="check",
    )
    _patch_completion_harness(monkeypatch, intent=intent, verify=(evidence, None))
    monkeypatch.setattr(
        host_execute,
        "can_finish_without_rerun",
        lambda *_a, **_k: True,
    )
    monkeypatch.setattr(
        host_execute, "_install_prepared_declaration", lambda *_a, **_k: None
    )
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    meta = make_meta()
    recoveries: list[dict[str, Any]] = []

    settlement = settle_host_completion(
        str(artifacts), meta, **_settle_arguments(artifacts, meta, recoveries)
    )

    assert recoveries == []
    assert settlement is not None
    assert settlement.launch_result is not None
    assert settlement.launch_result.host_completed is True
    receipt = load_host_completion_receipt(str(artifacts))
    assert receipt is not None and receipt.get("status") == "completed"
    verdict = receipt.get("verdict_receipt")
    assert verdict["receipt_id"] == "rc-1"
    assert verdict["run_id"] == "run-1"
    assert verdict["verdict"] == "no_new_failures"
    assert verdict["known_signatures"] == ["known:flake-1"]


@needs_no_new_core
def test_host_completion_no_new_refusal_recovers_with_typed_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    intent = _real_bound_intent()
    _patch_completion_harness(
        monkeypatch, intent=intent, verify=(None, "no_new_receipt_expired")
    )
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    meta = make_meta()
    recoveries: list[dict[str, Any]] = []

    settle_host_completion(
        str(artifacts), meta, **_settle_arguments(artifacts, meta, recoveries)
    )

    assert len(recoveries) == 1
    # The monitored child exit stays nonzero through recovery.
    assert recoveries[0]["exit_code"] == 1
    assert recoveries[0]["monitor_state"] == "failed"


@needs_no_new_core
def test_host_completion_no_new_shortcut_still_runs_precommit_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.monitor.host_completion_execute as host_execute
    import sase.monitor.host_completion_run as host_run

    intent = _real_bound_intent()
    evidence = NoNewEvidence(
        receipt_id="rc-1",
        run_id="run-1",
        verdict="no_new_failures",
        known_signatures=(),
        accept="no_new_failures",
        tool_name="check",
    )
    _patch_completion_harness(monkeypatch, intent=intent, verify=(evidence, None))
    monkeypatch.setattr(
        host_execute, "can_finish_without_rerun", lambda *_a, **_k: True
    )
    calls: list[dict[str, Any]] = []
    real_verify = host_run._verify_no_new_receipt

    def _gated(**kwargs: Any) -> tuple[Any, Any]:
        calls.append(kwargs)
        if len(calls) == 1:
            return evidence, None
        return None, "no_new_receipt_fingerprint_changed"

    for module in (host_run, host_execute):
        monkeypatch.setattr(module, "_verify_no_new_receipt", _gated)
    assert real_verify is not None
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    meta = make_meta()
    recoveries: list[dict[str, Any]] = []

    settle_host_completion(
        str(artifacts), meta, **_settle_arguments(artifacts, meta, recoveries)
    )

    assert len(calls) == 2
    assert calls[1].get("expected_receipt_id") == "rc-1"
    assert calls[1].get("expected_run_id") == "run-1"
    assert len(recoveries) == 1


@needs_no_new_core
def test_host_completion_resume_reruns_gate_instead_of_trusting_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json

    import sase.monitor.host_completion_execute as host_execute
    from sase.monitor.delivery import persist_host_completion_receipt

    intent = _real_bound_intent()
    _patch_completion_harness(
        monkeypatch,
        intent=intent,
        verify=(None, "no_new_receipt_fingerprint_changed"),
    )
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    # A successful marker exists but the obligated repo is still outstanding:
    # this is a resumed host completion, which must re-run the gate.
    (artifacts / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "repo_id": "repo-other",
                    "result": "ok",
                    "commit_sha": "s" * 40,
                    "cwd": "/other",
                }
            ]
        ),
        encoding="utf-8",
    )
    persist_host_completion_receipt(
        str(artifacts),
        {
            "schema_version": 1,
            "status": "finalizing",
            "intent_ref": "cci:no-new",
            "verdict_receipt": {
                "receipt_id": "rc-1",
                "run_id": "run-1",
                "verdict": "no_new_failures",
                "known_signatures": [],
            },
        },
    )
    monkeypatch.setattr(
        host_execute,
        "run_finalizers",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("must refuse before any commit action")
        ),
    )
    meta = make_meta()
    recoveries: list[dict[str, Any]] = []

    settle_host_completion(
        str(artifacts), meta, **_settle_arguments(artifacts, meta, recoveries)
    )

    assert len(recoveries) == 1


def test_host_completion_pass_intent_never_calls_receipt_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import sase.monitor.host_completion_execute as host_execute
    import sase.monitor.host_completion_run as host_run

    intent = _real_bound_intent(accept="pass")
    _patch_completion_harness(monkeypatch, intent=intent, verify=(None, "must-not-run"))
    monkeypatch.setattr(
        host_execute, "can_finish_without_rerun", lambda *_a, **_k: True
    )
    called: list[dict[str, Any]] = []

    def _fail_on_call(**kwargs: Any) -> tuple[Any, Any]:
        called.append(kwargs)
        raise AssertionError("receipt gate must not run for pass intents")

    for module in (host_run, host_execute):
        monkeypatch.setattr(module, "_verify_no_new_receipt", _fail_on_call)
    artifacts = tmp_path / "monitor"
    artifacts.mkdir()
    meta = make_meta()
    recoveries: list[dict[str, Any]] = []

    settlement = settle_host_completion(
        str(artifacts),
        meta,
        **_settle_arguments(
            artifacts, meta, recoveries, monitor_state="completed", exit_code=0
        ),
    )

    assert called == []
    assert recoveries == []
    assert settlement is not None
    assert settlement.launch_result is not None
    assert settlement.launch_result.host_completed is True


@needs_no_new_core
def test_freeze_failed_no_new_enters_host_completion() -> None:
    from sase.monitor.outcome_policy import freeze_start_outcome_policy
    from sase.monitor.request import StartMonitorRequest

    request = StartMonitorRequest(
        command="just check",
        reason="verify",
        timeout_seconds=60,
        cwd="/repo",
        project_name="sase",
        start_status="running",
        stop_status="done",
        profile="verify",
        completion_ref="cci:no-new",
    )

    frozen = freeze_start_outcome_policy(
        request, prepared_completion_accept="no_new_failures"
    )

    assert frozen is not None
    branches = frozen["branches"]
    assert branches["failed"]["action"] == "complete"
    assert branches["failed"]["completion_ref"] == "cci:no-new"
    assert branches["completed"]["action"] == "complete"
    assert branches["timeout"]["action"] == "continue"
    assert branches["stopped"]["action"] == "none"
    assert branches["lost"]["action"] == "none"


def test_freeze_failed_pass_stays_on_recovery() -> None:
    from sase.monitor.outcome_policy import freeze_start_outcome_policy
    from sase.monitor.request import StartMonitorRequest

    request = StartMonitorRequest(
        command="just check",
        reason="verify",
        timeout_seconds=60,
        cwd="/repo",
        project_name="sase",
        start_status="running",
        stop_status="done",
        profile="verify",
        completion_ref="cci:test",
    )

    frozen = freeze_start_outcome_policy(request)

    assert frozen is not None
    assert frozen["branches"]["failed"]["action"] == "continue"
