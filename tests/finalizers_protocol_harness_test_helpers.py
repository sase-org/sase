"""Shared helpers for generic-controller finalizer protocol tests."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import StitchCommandResult
from sase.finalizers.controller import run_finalizers
from sase.finalizers.declaration import (
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives


def prepare_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    repo: Path,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(repo))


def dirty_state(
    repos: tuple[DirtyRepo, ...],
    *,
    project_dir: Path,
) -> DirtyState:
    return DirtyState(
        project_dir=str(project_dir),
        repos=repos,
        details="dirty" if repos else "",
    )


def dirty_repo(path: Path, *, name: str = "main", kind: str = "main") -> DirtyRepo:
    return DirtyRepo(
        name=name,
        path=str(path),
        changed_files=("src/app.py",),
        kind=kind,  # type: ignore[arg-type]
    )


def patch_dirty(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
) -> None:
    def collect(_project_dir: str, artifact_root: object = None) -> DirtyState:
        return dirty_state(dirty["repos"], project_dir=repo)

    monkeypatch.setattr(
        "sase.finalizers.commit.resolve_finalizer_project_dir",
        lambda: str(repo),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: collect(str(repo)),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "content")},
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.git_changed_files",
        lambda path: (
            ["src/app.py"] if any(item.path == path for item in dirty["repos"]) else []
        ),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state",
        lambda _project_dir, _artifacts: PreparedCommitDirtyState(
            dirty_state=collect(str(repo)),
        ),
    )


def submit_commit(
    artifacts: Path,
    *,
    action: str = "commit",
    reverse_repositories: bool = False,
) -> None:
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    if reverse_repositories:
        repositories.reverse()
    for decision in repositories:
        decision["action"] = action
        if action == "commit":
            decision["message"] = "fix(final): reconcile commit declaration"
        else:
            decision.pop("message", None)
            decision["reason"] = "not mine"
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))


def run_controller(artifacts: Path, provider: MagicMock | None = None) -> InvokeResult:
    return run_finalizers(
        provider=provider or MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )


def successful_stitch(
    artifacts: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
    calls: list[str],
) -> Any:
    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
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
        return StitchCommandResult(returncode=0, stdout="ok\n")

    return run_stitch
