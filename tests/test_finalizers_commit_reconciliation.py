"""Commit reconciliation coverage for the finalizer controller."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.declaration import (
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import (
    DirtyRepo,
    DirtyState,
)
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives


def _prepare_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    repo: Path,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(repo))


def _dirty_state(repo: Path, *, dirty: bool) -> DirtyState:
    if not dirty:
        return DirtyState(project_dir=str(repo), repos=(), details="")
    return DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=("src/app.py",),
                kind="main",
            ),
        ),
        details="dirty",
    )


def _patch_commit_state(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    dirty: dict[str, bool],
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.commit.resolve_finalizer_project_dir",
        lambda: str(repo),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(repo, dirty=dirty["value"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "content")},
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.git_changed_files",
        lambda _path: ["src/app.py"] if dirty["value"] else [],
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state",
        lambda _project_dir, _artifacts: PreparedCommitDirtyState(
            dirty_state=_dirty_state(repo, dirty=dirty["value"]),
        ),
    )


def _persist_and_submit_commit(
    artifacts: Path,
    *,
    action: str = "commit",
    message: str = "fix(final): reconcile commit declaration",
    reason: str = "operator refused dirty work",
) -> None:
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = publication.payload["manifest_template"]
    decision = manifest["payloads"][0]["payload"]["repositories"][0]
    decision["action"] = action
    if action == "commit":
        decision["message"] = message
    else:
        decision.pop("message", None)
        decision["reason"] = reason
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))


def test_builtin_commit_executes_declared_stitch_without_reprompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, artifacts, repo)
    _patch_commit_state(monkeypatch, repo, dirty)
    calls: list[tuple[DirtyRepo, str, tuple[str, ...]]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append((repo_arg, message, tuple(excludes)))
        dirty["value"] = False
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": str(repo),
                        "result": "abc123",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    provider = MagicMock()

    _persist_and_submit_commit(artifacts)
    result = run_finalizers(
        provider=provider,
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    provider.invoke.assert_not_called()
    assert [(call[0].name, call[1], call[2]) for call in calls] == [
        ("main", "fix(final): reconcile commit declaration", ())
    ]
    assert not (artifacts / "commit_finalizer_result.json").exists()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    assert aggregate["instances"][0]["evidence"][0]["kind"] == "cwd"


def test_builtin_commit_refusal_fails_without_running_stitch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, artifacts, repo)
    _patch_commit_state(monkeypatch, repo, dirty)
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts, action="refuse", reason="not mine")
    with pytest.raises(BuiltinCommitFinalizerError, match="not mine"):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    runner.assert_not_called()
    assert not (artifacts / "commit_finalizer_result.json").exists()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "refused"
    assert aggregate["instances"][0]["refusal_reason"] == "not mine"


def test_post_submit_cleanup_fails_without_proven_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, artifacts, repo)
    _patch_commit_state(monkeypatch, repo, dirty)
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts)
    dirty["value"] = False
    with pytest.raises(
        BuiltinCommitFinalizerError,
        match="vanished|discarded|attributable",
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

    runner.assert_not_called()


def test_stale_commit_results_do_not_prove_clean_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, artifacts, repo)
    _patch_commit_state(monkeypatch, repo, dirty)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "cwd": str(repo),
                    "result": "old",
                    "commit_sha": "a" * 40,
                    "commit_tree": "b" * 40,
                }
            ]
        ),
        encoding="utf-8",
    )
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts)
    dirty["value"] = False
    with pytest.raises(
        BuiltinCommitFinalizerError,
        match="vanished|discarded|attributable",
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

    runner.assert_not_called()
