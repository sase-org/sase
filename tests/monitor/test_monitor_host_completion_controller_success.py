"""Real-controller host completion: success path and declaration checks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from sase.finalizers.declaration import (
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.macro.directives import PromptDirectives
from sase.monitor.delivery import load_host_completion_receipt
from sase.monitor.host_completion import (
    HOST_COMPLETION_IDENTITY,
    settle_host_completion,
)

from ..finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    successful_stitch,
)
from ._host_completion_controller import (
    bind_prepared,
    capture,
    check_full_stages,
    controller_catalog as controller_catalog,
    controller_meta,
    controller_recovery,
    observation,
    write_stages,
)

__all__ = [
    "test_bead_action_is_required_when_context_has_assigned_bead",
    "test_finalizer_process_binding_preserves_existing_nonce",
    "test_real_controller_success_uses_zero_model_calls",
    "test_real_declaration_submit_is_not_stubbed_on_success_path",
]


def test_real_controller_success_uses_zero_model_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    monkeypatch.setenv("SASE_WORKSPACE_NUM", "20")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    publication = publish_final_context(artifacts_dir=str(artifacts))
    repo_id = publication.context.obligations[0].obligation_id
    observations = [observation(repo_id)]
    intent_ref = bind_prepared(monkeypatch, artifacts, observations)
    write_stages(artifacts, check_full_stages())
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        successful_stitch(artifacts, dirty, calls),
    )
    recoveries: list[str] = []
    invokes: list[str] = []

    def track_invoke(self: object, *args: object, **kwargs: object) -> None:
        del self, args, kwargs
        invokes.append("provider")
        raise AssertionError("no-model host completion must not invoke a provider")

    monkeypatch.setattr(
        "sase.monitor.host_completion_execute._NoModelProvider.invoke", track_invoke
    )
    monkeypatch.delenv(SASE_FINAL_TURN_NONCE_ENV, raising=False)

    result = settle_host_completion(
        str(artifacts),
        controller_meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=182,
        project_name="proj",
        launch_recovery=controller_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=capture(),
        selected_action="complete",
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    assert result.launch_result.agent_name == HOST_COMPLETION_IDENTITY
    assert recoveries == []
    assert invokes == []
    assert os.environ.get(SASE_FINAL_TURN_NONCE_ENV)
    assert calls == ["main"]
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "completed"
    assert "Required checks passed in 3m 02s." in str(receipt.get("published_message"))


def test_finalizer_process_binding_preserves_existing_nonce(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.monitor.host_completion_state import _bind_finalizer_process_identity

    artifacts = tmp_path / "run-1"
    artifacts.mkdir()
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "starter-nonce")

    _bind_finalizer_process_identity(str(artifacts))

    assert os.environ[SASE_FINAL_TURN_NONCE_ENV] == "starter-nonce"


def test_bead_action_is_required_when_context_has_assigned_bead() -> None:
    from sase.core.finalizer_wire import (
        FinalizerAssignedBeadWire,
        FinalizerContextWire,
        FinalizerInstancePolicyWire,
        FinalizerObligationWire,
        FinalizerPlanEntryWire,
        FinalizerPlanWire,
    )
    from sase.finalizers.declaration import FinalizerDeclarationError
    from sase.finalizers.declaration_manifest import validate_provider_payloads

    context = FinalizerContextWire(
        schema_version=2,
        run_id="run-1",
        agent_id="agent-1",
        turn_nonce="nonce-1",
        plan_digest="p" * 64,
        requirements=[],
        obligations=[
            FinalizerObligationWire(
                obligation_id="repo-main",
                kind="repository",
                display_name="main",
                paths=["src/app.py"],
            )
        ],
        assigned_bead=FinalizerAssignedBeadWire(
            bead_id="sase-zq.1",
            primary_repo_obligation_id="repo-main",
        ),
    )
    plan = FinalizerPlanWire(
        schema_version=2,
        entries=[
            FinalizerPlanEntryWire(
                instance_id="commit",
                provider_ref="builtin@commit",
                after=[],
                policy=FinalizerInstancePolicyWire(),
                selector_index=0,
                resolved_index=0,
            )
        ],
        plan_digest="p" * 64,
        required=["commit"],
        selectors=[],
    )
    envelope = {
        "schema_version": 2,
        "payloads": [
            {
                "instance_id": "commit",
                "payload": {
                    "repositories": [
                        {
                            "repo_id": "repo-main",
                            "action": "commit",
                            "message": "fix: finish the change",
                        }
                    ],
                    "deferrals": [],
                },
            }
        ],
    }
    with pytest.raises(FinalizerDeclarationError, match="bead_action"):
        validate_provider_payloads(plan, context, envelope, host_records=())
    envelope["payloads"][0]["payload"]["repositories"][0]["bead_action"] = "keep"
    validate_provider_payloads(plan, context, envelope, host_records=())


def test_real_declaration_submit_is_not_stubbed_on_success_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    monkeypatch.setenv("SASE_WORKSPACE_NUM", "20")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    publication = publish_final_context(artifacts_dir=str(artifacts))
    repo_id = publication.context.obligations[0].obligation_id
    intent_ref = bind_prepared(monkeypatch, artifacts, [observation(repo_id)])
    write_stages(artifacts, check_full_stages())
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create",
        successful_stitch(artifacts, dirty, calls),
    )
    submits: list[dict[str, Any]] = []
    from sase.monitor import host_completion_state as host_state

    real_submit = host_state.submit_final_manifest

    def tracking_submit(manifest: Any, *, artifacts_dir: str | None = None) -> Any:
        submits.append(
            dict(manifest) if isinstance(manifest, dict) else {"raw": manifest}
        )
        return real_submit(manifest, artifacts_dir=artifacts_dir)

    monkeypatch.setattr(
        "sase.monitor.host_completion_state.submit_final_manifest", tracking_submit
    )

    result = settle_host_completion(
        str(artifacts),
        controller_meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=controller_recovery([]),
        release_claim=lambda *_a, **_k: None,
        capture=capture(),
        selected_action="complete",
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    assert submits, "host completion must submit the real declaration"
    assert "payloads" in submits[0]
    assert (artifacts / "final_submission.json").is_file()
