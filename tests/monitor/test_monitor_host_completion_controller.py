"""Real controller and declaration coverage for host completion."""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from sase.core.continuation_facade import bind_conditional_completion
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.declaration import publish_final_context
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.prepare import (
    persist_prepared_completion,
    prepare_conditional_completion,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.monitor.delivery import load_host_completion_receipt
from sase.monitor.diagnostics import diagnostic_manifest_path
from sase.monitor.followup import launch_followup_agent
from sase.monitor.host_completion import (
    HOST_COMPLETION_IDENTITY,
    settle_host_completion,
)
from sase.monitor.output import OutputCapture
from sase.shells.followup import FollowupLaunchResult
from sase.xprompt.directives import PromptDirectives

from ..finalizer_declaration_channel_test_helpers import valid_manifest
from ..finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    successful_stitch,
)


def _capture() -> OutputCapture:
    return OutputCapture()


def _passed_stage(stage_id: str, name: str) -> dict[str, Any]:
    return {
        "stage_id": stage_id,
        "name": name,
        "status": "passed",
        "exit_code": 0,
        "diagnostic_refs": [],
        "counts": {},
        "retained_ranges": [],
        "capture_errors": [],
    }


def _check_full_stages() -> list[dict[str, Any]]:
    return [
        _passed_stage("formatting", "fmt (python)"),
        _passed_stage("ruff", "lint (ruff)"),
        _passed_stage("mypy", "lint (mypy)"),
        _passed_stage("validation", "SASE validation"),
        _passed_stage("full_tests", "test (full)"),
    ]


def _write_stages(artifacts: Path, stages: list[dict[str, Any]]) -> None:
    path = diagnostic_manifest_path(artifacts)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"schema_version": CONTINUATION_WIRE_SCHEMA_VERSION, "stages": stages}
        ),
        encoding="utf-8",
    )


def _observation(
    repo_id: str, *, name: str = "main", kind: str = "main"
) -> dict[str, Any]:
    digest = "a" * 64
    return {
        "repo_id": repo_id,
        "kind": kind,
        "name": name,
        "head": digest,
        "head_tree": digest,
        "index_tree": digest,
        "complete": True,
        "paths": [
            {
                "path": "src/app.py",
                "xy": "M",
                "content_hash": digest,
                "mode": "100644",
                "kind": "file",
                "protected": False,
                "foreign": False,
            }
        ],
    }


def _production_recovery(
    recoveries: list[str],
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
        del meta, elapsed_seconds, timeout_kind, transfer_from_pid
        missing = required - {
            "monitor_state",
            "exit_code",
            "elapsed_seconds",
            "capture",
            "project_name",
        }
        assert not missing
        assert monitor_state == "completed"
        assert exit_code == 0
        assert isinstance(capture, OutputCapture)
        assert project_name == "proj"
        recoveries.append(artifacts_dir)
        return FollowupLaunchResult(launched=True, agent_name="acme--2")

    return launch_recovery


def _meta(artifacts: Path, intent_ref: str) -> dict[str, Any]:
    return {
        "monitor_id": "monitor-1",
        "monitor_completion_ref": intent_ref,
        "monitor_profile": "verify",
        "monitor_command": "just check-full",
        "monitor_execution_argv": ["just", "check-full"],
        "workspace_dir": "/ws/20",
        "workspace_num": 20,
        "continuation_workspace_ref": "/ws/20",
        "continuation_monitor_result_id": "result-1",
        "monitor_next_action": "Diagnose failures or stale verification, then finish.",
        "name": "agent-1",
    }


def _bind_prepared(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    observations: list[dict[str, Any]],
) -> str:
    monkeypatch.setenv("SASE_WORKSPACE_NUM", "20")
    monkeypatch.setattr(
        "sase.finalizers.prepare.observe_completion_repositories",
        lambda _root: observations,
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion.observe_completion_repositories",
        lambda _root: observations,
        raising=False,
    )
    monkeypatch.setattr(
        "sase.monitor.host_completion_state.observe_completion_repositories",
        lambda _root: observations,
    )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    prepared = prepare_conditional_completion(
        {
            "success_message": "Required checks passed in {duration}.",
            "verification": {"command": ["just", "check-full"]},
            "declaration": valid_manifest(publication),
        },
        artifacts_dir=str(artifacts),
    )
    bound = bind_conditional_completion(
        {
            "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
            "intent": prepared.intent,
            "monitor_id": "monitor-1",
            "command": ["just", "check-full"],
            "request_fingerprint": "sha256:abc",
        }
    )
    persist_prepared_completion(bound, artifacts_dir=artifacts)
    return prepared.intent_ref


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
    observations = [_observation(repo_id)]
    intent_ref = _bind_prepared(monkeypatch, artifacts, observations)
    _write_stages(artifacts, _check_full_stages())
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_create",
        successful_stitch(artifacts, dirty, calls),
    )
    recoveries: list[str] = []
    invokes: list[str] = []

    def track_invoke(self: object, *args: object, **kwargs: object) -> None:
        del self, args, kwargs
        invokes.append("provider")
        raise AssertionError("no-model host completion must not invoke a provider")

    monkeypatch.setattr(
        "sase.monitor.host_completion._NoModelProvider.invoke", track_invoke
    )

    result = settle_host_completion(
        str(artifacts),
        _meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=182,
        project_name="proj",
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=_capture(),
        selected_action="complete",
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    assert result.launch_result.agent_name == HOST_COMPLETION_IDENTITY
    assert recoveries == []
    assert invokes == []
    assert calls == ["main"]
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "completed"
    assert "Required checks passed in 3m 02s." in str(receipt.get("published_message"))


@pytest.mark.parametrize(
    ("reason", "mutate"),
    [
        (
            "stale_worktree_fingerprint",
            lambda observations: observations.__setitem__(
                0, {**observations[0], "head": "b" * 64}
            ),
        ),
        (
            "missing_required_stage",
            lambda _observations: "drop-full-tests",
        ),
    ],
)
def test_stale_or_missing_checks_use_one_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    mutate: Any,
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
    observations = [_observation(repo_id)]
    intent_ref = _bind_prepared(monkeypatch, artifacts, list(observations))
    marker = mutate(observations)
    if marker == "drop-full-tests":
        _write_stages(artifacts, _check_full_stages()[:-1])
    else:
        monkeypatch.setattr(
            "sase.monitor.host_completion_state.observe_completion_repositories",
            lambda _root: observations,
        )
        _write_stages(artifacts, _check_full_stages())
    recoveries: list[str] = []

    result = settle_host_completion(
        str(artifacts),
        _meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=_capture(),
        selected_action="complete",
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.launched is True
    assert recoveries == [str(artifacts)]
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "recovery"
    assert reason in str(receipt.get("reason"))


def test_unsupported_finalizer_uses_one_recovery(
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
    intent_ref = _bind_prepared(monkeypatch, artifacts, [_observation(repo_id)])
    _write_stages(artifacts, _check_full_stages())
    monkeypatch.setattr(
        "sase.monitor.host_completion_state.executor_capabilities",
        lambda _plan: [
            {
                "instance_id": "audit",
                "provider_ref": "example-finalizers@audit",
                "headless": False,
                "durable_replay": False,
                "requires_model": True,
            }
        ],
    )
    recoveries: list[str] = []

    result = settle_host_completion(
        str(artifacts),
        _meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=_capture(),
        selected_action="complete",
    )

    assert result is not None
    assert recoveries == [str(artifacts)]
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "recovery"
    assert "unsupported_executor" in str(receipt.get("reason"))


def test_tree_drift_after_finalizers_uses_one_recovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    extra = tmp_path / "extra"
    extra.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    monkeypatch.setenv("SASE_WORKSPACE_NUM", "20")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (dirty_repo(repo),)}
    patch_dirty(monkeypatch, repo, dirty)
    publication = publish_final_context(artifacts_dir=str(artifacts))
    repo_id = publication.context.obligations[0].obligation_id
    intent_ref = _bind_prepared(monkeypatch, artifacts, [_observation(repo_id)])
    _write_stages(artifacts, _check_full_stages())
    calls: list[str] = []
    base_stitch = successful_stitch(artifacts, dirty, calls)

    def drifting_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        context: object,
    ) -> StitchCommandResult:
        result = base_stitch(repo_arg, message, excludes, context)
        dirty["repos"] = (dirty_repo(extra, name="extra", kind="sibling"),)
        return result

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", drifting_stitch)
    recoveries: list[str] = []

    result = settle_host_completion(
        str(artifacts),
        _meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=_capture(),
        selected_action="complete",
    )

    assert result is not None
    assert recoveries == [str(artifacts)]
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "recovery"
    reason = str(receipt.get("reason") or "")
    assert "new_repository_obligation" in reason or "uncommitted changes" in reason
    assert receipt.get("commit_receipts")


def test_two_repository_partial_crash_retains_receipts_and_does_not_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    prepare_agent_env(monkeypatch, artifacts, repo)
    monkeypatch.setenv("SASE_WORKSPACE_NUM", "20")
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(repo, name="main", kind="main"),
            dirty_repo(linked, name="plans", kind="sibling"),
        )
    }
    patch_dirty(monkeypatch, repo, dirty)
    publication = publish_final_context(artifacts_dir=str(artifacts))
    observations = [
        _observation(item.obligation_id, name=item.display_name or item.obligation_id)
        for item in publication.context.obligations
        if item.kind == "repository"
    ]
    intent_ref = _bind_prepared(monkeypatch, artifacts, observations)
    _write_stages(artifacts, _check_full_stages())
    calls: list[str] = []

    def crashing_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        context: object,
    ) -> StitchCommandResult:
        del message, excludes, context
        calls.append(repo_arg.name)
        remaining = tuple(item for item in dirty["repos"] if item.path != repo_arg.path)
        dirty["repos"] = remaining
        payload = []
        existing = artifacts / "commit_results.json"
        if existing.is_file():
            payload = json.loads(existing.read_text(encoding="utf-8"))
        payload.append(
            {
                "cwd": repo_arg.path,
                "result": "ok",
                "commit_sha": "a" * 40,
                "commit_tree": "b" * 40,
            }
        )
        existing.write_text(json.dumps(payload), encoding="utf-8")
        if len(calls) == 1:
            raise RuntimeError("crash after first repository")
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", crashing_stitch)
    recoveries: list[str] = []
    meta = _meta(artifacts, intent_ref)

    result = settle_host_completion(
        str(artifacts),
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=_capture(),
        selected_action="complete",
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is not True
    assert recoveries == [str(artifacts)]
    receipt = load_host_completion_receipt(artifacts)
    assert receipt is not None
    assert receipt["status"] == "recovery"
    markers = receipt.get("commit_receipts") or []
    assert len(markers) == 1
    assert markers[0]["result"] == "ok"

    second = settle_host_completion(
        str(artifacts),
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=_production_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=_capture(),
        selected_action="complete",
    )
    second_receipt = load_host_completion_receipt(artifacts)
    assert second_receipt is not None
    assert second_receipt["status"] != "completed"
    if second is not None and second.launch_result is not None:
        assert second.launch_result.host_completed is not True


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
        validate_provider_payloads(plan, context, envelope)
    envelope["payloads"][0]["payload"]["repositories"][0]["bead_action"] = "keep"
    validate_provider_payloads(plan, context, envelope)


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
    intent_ref = _bind_prepared(monkeypatch, artifacts, [_observation(repo_id)])
    _write_stages(artifacts, _check_full_stages())
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_create",
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
        _meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=_production_recovery([]),
        release_claim=lambda *_a, **_k: None,
        capture=_capture(),
        selected_action="complete",
    )

    assert result is not None
    assert result.launch_result is not None
    assert result.launch_result.host_completed is True
    assert submits, "host completion must submit the real declaration"
    assert "payloads" in submits[0]
    assert (artifacts / "final_submission.json").is_file()
