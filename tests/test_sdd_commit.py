"""Tests for committing SDD files."""

import json
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import pytest

from sase.git_lock_retry import run_with_git_lock_retry
from sase.sdd._git_contention import (
    ENV_GIT_LOCK_RETRY_DELAYS,
    ENV_STORE_WRITE_LOCK_TIMEOUT,
    SddGitCommandError,
    store_git_write_lock,
)
from sase.sdd.files import commit_sdd_files
from sase.sdd._repository_transaction import SddRepositoryHealthError
from tests._sdd_commit_helpers import init_test_git_repo


def test_commit_sdd_files() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )

        (sdd_dir / "test.md").write_text("hello", encoding="utf-8")
        commit_sdd_files(sdd_dir, "Test commit")

        log = subprocess.run(
            ["git", "log", "-1", "--format=%B"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Test commit" in log.stdout
        assert "SASE_TYPE=sdd" in log.stdout


def test_commit_sdd_files_stages_only_targeted_paths() -> None:
    """Targeted local SDD commits must not sweep unrelated dirty files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )

        prompt = sdd_dir / "prompts" / "202605" / "targeted.md"
        plan = sdd_dir / "plans" / "202605" / "targeted.md"
        prompt.parent.mkdir(parents=True)
        plan.parent.mkdir(parents=True)
        prompt.write_text("prompt", encoding="utf-8")
        plan.write_text("plan", encoding="utf-8")
        unrelated = sdd_dir / "research" / "202605" / "notes.md"
        unrelated.parent.mkdir(parents=True)
        unrelated.write_text("do not commit", encoding="utf-8")

        commit_sdd_files(sdd_dir, "Targeted commit", paths=[prompt, plan])

        committed = subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        status = subprocess.run(
            [
                "git",
                "-c",
                "color.status=false",
                "status",
                "--short",
                "--",
                "research/202605/notes.md",
            ],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

        assert committed == [
            "plans/202605/targeted.md",
            "prompts/202605/targeted.md",
        ]
        assert status == "?? research/202605/notes.md\n"


def test_commit_sdd_files_records_agent_marker_when_artifacts_dir_is_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdd_dir = tmp_path / "sdd"
    artifacts_dir = tmp_path / "artifacts"
    sdd_dir.mkdir()
    artifacts_dir.mkdir()
    subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260708120000")
    monkeypatch.setattr(
        "sase.workflows.commit.commit_tracking."
        "update_agent_artifact_index_for_marker_mutation",
        lambda *_args, **_kwargs: None,
    )

    (sdd_dir / "test.md").write_text("hello", encoding="utf-8")

    assert (
        commit_sdd_files(
            sdd_dir,
            "Record SDD commit",
            repo_name="sase-org/sase--sdd",
        )
        is True
    )

    results = json.loads((artifacts_dir / "commit_results.json").read_text())
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=sdd_dir,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert not (artifacts_dir / "commit_result.json").exists()
    assert results[0]["run_id"] == "20260708120000"
    assert results[0]["cwd"] == str(sdd_dir)
    assert results[0]["result"] == head
    assert results[0]["message"].startswith("Record SDD commit")
    assert results[0]["repo_name"] == "sase-org/sase--sdd"
    diff_path = Path(results[0]["diff_path"])
    assert diff_path == artifacts_dir / "commit_diffs" / "001.diff"
    assert "+hello\n" in diff_path.read_text(encoding="utf-8")


def test_commit_sdd_files_diff_is_scoped_to_committed_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdd_dir = tmp_path / "sdd"
    artifacts_dir = tmp_path / "artifacts"
    init_test_git_repo(sdd_dir)
    artifacts_dir.mkdir()
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.setattr(
        "sase.workflows.commit.commit_tracking."
        "update_agent_artifact_index_for_marker_mutation",
        lambda *_args, **_kwargs: None,
    )
    committed = sdd_dir / "plans" / "plan.md"
    uncommitted = sdd_dir / "research" / "report.md"
    committed.parent.mkdir()
    uncommitted.parent.mkdir()
    committed.write_text("plan\n", encoding="utf-8")
    uncommitted.write_text("report\n", encoding="utf-8")

    assert commit_sdd_files(
        sdd_dir,
        "Add plan",
        paths=[committed],
        artifacts_dir=artifacts_dir,
        repo_name="plans",
    )

    results = json.loads((artifacts_dir / "commit_results.json").read_text())
    diff_text = Path(results[0]["diff_path"]).read_text(encoding="utf-8")
    assert "plans/plan.md" in diff_text
    assert "research/report.md" not in diff_text
    assert (
        subprocess.run(
            ["git", "status", "--short"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        == "?? research/\n"
    )


def test_commit_sdd_files_skips_agent_marker_when_artifacts_dir_is_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sdd_dir = tmp_path / "sdd"
    artifacts_dir = tmp_path / "artifacts"
    sdd_dir.mkdir()
    artifacts_dir.mkdir()
    subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )
    monkeypatch.delenv("SASE_ARTIFACTS_DIR", raising=False)
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)

    (sdd_dir / "test.md").write_text("hello", encoding="utf-8")

    assert commit_sdd_files(sdd_dir, "Record SDD commit") is True

    assert not (artifacts_dir / "commit_results.json").exists()


def test_commit_sdd_files_no_changes() -> None:
    """No-op when there are no changes to commit."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        subprocess.run(["git", "init"], cwd=sdd_dir, check=True, capture_output=True)

        commit_sdd_files(sdd_dir, "Empty commit")

        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
        )
        assert log.stdout.strip() == ""


def test_commit_sdd_files_not_git_repo() -> None:
    """No-op if sdd_dir is not a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        sdd_dir = Path(tmpdir)
        commit_sdd_files(sdd_dir, "Should not error")


@pytest.mark.parametrize(
    ("marker", "label"),
    [
        ("rebase-merge", "rebase"),
        ("MERGE_HEAD", "merge"),
        ("CHERRY_PICK_HEAD", "cherry-pick"),
    ],
)
def test_commit_sdd_files_refuses_in_progress_git_operation_before_staging(
    tmp_path: Path,
    marker: str,
    label: str,
) -> None:
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    plan = repo / "plan.md"
    plan.write_text("plan\n", encoding="utf-8")
    marker_path = repo / ".git" / marker
    if "." in marker:
        marker_path.write_text("blocked\n", encoding="utf-8")
    else:
        marker_path.mkdir()
    starting_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    with pytest.raises(SddRepositoryHealthError, match=label):
        commit_sdd_files(repo, "Must not commit")

    assert plan.read_text(encoding="utf-8") == "plan\n"
    assert (
        subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == ""
    )
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == starting_head
    )


def test_commit_sdd_files_refuses_unmerged_index_without_mutation(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    shared = repo / "shared.md"
    shared.write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "shared.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True
    )
    subprocess.run(["git", "checkout", "-b", "other"], cwd=repo, check=True)
    shared.write_text("other\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "other"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "master"], cwd=repo, check=True)
    shared.write_text("master\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "master"], cwd=repo, check=True)
    merged = subprocess.run(
        ["git", "merge", "other"], cwd=repo, check=False, capture_output=True
    )
    assert merged.returncode != 0
    plan = repo / "plan.md"
    plan.write_text("keep\n", encoding="utf-8")
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    with pytest.raises(SddRepositoryHealthError, match="unmerged index"):
        commit_sdd_files(repo, "Must not commit")

    assert plan.read_text(encoding="utf-8") == "keep\n"
    assert (
        subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        == before
    )


def test_commit_sdd_files_retries_transient_index_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    (repo / "plan.md").write_text("plan\n", encoding="utf-8")
    lock_path = repo / ".git/index.lock"
    lock_path.touch()
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.01,0.02,0.04,0.08")
    release = threading.Timer(0.03, lambda: lock_path.unlink(missing_ok=True))
    release.start()

    try:
        assert commit_sdd_files(repo, "Commit after contention") is True
    finally:
        release.cancel()
        lock_path.unlink(missing_ok=True)


def test_commit_sdd_files_removes_persistent_index_lock_after_retry_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    (repo / "plan.md").write_text("plan\n", encoding="utf-8")
    lock_path = repo / ".git/index.lock"
    lock_path.touch()
    monkeypatch.setenv(ENV_GIT_LOCK_RETRY_DELAYS, "0.001,0.001")

    assert commit_sdd_files(repo, "Recover after contention") is True
    assert not lock_path.exists()


def test_commit_sdd_files_does_not_retry_non_lock_128(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    retry_attempt_counts: list[int] = []

    def observe_retry(
        attempt: Callable[[], subprocess.CompletedProcess[Any]],
        *,
        cwd: str | Path,
        delays: Iterable[float],
    ) -> tuple[subprocess.CompletedProcess[Any], object]:
        result, outcome = run_with_git_lock_retry(
            attempt,
            cwd=cwd,
            delays=delays,
        )
        retry_attempt_counts.append(outcome.attempts_made)
        return result, outcome

    monkeypatch.setattr(
        "sase.sdd._git_contention.run_with_git_lock_retry",
        observe_retry,
    )

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        commit_sdd_files(repo, "Invalid pathspec", paths=[":(invalid)"])

    assert "pathspec" in str(exc_info.value).lower()
    assert retry_attempt_counts
    assert set(retry_attempt_counts) == {1}


def test_commit_sdd_files_errors_on_unexpected_cached_diff_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    (repo / "plan.md").write_text("plan\n", encoding="utf-8")
    monkeypatch.setattr(
        "sase.sdd._commit_store.changed_sdd_files",
        lambda _sdd_dir, _pathspecs: ["plan.md"],
    )

    def fail_cached_diff(
        args: list[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        assert args[:3] == ["diff", "--cached", "--quiet"]
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=128,
            stdout="",
            stderr="fatal: could not inspect the index",
        )

    monkeypatch.setattr("sase.sdd._commit_store.run_sdd_git", fail_cached_diff)

    with pytest.raises(SddGitCommandError, match="could not inspect the index"):
        commit_sdd_files(repo, "Commit with failed staged-diff probe")


def test_commit_sdd_files_waits_for_store_write_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    plan = repo / "plan.md"
    plan.write_text("first\n", encoding="utf-8")
    subprocess.run(["git", "add", "plan.md"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    original_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    plan.write_text("second\n", encoding="utf-8")
    monkeypatch.setenv(ENV_STORE_WRITE_LOCK_TIMEOUT, "1")
    started = threading.Event()
    finished = threading.Event()
    results: list[bool] = []

    def commit_in_thread() -> None:
        started.set()
        results.append(commit_sdd_files(repo, "Commit after store lock"))
        finished.set()

    with store_git_write_lock(repo) as acquired:
        assert acquired is True
        writer = threading.Thread(target=commit_in_thread)
        writer.start()
        assert started.wait(timeout=1)
        time.sleep(0.05)
        assert finished.is_set() is False
        current_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert current_head == original_head

    writer.join(timeout=1)
    assert writer.is_alive() is False
    assert results == [True]
