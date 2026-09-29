"""Declared stitch-commit behavior for legacy artifact-link index dirt."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.finalizers.commit import BuiltinCommitFinalizerError, StitchCommandResult
from sase.finalizers.controller import run_finalizers
from sase.finalizers.declaration import (
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.reconciliation import prepare_commit_dirty_state
from sase.linked_repos import LINKED_REPOS_JSON_ENV
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives
from tests._conftest_environment import redirect_sase_home

from ._commit_finalizer_artifact_links_helpers import (
    create_primary,
    create_sidecar,
    record_reads,
    run_git,
    sdd_store,
    set_finalizer_env,
)


def _append_commit_result(artifacts: Path, repo_path: str, sha: str, tree: str) -> None:
    path = artifacts / "commit_results.json"
    payload: list[dict[str, str]] = []
    if path.is_file():
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, list):
            payload = [item for item in loaded if isinstance(item, dict)]
    payload.append(
        {
            "cwd": repo_path,
            "result": sha,
            "commit_sha": sha,
            "commit_tree": tree,
        }
    )
    path.write_text(json.dumps(payload), encoding="utf-8")


def _commit_remaining_stitch(
    repo: DirtyRepo,
    message: str,
    excludes: tuple[str, ...],
    context: object,
) -> StitchCommandResult:
    excluded = set(excludes)
    to_commit = [
        path
        for path in finalizer_git.git_changed_files(repo.path)
        if path not in excluded
    ]
    if not to_commit:
        return StitchCommandResult(returncode=1, stderr="nothing to commit\n")
    added = subprocess.run(
        ["git", "add", "--", *to_commit],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
    )
    if added.returncode != 0:
        return StitchCommandResult(
            returncode=added.returncode,
            stdout=added.stdout,
            stderr=added.stderr,
        )
    committed = subprocess.run(
        ["git", "commit", "-q", "-m", message],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=False,
    )
    if committed.returncode != 0:
        return StitchCommandResult(
            returncode=committed.returncode,
            stdout=committed.stdout,
            stderr=committed.stderr,
        )
    sha = run_git(Path(repo.path), "rev-parse", "HEAD").strip()
    tree = run_git(Path(repo.path), "rev-parse", "HEAD^{tree}").strip()
    artifacts_dir = getattr(context, "artifacts_dir", None)
    if artifacts_dir:
        _append_commit_result(Path(artifacts_dir), repo.path, sha, tree)
    return StitchCommandResult(returncode=0, stdout=f"{sha}\n")


def _commit_without_marker_stitch(
    repo: DirtyRepo,
    message: str,
    excludes: tuple[str, ...],
) -> StitchCommandResult:
    excluded = set(excludes)
    to_commit = [
        path
        for path in finalizer_git.git_changed_files(repo.path)
        if path not in excluded
    ]
    if not to_commit:
        return StitchCommandResult(returncode=1, stderr="nothing to commit\n")
    subprocess.run(
        ["git", "add", "--", *to_commit],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-q", "-m", message],
        cwd=repo.path,
        capture_output=True,
        text=True,
        check=True,
    )
    sha = run_git(Path(repo.path), "rev-parse", "HEAD").strip()
    return StitchCommandResult(returncode=0, stdout=f"{sha}\n")


def test_executor_commits_declared_legacy_link_index_through_stitch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Legacy link-index dirt is now a regular declared commit obligation."""
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
    plans = create_sidecar(tmp_path, "plans")
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv(LINKED_REPOS_JSON_ENV, "[]")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: sdd_store(plans)
    )
    record_reads(plans, "plan:202608/one.md")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    plans_cwd = str(plans.expanduser().resolve())
    stitch_calls: list[tuple[str, tuple[str, ...]]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        context: object,
    ) -> StitchCommandResult:
        stitch_calls.append((repo_arg.name, repo_arg.changed_files))
        return _commit_remaining_stitch(repo_arg, message, excludes, context)

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", run_stitch
    )

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    assert repositories, "plans sidecar should be a commit obligation"
    for decision in repositories:
        decision["action"] = "commit"
        decision["message"] = "chore(artifact-links): persist link indexes"
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))

    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    assert len(stitch_calls) == 1
    assert any(path.endswith("one.md.json") for path in stitch_calls[0][1])
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    assert "chore(artifact-links): persist link indexes" in run_git(
        plans, "log", "-1", "--pretty=%s"
    )
    markers = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    assert any(item.get("cwd") == plans_cwd for item in markers)
    assert run_git(plans, "status", "--porcelain", "--untracked-files=all") == ""


def test_executor_rejects_artifact_link_auto_commit_without_new_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
    plans = create_sidecar(tmp_path, "plans")
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv(LINKED_REPOS_JSON_ENV, "[]")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: sdd_store(plans)
    )
    record_reads(plans, "plan:202608/one.md")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    real_prepare = prepare_commit_dirty_state

    def prepare_without_ledger(project_dir: str, artifacts_dir: Path):
        before = []
        existing = artifacts / "commit_results.json"
        if existing.is_file():
            before = json.loads(existing.read_text(encoding="utf-8"))
        state = real_prepare(project_dir, artifacts_dir)
        existing.write_text(json.dumps(before), encoding="utf-8")
        return state

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.prepare_commit_dirty_state",
        prepare_without_ledger,
    )
    stitch_calls: list[tuple[str, tuple[str, ...]]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        stitch_calls.append((repo_arg.name, repo_arg.changed_files))
        return _commit_without_marker_stitch(repo_arg, message, excludes)

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", run_stitch
    )

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    for decision in manifest["payloads"][0]["payload"]["repositories"]:
        decision["action"] = "commit"
        decision["message"] = "chore(artifact-links): persist link indexes"
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))

    with pytest.raises(
        BuiltinCommitFinalizerError,
        match="commit_results\\.json entry was recorded",
    ):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    assert len(stitch_calls) == 1
    assert "chore(artifact-links): persist link indexes" in run_git(
        plans, "log", "-1", "--pretty=%s"
    )


def test_executor_commits_mixed_report_and_legacy_link_index_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mixed sidecar dirt is handled by the declared stitch commit."""
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
    plans = create_sidecar(tmp_path, "plans")
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv(LINKED_REPOS_JSON_ENV, "[]")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: sdd_store(plans)
    )
    record_reads(plans, "plan:202608/one.md")
    report = plans / "202608" / "report.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("# mixed report\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    stitch_calls: list[tuple[str, tuple[str, ...]]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        context: object,
    ) -> StitchCommandResult:
        stitch_calls.append((repo_arg.name, repo_arg.changed_files))
        return _commit_remaining_stitch(repo_arg, message, excludes, context)

    monkeypatch.setattr(
        "sase.finalizers.commit_execution.run_stitch_create", run_stitch
    )

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    assert repositories, "plans sidecar should be a commit obligation"
    for decision in repositories:
        decision["action"] = "commit"
        decision["message"] = "docs: add mixed reconciliation report"
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))

    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    assert len(stitch_calls) == 1
    assert any(path.endswith("report.md") for path in stitch_calls[0][1])
    assert any(path.endswith("one.md.json") for path in stitch_calls[0][1])
    assert not (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).exists()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    subjects = run_git(plans, "log", "--pretty=%s")
    assert "docs: add mixed reconciliation report" in subjects
    tracked = run_git(plans, "ls-files")
    assert "links/202608/one.md.json" in tracked
    assert "202608/report.md" in tracked
    assert run_git(plans, "status", "--porcelain", "--untracked-files=all") == ""
    markers = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    plans_cwd = str(plans.expanduser().resolve())
    matching = [item for item in markers if item.get("cwd") == plans_cwd]
    assert len(matching) == 1
