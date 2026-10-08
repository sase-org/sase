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
    base_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-b", "other"], cwd=repo, check=True)
    shared.write_text("other\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-am", "other"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", base_branch], cwd=repo, check=True)
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
    monkeypatch.setattr(
        "sase.sdd._commit_store._staged_sdd_files",
        lambda _sdd_dir, _pathspecs: [],
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
        time.sleep(0.05)  # sase-test-wait: verifies git lock contention
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


def _porcelain(repo: Path) -> str:
    return subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _commit_paths(repo: Path) -> list[str]:
    out = subprocess.run(
        ["git", "show", "--name-status", "--format=", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return sorted(line.split("\t", 1)[1] for line in out.splitlines() if line.strip())


def test_commit_sdd_files_commits_staged_only_changes(tmp_path: Path) -> None:
    """Staged-only modification + staged deletion land in one commit."""
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    (repo / "a.md").write_text("v1\n", encoding="utf-8")
    (repo / "b.md").write_text("v1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    (repo / "a.md").write_text("v2\n", encoding="utf-8")
    (repo / "b.md").unlink()
    subprocess.run(["git", "add", "a.md", "b.md"], cwd=repo, check=True)
    # Nothing left unstaged: worktree-only enumeration sees nothing.
    assert _porcelain(repo).splitlines() == ["M  a.md", "D  b.md"]

    assert commit_sdd_files(repo, "staged only") is True

    assert _commit_paths(repo) == ["a.md", "b.md"]
    assert _porcelain(repo) == ""


def test_commit_sdd_files_mixed_untracked_and_staged_deletion(
    tmp_path: Path,
) -> None:
    """An untracked file plus a staged deletion commit together."""
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    (repo / "victim.md").write_text("gone\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    subprocess.run(["git", "rm", "-q", "victim.md"], cwd=repo, check=True)
    (repo / "new.md").write_text("new\n", encoding="utf-8")

    assert commit_sdd_files(repo, "mixed") is True

    assert _commit_paths(repo) == ["new.md", "victim.md"]
    assert _porcelain(repo) == ""


def test_commit_sdd_files_targeted_scope_preserves_outside_staged(
    tmp_path: Path,
) -> None:
    """A directory-scoped commit leaves outside staged changes alone."""
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    keep = repo / "keep" / "k.md"
    other = repo / "other" / "o.md"
    keep.parent.mkdir(parents=True)
    other.parent.mkdir(parents=True)
    keep.write_text("k1\n", encoding="utf-8")
    other.write_text("o1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    keep.write_text("k2\n", encoding="utf-8")
    other.write_text("o2\n", encoding="utf-8")
    subprocess.run(["git", "add", "keep/k.md", "other/o.md"], cwd=repo, check=True)

    assert commit_sdd_files(repo, "scoped", paths=["keep"]) is True

    assert _commit_paths(repo) == ["keep/k.md"]
    assert _porcelain(repo).splitlines() == ["M  other/o.md"]


def test_commit_sdd_files_excludes_staged_goals(tmp_path: Path) -> None:
    """Root bead commits never sweep staged goal-ledger changes."""
    repo = tmp_path / "repo"
    init_test_git_repo(repo)
    (repo / "goals").mkdir()
    (repo / "plans").mkdir()
    (repo / "goals" / "g.md").write_text("g1\n", encoding="utf-8")
    (repo / "plans" / "p.md").write_text("p1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True)
    (repo / "goals" / "g.md").write_text("g2\n", encoding="utf-8")
    (repo / "plans" / "p.md").write_text("p2\n", encoding="utf-8")
    subprocess.run(["git", "add", "goals/g.md", "plans/p.md"], cwd=repo, check=True)

    assert commit_sdd_files(repo, "beads") is True

    assert _commit_paths(repo) == ["plans/p.md"]
    assert _porcelain(repo).splitlines() == ["M  goals/g.md"]
