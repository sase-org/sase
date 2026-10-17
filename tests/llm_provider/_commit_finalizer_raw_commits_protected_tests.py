"""Absorption guards for protected paths and interleaved history."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from sase.finalizers.commit_types import BuiltinCommitFinalizerError
from sase.finalizers.commit_validation import raise_if_unpublished_local_commits
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_raw_commits import (
    absorb_raw_local_commits,
    unrecorded_local_commits,
)
from sase.llm_provider.types import InvokeResult

from ._commit_finalizer_raw_commits_helpers import (
    baseline_record,
    commit_file,
    init_repo,
    record_host_stitch,
    repo_head,
    repo_state,
    run_git,
    write_baseline,
)


@pytest.mark.parametrize("protected_kind", ["tracked", "untracked"])
def test_absorb_skips_raw_commit_of_baseline_dirty_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected_kind: str,
) -> None:
    """Committing baseline dirt clean does not remove its protection boundary."""

    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "linked")
    protected_path = "base.txt" if protected_kind == "tracked" else "loose.txt"
    if protected_kind == "tracked":
        (repo / protected_path).write_text("baseline edit\n", encoding="utf-8")
    else:
        (repo / protected_path).write_text("baseline untracked\n", encoding="utf-8")
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
                fingerprints=dict(finalizer_git.dirty_path_fingerprints(str(repo))),
            ),
        ],
    )
    sha = commit_file(
        repo, "own.txt", "own work\n", "raw commit includes baseline dirt"
    )
    tip_state = repo_state(repo)
    assert tip_state[2] == ""

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert repo_state(repo) == tip_state

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        raise_if_unpublished_local_commits(
            artifacts_dir,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )
    assert sha in exc_info.value.result.diagnostics[0].message


def test_absorb_rejects_protected_path_restored_to_baseline_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-commit history catches a protected path hidden by a net revert."""

    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "linked")
    protected = repo / "base.txt"
    protected.write_text("dirty at baseline\n", encoding="utf-8")
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
                fingerprints=dict(finalizer_git.dirty_path_fingerprints(str(repo))),
            ),
        ],
    )
    first = commit_file(repo, "base.txt", "first raw version\n", "raw protected edit")
    restore = commit_file(repo, "base.txt", "base\n", "restore baseline HEAD content")
    tip_state = repo_state(repo)
    assert run_git(repo, "diff", "HEAD~2", "HEAD", "--", "base.txt") == ""

    assert [
        commit.sha for commit in unrecorded_local_commits(artifacts_dir)[0].commits
    ] == [first, restore]
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert repo_state(repo) == tip_state


@pytest.mark.parametrize("protected_side", ["source", "destination"])
def test_absorb_rejects_rename_of_a_protected_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected_side: str,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = init_repo(tmp_path / "linked")
    target = repo / "target.txt"
    target.write_text("original target\n", encoding="utf-8")
    run_git(repo, "add", "-A")
    run_git(repo, "commit", "-q", "-m", "add target")
    protected = repo / ("base.txt" if protected_side == "source" else "target.txt")
    protected.write_text("dirty at baseline\n", encoding="utf-8")
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
                fingerprints=dict(finalizer_git.dirty_path_fingerprints(str(repo))),
            ),
        ],
    )
    run_git(repo, "mv", "-f", "base.txt", "target.txt")
    run_git(repo, "commit", "-q", "-m", "rename protected path")
    tip_state = repo_state(repo)

    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert repo_state(repo) == tip_state


@pytest.mark.parametrize(
    "interleaving", ["foreign_after", "host_after", "foreign_between"]
)
def test_absorb_rejects_filtered_commit_inside_raw_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interleaving: str,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    repo = init_repo(tmp_path / "linked")
    baseline = repo_head(repo)
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
                head=baseline,
            ),
        ],
    )
    raw_shas = [commit_file(repo, "raw-one.txt", "one\n", "first raw commit")]
    if interleaving == "foreign_between":
        interleaved_sha = commit_file(
            repo,
            "foreign.txt",
            "foreign\n",
            "concurrent work\n\nSASE_AGENT=other-agent",
        )
        raw_shas.append(commit_file(repo, "raw-two.txt", "two\n", "second raw commit"))
        expected_history = [raw_shas[0], interleaved_sha, raw_shas[1]]
    else:
        interleaved_sha = commit_file(
            repo,
            "interleaved.txt",
            "interleaved\n",
            (
                "concurrent work\n\nSASE_AGENT=other-agent"
                if interleaving == "foreign_after"
                else "host stitch work"
            ),
        )
        if interleaving == "host_after":
            record_host_stitch(artifacts_dir, repo, interleaved_sha, pushed=False)
        expected_history = [raw_shas[0], interleaved_sha]
    tip_state = repo_state(repo)

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == raw_shas
    assert run_git(repo, "rev-list", "--reverse", f"{baseline}..HEAD").splitlines() == (
        expected_history
    )
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert repo_state(repo) == tip_state

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        raise_if_unpublished_local_commits(
            artifacts_dir,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )
    diagnostic = exc_info.value.result.diagnostics[0]
    assert diagnostic.code == "unpublished_local_commits"
    assert all(sha in diagnostic.message for sha in raw_shas)


def test_absorb_rejects_exempted_tool_commit_inside_raw_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    repo = init_repo(tmp_path / "linked")
    baseline = repo_head(repo)
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
                head=baseline,
            ),
        ],
    )
    first = commit_file(repo, "raw-one.txt", "one\n", "first raw commit")
    commit_file(
        repo,
        "memory.txt",
        "memory\n",
        "chore: initialize sase memory\n\nSASE_TYPE=memory",
    )
    second = commit_file(repo, "raw-two.txt", "two\n", "second raw commit")
    tip_state = repo_state(repo)

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == [first, second]
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert repo_state(repo) == tip_state


@pytest.mark.parametrize("preceding", ["foreign", "host", "remote"])
def test_absorb_preserves_commit_before_complete_raw_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preceding: str,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    repo = init_repo(tmp_path / "linked")
    baseline = repo_head(repo)
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
                head=baseline,
            ),
        ],
    )
    if preceding == "remote":
        remote = tmp_path / "remote.git"
        subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
        run_git(repo, "remote", "add", "origin", str(remote))
        run_git(repo, "push", "-q", "-u", "origin", "HEAD")
        prior = commit_file(
            repo, "prior.txt", "remote work\n", "remote-reachable prior"
        )
        run_git(repo, "push", "-q", "origin", "HEAD")
    elif preceding == "foreign":
        prior = commit_file(
            repo,
            "prior.txt",
            "foreign work\n",
            "prior concurrent work\n\nSASE_AGENT=other-agent",
        )
    else:
        prior = commit_file(repo, "prior.txt", "host work\n", "prior host stitch")
        record_host_stitch(artifacts_dir, repo, prior, pushed=False)
    raw_sha = commit_file(repo, "own.txt", "own work\n", "raw suffix")
    tip = repo_head(repo)

    absorbed = absorb_raw_local_commits(str(tmp_path), artifacts_dir)

    assert len(absorbed) == 1
    assert absorbed[0].reset_target == prior
    assert absorbed[0].recovery_ref == "refs/sase/recovery/raw-commits/run-1"
    assert run_git(repo, "rev-parse", absorbed[0].recovery_ref) == tip
    assert repo_head(repo) == prior
    assert run_git(repo, "diff", "--cached", "--name-only").splitlines() == ["own.txt"]
    assert raw_sha in [commit.sha for commit in absorbed[0].commits]
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
