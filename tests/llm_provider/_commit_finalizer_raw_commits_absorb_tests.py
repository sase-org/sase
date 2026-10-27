"""Absorption eligibility, skip cases, and reset races."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.finalizers.commit_types import BuiltinCommitFinalizerError
from sase.finalizers.commit_validation import raise_if_unpublished_local_commits
from sase.llm_provider import commit_finalizer_raw_commits as raw_commits
from sase.llm_provider.commit_finalizer_baseline import (
    capture_opened_repo_dirty_baseline,
)
from sase.llm_provider.commit_finalizer_raw_commits import (
    absorb_raw_local_commits,
    unrecorded_local_commits,
)
from sase.llm_provider.types import InvokeResult

from ._commit_finalizer_raw_commits_helpers import (
    baseline_record,
    commit_file,
    init_repo,
    repo_head,
    repo_state,
    run_git,
    write_baseline,
)


def test_absorb_soft_resets_eligible_chain_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "linked")
    base = repo_head(repo)
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=base,
            ),
        ],
    )
    first = commit_file(repo, "one.txt", "one\n", "agent raw one")
    tip = commit_file(repo, "two.txt", "two\n", "agent raw two")

    absorbed = absorb_raw_local_commits(str(tmp_path), artifacts_dir)

    assert len(absorbed) == 1
    entry = absorbed[0]
    assert entry.kind == "sibling"
    assert entry.name == "core"
    assert [commit.sha for commit in entry.commits] == [first, tip]
    assert [commit.subject for commit in entry.commits] == [
        "agent raw one",
        "agent raw two",
    ]
    assert entry.reset_target == base
    assert entry.recovery_ref == "refs/sase/recovery/raw-commits/run-1"
    # The recovery ref pins the pre-reset HEAD, and the changes are staged.
    assert run_git(repo, "rev-parse", "--verify", entry.recovery_ref) == tip
    assert repo_head(repo) == base
    status = run_git(repo, "status", "--porcelain=v1")
    assert "A  one.txt" in status.splitlines()
    assert "A  two.txt" in status.splitlines()
    # A second call finds nothing: HEAD already equals the reset target.
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()


def test_absorb_skips_merge_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )
    run_git(repo, "checkout", "-q", "-b", "feature")
    commit_file(repo, "feature.txt", "feature\n", "feature work")
    run_git(repo, "checkout", "-q", "main")
    commit_file(repo, "main.txt", "main\n", "main work")
    run_git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")
    tip = repo_head(repo)

    assert len(unrecorded_local_commits(artifacts_dir)[0].commits) == 3
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert repo_head(repo) == tip


def test_absorb_soft_resets_opened_linked_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "bob-mac-capture")
    artifacts_dir = tmp_path / "artifacts"
    assert (
        capture_opened_repo_dirty_baseline(
            "linked:bob-mac-capture",
            str(repo),
            kind="linked",
            name="bob-mac-capture",
            artifacts_dir=str(artifacts_dir),
        )
        is None
    )
    base = repo_head(repo)
    tip = commit_file(repo, "work.txt", "work\n", "agent raw linked commit")

    absorbed = absorb_raw_local_commits(str(tmp_path), artifacts_dir)

    assert len(absorbed) == 1
    entry = absorbed[0]
    assert entry.kind == "linked"
    assert entry.name == "bob-mac-capture"
    assert [commit.sha for commit in entry.commits] == [tip]
    assert entry.reset_target == base
    assert entry.recovery_ref == "refs/sase/recovery/raw-commits/run-1"
    assert run_git(repo, "rev-parse", "--verify", entry.recovery_ref) == tip
    assert repo_head(repo) == base
    status = run_git(repo, "status", "--porcelain=v1")
    assert "A  work.txt" in status.splitlines()


def test_absorb_skips_detached_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )
    run_git(repo, "checkout", "-q", "--detach", "HEAD")
    tip = commit_file(repo, "work.txt", "work\n", "detached raw commit")

    assert len(unrecorded_local_commits(artifacts_dir)[0].commits) == 1
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert repo_head(repo) == tip


def test_backstop_raises_for_ineligible_opened_linked_repo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "bob-mac-capture")
    artifacts_dir = tmp_path / "artifacts"
    assert (
        capture_opened_repo_dirty_baseline(
            "linked:bob-mac-capture",
            str(repo),
            kind="linked",
            name="bob-mac-capture",
            artifacts_dir=str(artifacts_dir),
        )
        is None
    )
    run_git(repo, "checkout", "-q", "--detach", "HEAD")
    sha = commit_file(repo, "work.txt", "work\n", "detached linked raw commit")

    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        raise_if_unpublished_local_commits(
            artifacts_dir,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )
    assert sha in exc_info.value.result.diagnostics[0].message


def test_absorb_skips_operation_in_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )
    run_git(repo, "checkout", "-q", "-b", "other")
    commit_file(repo, "other.txt", "other\n", "other work")
    run_git(repo, "checkout", "-q", "main")
    tip = commit_file(repo, "work.txt", "work\n", "linear raw commit")
    run_git(repo, "merge", "--no-commit", "other")

    try:
        assert (repo / ".git" / "MERGE_HEAD").exists()
        assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
        assert repo_head(repo) == tip
    finally:
        run_git(repo, "merge", "--abort")


def test_absorb_revalidates_head_before_pinning_and_resetting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )
    raw_sha = commit_file(repo, "raw.txt", "raw\n", "raw commit")
    original_proof = raw_commits._prove_owned_suffix
    raced_head: list[str] = []
    raced_state: list[tuple[str, str, str, str, str]] = []

    def prove_then_advance(finding: object) -> object:
        proof = original_proof(finding)  # type: ignore[arg-type]
        raced_head.append(
            commit_file(repo, "racer.txt", "racer\n", "concurrent commit")
        )
        raced_state.append(repo_state(repo))
        return proof

    monkeypatch.setattr(raw_commits, "_prove_owned_suffix", prove_then_advance)

    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()

    assert len(raced_head) == 1
    assert repo_state(repo) == raced_state[0]
    assert repo_head(repo) == raced_head[0]
    assert not run_git(
        repo, "for-each-ref", "--format=%(refname)", "refs/sase/recovery/raw-commits"
    )
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        raise_if_unpublished_local_commits(
            artifacts_dir,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )
    assert raw_sha in exc_info.value.result.diagnostics[0].message


def test_absorb_without_run_id_leaves_repos_untouched(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    repo = init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )
    tip = commit_file(repo, "work.txt", "work\n", "raw commit")

    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert repo_head(repo) == tip
