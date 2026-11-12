"""Real-controller host completion: recovery and crash-safety paths."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.declaration import publish_final_context
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.macro.directives import PromptDirectives
from sase.monitor.delivery import load_host_completion_receipt
from sase.monitor.host_completion import settle_host_completion

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
    "test_stale_or_missing_checks_use_one_recovery",
    "test_tree_drift_after_finalizers_uses_one_recovery",
    "test_two_repository_partial_crash_retains_receipts_and_does_not_complete",
    "test_unsupported_finalizer_uses_one_recovery",
]


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
    observations = [observation(repo_id)]
    intent_ref = bind_prepared(monkeypatch, artifacts, list(observations))
    marker = mutate(observations)
    if marker == "drop-full-tests":
        write_stages(artifacts, check_full_stages()[:-1])
    else:
        monkeypatch.setattr(
            "sase.monitor.host_completion_state.observe_completion_repositories",
            lambda _root: observations,
        )
        write_stages(artifacts, check_full_stages())
    recoveries: list[str] = []

    result = settle_host_completion(
        str(artifacts),
        controller_meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=controller_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=capture(),
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
    if reason == "stale_worktree_fingerprint":
        assert receipt["fingerprint_differences_recorded"] is True
        assert receipt["fingerprint_differences"]["items"] == [
            {
                "repo_id": repo_id,
                "repo_name": "main",
                "repo_kind": "main",
                "component": "head",
                "path": None,
                "expected": "a" * 64,
                "observed": "b" * 64,
            }
        ]


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
    intent_ref = bind_prepared(monkeypatch, artifacts, [observation(repo_id)])
    write_stages(artifacts, check_full_stages())
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
        controller_meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=controller_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=capture(),
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
    intent_ref = bind_prepared(monkeypatch, artifacts, [observation(repo_id)])
    write_stages(artifacts, check_full_stages())
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

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", drifting_stitch
    )
    recoveries: list[str] = []

    result = settle_host_completion(
        str(artifacts),
        controller_meta(artifacts, intent_ref),
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=controller_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=capture(),
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
        observation(item.obligation_id, name=item.display_name or item.obligation_id)
        for item in publication.context.obligations
        if item.kind == "repository"
    ]
    intent_ref = bind_prepared(monkeypatch, artifacts, observations)
    write_stages(artifacts, check_full_stages())
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

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", crashing_stitch
    )
    recoveries: list[str] = []
    meta = controller_meta(artifacts, intent_ref)

    result = settle_host_completion(
        str(artifacts),
        meta,
        monitor_state="completed",
        exit_code=0,
        elapsed_seconds=12,
        project_name="proj",
        launch_recovery=controller_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=capture(),
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
        launch_recovery=controller_recovery(recoveries),
        release_claim=lambda *_a, **_k: None,
        capture=capture(),
        selected_action="complete",
    )
    second_receipt = load_host_completion_receipt(artifacts)
    assert second_receipt is not None
    assert second_receipt["status"] != "completed"
    if second is not None and second.launch_result is not None:
        assert second.launch_result.host_completed is not True
