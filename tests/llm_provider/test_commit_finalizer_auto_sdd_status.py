"""Auto-commit coverage for generated SDD plan done status changes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.reconciliation import (
    auto_commit_separate_sdd_store_if_possible as _auto_commit_separate_sdd_store_if_possible,
    prepare_commit_dirty_state,
)
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider import commit_finalizer_git_status as finalizer_git_status
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV, record_opened_sibling
from tests.sdd_policy_helpers import set_sdd_policy

_PLAN_WIP = """---
title: Test plan
status: wip
---

Original body.
"""

_PLAN_DONE = """---
title: Test plan
status: done
---

Original body.
"""


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", message)


def _create_repo_with_plan(repo: Path) -> Path:
    _init_git_repo(repo)
    plan = repo / "sdd" / "plans" / "test_plan.md"
    plan.parent.mkdir(parents=True)
    plan.write_text(_PLAN_WIP, encoding="utf-8")
    _commit_all(repo, "initial")
    return plan


def _create_clean_repo_with_ignored_sdd_store(repo: Path) -> Path:
    _init_git_repo(repo)
    (repo / ".gitignore").write_text(".sase/\n", encoding="utf-8")
    _commit_all(repo, "initial")

    sdd_store = repo / ".sase" / "sdd"
    _init_git_repo(sdd_store)
    (sdd_store / "README.md").write_text("seed\n", encoding="utf-8")
    _commit_all(sdd_store, "initial sdd")
    return sdd_store


def _set_agent_env(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260528_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)


def _use_git_dirty_details(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _use_separate_sdd_store_config(monkeypatch: pytest.MonkeyPatch) -> None:
    set_sdd_policy(monkeypatch, "separate_repo")
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )


def _prepare(artifacts_dir: Path):
    return prepare_commit_dirty_state(
        resolve_finalizer_project_dir(),
        artifacts_dir,
    )


def test_done_status_only_sdd_plan_change_is_auto_committed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    plan = _create_repo_with_plan(repo)
    plan.write_text(_PLAN_DONE, encoding="utf-8")
    _set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    state = _prepare(artifacts_dir)

    assert state.dirty_state.is_clean
    assert state.done_plan_auto_committed is True
    assert _run_git(repo, "status", "--short") == ""
    commit_message = _run_git(repo, "log", "-1", "--pretty=%B")
    assert "chore: Mark SDD plan done" in commit_message
    assert "SASE_TYPE=sdd" in commit_message


def test_auto_commit_git_runner_recovers_stale_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    _init_git_repo(repo)
    path = repo / "plan.md"
    path.write_text("plan\n", encoding="utf-8")
    lock = repo / ".git" / "index.lock"
    lock.write_text("stale", encoding="utf-8")
    monkeypatch.setenv("SASE_GIT_LOCK_RETRY_DELAYS", "0.001,0.001")

    result = finalizer_git_status.run_git(str(repo), ["add", "plan.md"])

    assert result is not None
    assert result.returncode == 0
    assert not lock.exists()
    assert _run_git(repo, "diff", "--cached", "--name-only").strip() == "plan.md"


def test_additional_dirty_file_uses_provider_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    plan = _create_repo_with_plan(repo)
    extra = repo / "src" / "extra.py"
    extra.parent.mkdir()
    extra.write_text("VALUE = 1\n", encoding="utf-8")
    _commit_all(repo, "add extra")
    plan.write_text(_PLAN_DONE, encoding="utf-8")
    extra.write_text("VALUE = 2\n", encoding="utf-8")
    _set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    state = _prepare(artifacts_dir)

    assert not state.dirty_state.is_clean
    remaining = [
        path
        for repo_item in state.dirty_state.repos
        for path in repo_item.changed_files
    ]
    assert any(path.endswith("extra.py") for path in remaining)


def test_non_status_sdd_markdown_change_uses_provider_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    plan = _create_repo_with_plan(repo)
    changed_body = _PLAN_WIP.replace("Original body.", "Updated body.")
    plan.write_text(changed_body, encoding="utf-8")
    _set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    state = _prepare(artifacts_dir)

    assert not state.dirty_state.is_clean
    remaining = [
        path
        for repo_item in state.dirty_state.repos
        for path in repo_item.changed_files
    ]
    assert any("test_plan.md" in path for path in remaining)


def test_sibling_done_status_change_uses_provider_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    main.mkdir()
    sibling = tmp_path / "sase-core_10"
    plan = _create_repo_with_plan(sibling)
    plan.write_text(_PLAN_DONE, encoding="utf-8")
    _set_agent_env(monkeypatch, main)
    _use_git_dirty_details(monkeypatch)
    monkeypatch.setenv(
        SIBLING_REPOS_JSON_ENV,
        json.dumps([{"name": "core", "workspace_dir": str(sibling)}]),
    )
    artifacts_dir = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    record_opened_sibling("core", str(sibling))
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    state = _prepare(artifacts_dir)

    assert not state.dirty_state.is_clean
    assert any(item.path == str(sibling.resolve()) for item in state.dirty_state.repos)


def test_dirty_separate_sdd_store_is_auto_committed_when_main_repo_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    sdd_store = _create_clean_repo_with_ignored_sdd_store(repo)
    beads = sdd_store / "beads" / "issues.jsonl"
    beads.parent.mkdir()
    beads.write_text('{"id":"beads-1"}\n', encoding="utf-8")
    _set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    _use_separate_sdd_store_config(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    state = _prepare(artifacts_dir)

    assert state.sdd_store_auto_committed is True
    assert state.dirty_state.is_clean
    assert _run_git(repo, "status", "--short") == ""
    assert _run_git(sdd_store, "status", "--short") == ""
    commit_message = _run_git(sdd_store, "log", "-1", "--pretty=%B")
    assert "chore(beads): sync bead state" in commit_message
    assert "SASE_TYPE=beads" in commit_message


def test_split_sdd_store_auto_commit_targets_only_bead_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd.store import SddStore, write_sdd_store_record

    plans = tmp_path / "sase" / "repos" / "plans"
    research = tmp_path / "sase" / "repos" / "research"
    beads = tmp_path / "sase" / "repos" / "beads"
    (beads / ".git").mkdir(parents=True)
    write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/project--plans",
                    "remote_url": "git@example.com:acme/project--plans.git",
                },
                "research": {
                    "repo": "acme/project--research",
                    "remote_url": "git@example.com:acme/project--research.git",
                },
                "beads": {
                    "repo": "acme/project--beads",
                    "remote_url": "git@example.com:acme/project--beads.git",
                },
            },
        },
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.com:acme/project--plans.git",
        sidecar_dirs={"research": research},
        sidecar_remote_urls={"research": "git@example.com:acme/project--research.git"},
        beads_dir=beads,
    )
    commit = MagicMock(return_value=True)
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", lambda _root: False)

    assert _auto_commit_separate_sdd_store_if_possible(str(tmp_path)).committed
    commit.assert_called_once_with(
        store,
        "chore(beads): sync bead state",
        auto_commit_type="beads",
        paths=[beads],
        artifacts_dir=None,
    )


def test_clean_bead_state_skips_finalizer_retry_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd.store import SddStore, write_sdd_store_record

    plans = tmp_path / "sase" / "repos" / "plans"
    research = tmp_path / "sase" / "repos" / "research"
    beads = tmp_path / "sase" / "repos" / "beads"
    (beads / ".git").mkdir(parents=True)
    write_sdd_store_record(
        tmp_path,
        {
            "schema_version": 3,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                "plans": {
                    "repo": "acme/project--plans",
                    "remote_url": "git@example.com:acme/project--plans.git",
                },
                "research": {
                    "repo": "acme/project--research",
                    "remote_url": "git@example.com:acme/project--research.git",
                },
                "beads": {
                    "repo": "acme/project--beads",
                    "remote_url": "git@example.com:acme/project--beads.git",
                },
            },
        },
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        sidecar_dirs={"research": research},
        beads_dir=beads,
    )
    commit = MagicMock(return_value=True)
    clean = MagicMock(side_effect=[False, True])
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)
    monkeypatch.setattr("sase.sdd.files.commit_sdd_store_files", commit)
    monkeypatch.setattr("sase.bead.sync.bead_state_is_clean", clean)

    assert _auto_commit_separate_sdd_store_if_possible(str(tmp_path)).committed
    assert not _auto_commit_separate_sdd_store_if_possible(str(tmp_path)).committed

    assert clean.call_count == 2
    commit.assert_called_once_with(
        store,
        "chore(beads): sync bead state",
        auto_commit_type="beads",
        paths=[beads],
        artifacts_dir=None,
    )


def test_dirty_separate_sdd_non_bead_file_is_prompted_and_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "sase_10"
    sdd_store = _create_clean_repo_with_ignored_sdd_store(repo)
    report = sdd_store / "research" / "report.md"
    report.parent.mkdir()
    report.write_text("agent-authored report\n", encoding="utf-8")
    _set_agent_env(monkeypatch, repo)
    _use_git_dirty_details(monkeypatch)
    _use_separate_sdd_store_config(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"

    dirty_state = collect_dirty_state(str(repo), artifact_root=artifacts_dir)

    assert [
        (item.kind, item.name, item.changed_files) for item in dirty_state.repos
    ] == [("sdd", "sdd", ("research/report.md",))]
    assert f"SDD sidecar repo sdd: {sdd_store.resolve()}" in dirty_state.details
    assert f"cd {sdd_store.resolve()}" in dirty_state.details
    assert "/sase_git_commit" in dirty_state.details
    assert "git status --short --branch" in dirty_state.details
    assert _run_git(sdd_store, "status", "--short") == "?? research/\n"
