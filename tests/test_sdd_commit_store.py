"""Tests for committing SDD store files."""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sase.sdd.files import commit_sdd_store_files
from sase.sdd._git_contention import store_git_write_lock
from sase.sdd._repository_transaction import require_sdd_repository_health
from sase.sdd.store import SddStore
from tests._sdd_commit_helpers import init_test_git_repo


@pytest.mark.parametrize(
    ("mode", "async_remote", "sync_error", "expected_sync", "expected_async"),
    [
        (True, True, None, 1, 0),
        (False, True, None, 0, 0),
        ("async", True, None, 0, 1),
        ("async", False, None, 0, 1),
        (True, True, "push failed", 1, 0),
    ],
)
def test_commit_sdd_store_files_push_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: bool | str,
    async_remote: bool,
    sync_error: str | None,
    expected_sync: int,
    expected_async: int,
) -> None:
    store = SddStore(
        storage="separate_repo",
        sdd_dir=tmp_path,
        repo_root=tmp_path,
        remote_url="git@example.com:owner/repo-sdd.git" if async_remote else None,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": mode}},
    )
    monkeypatch.setattr("sase.sdd._commit.commit_sdd_files", lambda *a, **k: True)
    sync_calls: list[Path] = []
    async_calls: list[Path] = []

    def fake_sync(path: Path) -> SimpleNamespace:
        sync_calls.append(path)
        return SimpleNamespace(pushed=sync_error is None, error=sync_error)

    def fake_async(path: Path) -> SimpleNamespace | None:
        async_calls.append(path)
        if not async_remote:
            return None
        return SimpleNamespace(pid=123, log_path=tmp_path / "push.log")

    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_sync)
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch_async", fake_async)

    assert commit_sdd_store_files(store, "Commit SDD") is True
    assert sync_calls == [tmp_path] * expected_sync
    assert async_calls == [tmp_path] * expected_async


def test_commit_sdd_store_files_does_not_push_local_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = SddStore(storage="local", sdd_dir=tmp_path, repo_root=tmp_path)
    monkeypatch.setattr("sase.sdd._commit.commit_sdd_files", lambda *a, **k: True)
    sync = MagicMock()
    async_push = MagicMock()
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", sync)
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch_async", async_push)

    assert commit_sdd_store_files(store, "Commit SDD") is True
    sync.assert_not_called()
    async_push.assert_not_called()


def test_commit_sdd_store_files_routes_split_paths_to_owning_repos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = tmp_path / "project--plans"
    research = tmp_path / "project--research"
    beads = tmp_path / "project--beads"
    init_test_git_repo(plans)
    init_test_git_repo(research)
    init_test_git_repo(beads)
    plan = plans / "202607" / "plan.md"
    report = research / "202607" / "report.md"
    issue = beads / "issues.jsonl"
    plan.parent.mkdir()
    report.parent.mkdir()
    plan.write_text("# Plan\n", encoding="utf-8")
    report.write_text("# Research\n", encoding="utf-8")
    issue.write_text('{"id":"project-1"}\n', encoding="utf-8")
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.com:acme/project--plans.git",
        research_dir=research,
        research_remote_url="git@example.com:acme/project--research.git",
        beads_dir=beads,
    )

    assert commit_sdd_store_files(
        store,
        "Commit split SDD",
        paths=[plan, report, issue],
    )

    assert subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=plans,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines() == ["202607/plan.md"]
    assert subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=research,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines() == ["202607/report.md"]
    assert subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=beads,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines() == ["issues.jsonl"]


def test_commit_sdd_store_files_pushes_each_changed_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = tmp_path / "project--plans"
    research = tmp_path / "project--research"
    beads = tmp_path / "project--beads"
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.com:acme/project--plans.git",
        research_dir=research,
        research_remote_url="git@example.com:acme/project--research.git",
        beads_dir=beads,
    )
    commit_roots: list[Path] = []
    pushed_roots: list[Path] = []

    def fake_commit(root: Path, *_args: object, **_kwargs: object) -> bool:
        commit_roots.append(root)
        return True

    def fake_push(root: Path) -> SimpleNamespace:
        pushed_roots.append(root)
        return SimpleNamespace(pushed=True, error=None)

    monkeypatch.setattr("sase.sdd._commit.commit_sdd_files", fake_commit)
    monkeypatch.setattr("sase.bead.sync.push_bead_work_launch", fake_push)

    assert commit_sdd_store_files(
        store,
        "Commit split SDD",
        push_after_commit=True,
    )
    assert commit_roots == [plans, research, beads]
    assert pushed_roots == [plans, research, beads]


def test_beads_lock_and_health_state_do_not_block_plans_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plans = tmp_path / "project--plans"
    beads = tmp_path / "project--beads"
    init_test_git_repo(plans)
    init_test_git_repo(beads)
    plan = plans / "202607" / "plan.md"
    plan.parent.mkdir()
    plan.write_text("# Plan\n", encoding="utf-8")
    (beads / ".git" / "MERGE_HEAD").write_text("wedged\n", encoding="utf-8")
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        remote_url="git@example.com:acme/project--plans.git",
        beads_dir=beads,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )

    with store_git_write_lock(beads, timeout=0) as acquired:
        assert acquired
        require_sdd_repository_health(plans)
        assert commit_sdd_store_files(store, "Commit plan", paths=[plan])

    assert subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=plans,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines() == ["202607/plan.md"]


def test_split_beads_auto_commit_marker_uses_beads_repo_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.sdd.store import write_sdd_store_record

    workspace = tmp_path / "workspace"
    plans = workspace / "sase" / "repos" / "plans"
    research = workspace / "sase" / "repos" / "research"
    beads = workspace / "sase" / "repos" / "beads"
    artifacts = tmp_path / "artifacts"
    workspace.mkdir()
    plans.mkdir(parents=True)
    research.mkdir()
    artifacts.mkdir()
    init_test_git_repo(beads)
    issue = beads / "issues.jsonl"
    issue.write_text('{"id":"project-1"}\n', encoding="utf-8")
    write_sdd_store_record(
        workspace,
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
        research_dir=research,
        research_remote_url="git@example.com:acme/project--research.git",
        beads_dir=beads,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )

    assert commit_sdd_store_files(
        store,
        "Commit bead state",
        paths=[issue],
        artifacts_dir=artifacts,
    )

    markers = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    assert markers[0]["repo_name"] == "acme/project--beads"
