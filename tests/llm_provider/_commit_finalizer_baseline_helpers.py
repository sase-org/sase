"""Shared public helpers for commit-finalizer baseline tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.finalizers.commit_validation import protected_baseline_paths
from sase.llm_provider.commit_finalizer_state import collect_dirty_state

from sase.llm_provider.commit_finalizer_baseline import FINALIZER_BASELINE_FILENAME
from sase.llm_provider import commit_finalizer_git as finalizer_git

from ._commit_finalizer_sibling_helpers import init_git_repo

PRE_EXISTING_HEADER = "Pre-existing changes detected before this run started"


def init_git_repo_with_identity(repo: Path) -> None:
    init_git_repo(repo)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )


def write_finalizer_baseline_records(
    artifacts_dir: Path,
    records: list[dict[str, object]],
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps({"schema_version": 1, "repositories": records}),
        encoding="utf-8",
    )


def finalizer_baseline_record(
    *,
    repo_id: str,
    repo_path: Path,
    kind: str,
    name: str,
    scope: str,
    fingerprints: dict[str, tuple[str, str | None]],
    captured_at: str,
) -> dict[str, object]:
    return {
        "repo_id": repo_id,
        "path": finalizer_git.normalize_path(str(repo_path)),
        "kind": kind,
        "name": name,
        "scope": scope,
        "captured_at": captured_at,
        "fingerprints": {
            path: list(fingerprint) for path, fingerprint in fingerprints.items()
        },
    }


def use_git_dirty_details(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drive main-repo changes from real git status for baseline tests."""

    def build(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed_files = finalizer_git.git_changed_files(project_dir)
        if not changed_files:
            return (False, [], "", "")
        details = "Uncommitted changes detected:\n" + "\n".join(changed_files)
        return (True, changed_files, "commit", details)

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build,
    )


def dirty_details(project_dir: Path, artifacts_dir: Path) -> str:
    return collect_dirty_state(str(project_dir), artifact_root=artifacts_dir).details


def is_protected(artifacts_dir: Path, repo_path: Path, path: str) -> bool:
    return path in protected_baseline_paths(
        artifacts_dir,
        str(repo_path),
        get_changed_files=lambda _repo: [path],
    )
