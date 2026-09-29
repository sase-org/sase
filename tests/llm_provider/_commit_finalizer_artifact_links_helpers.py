"""Shared helpers for commit-finalizer artifact-link tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)
from sase.sdd.store import SddStore
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV


def run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )


def commit_all(repo: Path, message: str = "initial") -> None:
    run_git(repo, "add", ".")
    run_git(repo, "commit", "-q", "-m", message)


def create_primary(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    _init_git(main)
    (main / "README.md").write_text("main\n", encoding="utf-8")
    commit_all(main)
    return main


def create_sidecar(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    _init_git(repo)
    (repo / "README.md").write_text(f"{name}\n", encoding="utf-8")
    commit_all(repo)
    return repo


def set_finalizer_env(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260821_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)

    def build(path: str) -> tuple[bool, list[str], str, str]:
        changed = finalizer_git.git_changed_files(path)
        if not changed:
            return (False, [], "", "")
        return (True, changed, "commit", "Uncommitted changes detected")

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )


def sdd_store(plans: Path, research: Path | None = None) -> SddStore:
    sidecar_dirs = {"research": research} if research is not None else {}
    return SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        sidecar_dirs=sidecar_dirs,
    )


def read_row(target: str) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": "agent:alice.athena.09l",
        "relation": "read",
        "target_ref": target,
        "description": "Need the plan context",
        "origin": "read",
        "created_by": "alice.athena.09l",
        "created_at": "2026-08-21T12:00:00Z",
        "uses": 1,
    }


def record_reads(plans: Path, *targets: str) -> ArtifactLinkStore:
    """Materialize already-dirty link-index rows directly in the sidecar.

    A bare ``sase artifact read`` no longer writes synchronously (see
    ``test_two_implicit_plan_reads_produce_no_dirt_or_commit``), so
    this helper now stands in for whatever *does* still write a link index
    directly -- an explicit ``sase artifact link`` mutation, a backfill
    repair, or dirt left over from before this run. The reconciliation
    machinery under test does not care why an index is dirty, only that it
    is, so this remains meaningful coverage of that machinery.
    """
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    for target in targets:
        store.upsert_row(read_row(target))
    return store
