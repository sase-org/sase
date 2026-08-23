"""Shared helpers for commit-reconciliation finalizer tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.finalizers.declaration import (
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
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


def dirty_state(repo: Path, *, dirty: bool) -> DirtyState:
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


def dirty_repo(
    path: Path,
    *,
    name: str = "main",
    kind: str = "main",
    changed_files: tuple[str, ...] = ("src/app.py",),
) -> DirtyRepo:
    return DirtyRepo(
        name=name,
        path=str(path),
        changed_files=changed_files,
        kind=kind,  # type: ignore[arg-type]
    )


def dirty_repos(project_dir: Path, repos: tuple[DirtyRepo, ...]) -> DirtyState:
    return DirtyState(
        project_dir=str(project_dir),
        repos=repos,
        details="dirty" if repos else "",
    )


def changed_files_for(path: str, repos: tuple[DirtyRepo, ...]) -> list[str]:
    for repo in repos:
        if repo.path == path:
            return list(repo.changed_files)
    return []


def fingerprints_for(
    path: str, repos: tuple[DirtyRepo, ...]
) -> dict[str, tuple[str, str]]:
    files = changed_files_for(path, repos)
    if not files:
        return {"src/app.py": ("M", "content")}
    return dict.fromkeys(files, ("M", "content"))


def patch_commit_state(
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
        lambda _root: dirty_state(repo, dirty=dirty["value"]),
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
            dirty_state=dirty_state(repo, dirty=dirty["value"]),
        ),
    )


def patch_multi_repo_state(
    monkeypatch: pytest.MonkeyPatch,
    project_dir: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.commit.resolve_finalizer_project_dir",
        lambda: str(project_dir),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: dirty_repos(project_dir, dirty["repos"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda path: fingerprints_for(path, dirty["repos"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.git_changed_files",
        lambda path: changed_files_for(path, dirty["repos"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state",
        lambda _project_dir, _artifacts: PreparedCommitDirtyState(
            dirty_state=dirty_repos(project_dir, dirty["repos"]),
        ),
    )


def write_commit_results(artifacts: Path, markers: list[dict[str, str]]) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "commit_results.json").write_text(
        json.dumps(markers),
        encoding="utf-8",
    )


def marker(
    cwd: Path, *, sha: str, tree: str, result: str | None = None
) -> dict[str, str]:
    return {
        "cwd": str(cwd),
        "result": result if result is not None else sha,
        "commit_sha": sha,
        "commit_tree": tree,
    }


def persist_and_submit_commit(
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
    for decision in manifest["payloads"][0]["payload"]["repositories"]:
        decision["action"] = action
        if action == "commit":
            decision["message"] = message
        else:
            decision.pop("message", None)
            decision["reason"] = reason
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))


def mixed_sidecar_files() -> tuple[str, ...]:
    return ("202608/report.md", "links/202608/one.md.json")


def fingerprints_for_files(*paths: str) -> dict[str, tuple[str, str]]:
    return dict.fromkeys(paths, ("M", "content"))


def spend_declaration_recovery(artifacts: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).write_text(
        "spent\n",
        encoding="utf-8",
    )
