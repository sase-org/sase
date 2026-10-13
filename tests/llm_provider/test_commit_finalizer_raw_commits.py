"""Coverage for raw local-commit detection and absorption.

An agent's raw ``git commit`` outside the host stitch path leaves a clean
tree, so dirty-state discovery never sees it. The detector
(:func:`unrecorded_local_commits`) finds those commits from the run-start
baseline ``head``; :func:`absorb_raw_local_commits` soft-resets eligible
chains back to staged dirt; the execution-time backstop fails anything left
over with ``unpublished_local_commits`` (bead sase-1kh.2).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sase.finalizers.commit_types import BuiltinCommitFinalizerError
from sase.finalizers.commit_validation import raise_if_unpublished_local_commits
from sase.finalizers.ledger import RETRYABLE_DIAGNOSTIC_CODES
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider import commit_finalizer_raw_commits as raw_commits
from sase.llm_provider.commit_finalizer_baseline import (
    FINALIZER_BASELINE_FILENAME,
    capture_opened_repo_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider.commit_finalizer_raw_commits import (
    absorb_raw_local_commits,
    unrecorded_local_commits,
)
from sase.llm_provider.types import InvokeResult

#: Sentinel for writing a legacy baseline record with no ``head`` key at all.
_NO_HEAD = object()


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _run_git(path, "init", "-q", "-b", "main")
    _run_git(path, "config", "user.name", "SASE Test")
    _run_git(path, "config", "user.email", "sase-test@example.invalid")
    (path / "base.txt").write_text("base\n", encoding="utf-8")
    _run_git(path, "add", "-A")
    _run_git(path, "commit", "-q", "-m", "initial")
    return path


def _commit(repo: Path, filename: str, content: str, message: str) -> str:
    (repo / filename).write_text(content, encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", message)
    return _run_git(repo, "rev-parse", "HEAD")


def _head(repo: Path) -> str:
    return _run_git(repo, "rev-parse", "HEAD")


def _repo_state(repo: Path) -> tuple[str, str, str, str, str]:
    """Capture HEAD, index, status, and both worktree/index diffs."""

    return (
        _head(repo),
        _run_git(repo, "write-tree"),
        _run_git(repo, "status", "--porcelain=v1", "--untracked-files=all"),
        _run_git(repo, "diff", "--binary", "HEAD"),
        _run_git(repo, "diff", "--cached", "--binary"),
    )


def _write_baseline(
    artifacts_dir: Path,
    records: list[dict[str, object]],
) -> None:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / FINALIZER_BASELINE_FILENAME).write_text(
        json.dumps({"schema_version": 1, "repositories": records}),
        encoding="utf-8",
    )


def _baseline_record(
    *,
    repo_id: str,
    repo: Path,
    kind: str,
    name: str,
    scope: str,
    head: object,
    fingerprints: dict[str, tuple[str, str | None]] | None = None,
) -> dict[str, object]:
    record: dict[str, object] = {
        "repo_id": repo_id,
        "path": finalizer_git.normalize_path(str(repo)),
        "kind": kind,
        "name": name,
        "scope": scope,
        "captured_at": "2026-10-13T12:00:00+00:00",
        "fingerprints": {
            path: list(fingerprint)
            for path, fingerprint in (fingerprints or {}).items()
        },
    }
    if head is not _NO_HEAD:
        record["head"] = head
    return record


def _record_host_stitch(
    artifacts_dir: Path, repo: Path, sha: str, *, pushed: bool = False
) -> None:
    tree = _run_git(repo, "rev-parse", f"{sha}^{{tree}}")
    (artifacts_dir / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "cwd": str(repo),
                    "result": sha,
                    "commit_sha": sha,
                    "commit_tree": tree,
                    "pushed": pushed,
                }
            ]
        ),
        encoding="utf-8",
    )


def test_detects_raw_commits_in_main_and_sibling_oldest_first(
    tmp_path: Path,
) -> None:
    main = _init_repo(tmp_path / "main")
    sibling = _init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="main",
                repo=main,
                kind="main",
                name="main",
                scope="run_start",
                head=_head(main),
            ),
            _baseline_record(
                repo_id="sibling:core",
                repo=sibling,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(sibling),
            ),
        ],
    )

    sibling_base = _head(sibling)
    _commit(sibling, "one.txt", "one\n", "agent raw one")
    second = _commit(sibling, "two.txt", "two\n", "agent raw two")
    main_sha = _commit(main, "m.txt", "m\n", "main raw")

    findings = unrecorded_local_commits(artifacts_dir)
    assert [finding.name for finding in findings] == ["core", "main"]
    by_name = {finding.name: finding for finding in findings}
    assert [commit.sha for commit in by_name["main"].commits] == [main_sha]
    assert by_name["main"].commits[0].subject == "main raw"
    assert [commit.sha for commit in by_name["core"].commits][1] == second
    assert [commit.subject for commit in by_name["core"].commits] == [
        "agent raw one",
        "agent raw two",
    ]
    assert by_name["core"].baseline_head == sibling_base


def test_host_stitch_commit_waiting_on_resume_is_not_raw(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )

    sha = _commit(repo, "work.txt", "work\n", "host stitch commit")
    _record_host_stitch(artifacts_dir, repo, sha, pushed=False)

    assert unrecorded_local_commits(artifacts_dir) == ()


def test_remote_reachable_fast_forwards_since_baseline_are_ignored(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    _run_git(repo, "remote", "add", "origin", str(remote))
    _run_git(repo, "push", "-q", "-u", "origin", "HEAD")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )

    _commit(repo, "pushed.txt", "pushed\n", "pushed after baseline")
    _run_git(repo, "push", "-q", "origin", "HEAD")
    local_sha = _commit(repo, "local.txt", "local\n", "local only")

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == [local_sha]


def test_foreign_agent_commit_is_not_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A concurrent agent's local-only commit is not this turn's raw commit.

    The discarded-work guard already exempts foreign-agent races in shared
    clones; the raw-commit detector must agree, or the backstop would fail
    turns for work another agent committed (``sase-1kh.2`` follow-up from
    ``test_already_clean_foreign_race_on_external_is_exempt``).
    """

    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent-meta"))
    repo = _init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )

    _commit(
        repo,
        "work.txt",
        "work\n",
        "commit dirty payload\n\nSASE_AGENT=other-agent",
    )

    assert unrecorded_local_commits(artifacts_dir) == ()


def test_own_and_unattributed_commits_are_still_raw_alongside_foreign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Foreign exemption keeps only this agent's unattributed or own commits."""

    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent-meta"))
    repo = _init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )

    _commit(
        repo,
        "foreign.txt",
        "foreign\n",
        "foreign payload\n\nSASE_AGENT=other-agent",
    )
    own_sha = _commit(
        repo,
        "own.txt",
        "own\n",
        "own payload\n\nSASE_AGENT=current-agent",
    )
    plain_sha = _commit(repo, "plain.txt", "plain\n", "plain raw work")

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == [own_sha, plain_sha]


def test_sdd_and_headless_baseline_records_are_skipped(
    tmp_path: Path,
) -> None:
    sdd = _init_repo(tmp_path / "sdd")
    legacy = _init_repo(tmp_path / "legacy")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sdd:research",
                repo=sdd,
                kind="sdd",
                name="research",
                scope="run_start",
                head=_head(sdd),
            ),
            _baseline_record(
                repo_id="main",
                repo=legacy,
                kind="main",
                name="main",
                scope="run_start",
                head=_NO_HEAD,
            ),
        ],
    )

    _commit(sdd, "note.md", "note\n", "sdd sidecar commit")
    _commit(legacy, "work.txt", "work\n", "legacy raw commit")

    assert unrecorded_local_commits(artifacts_dir) == ()


def test_opened_repo_baseline_capture_records_head(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"

    assert (
        capture_opened_repo_dirty_baseline(
            "linked:core",
            str(repo),
            kind="linked",
            name="core",
            artifacts_dir=str(artifacts_dir),
        )
        is None
    )

    records = load_finalizer_baseline_records(artifacts_dir)
    assert records is not None
    assert len(records) == 1
    assert records[0].head == _head(repo)


def test_absorb_soft_resets_eligible_chain_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = _init_repo(tmp_path / "linked")
    base = _head(repo)
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=base,
            ),
        ],
    )
    first = _commit(repo, "one.txt", "one\n", "agent raw one")
    tip = _commit(repo, "two.txt", "two\n", "agent raw two")

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
    assert _run_git(repo, "rev-parse", "--verify", entry.recovery_ref) == tip
    assert _head(repo) == base
    status = _run_git(repo, "status", "--porcelain=v1")
    assert "A  one.txt" in status.splitlines()
    assert "A  two.txt" in status.splitlines()
    # A second call finds nothing: HEAD already equals the reset target.
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()


def test_absorb_skips_merge_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = _init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )
    _run_git(repo, "checkout", "-q", "-b", "feature")
    _commit(repo, "feature.txt", "feature\n", "feature work")
    _run_git(repo, "checkout", "-q", "main")
    _commit(repo, "main.txt", "main\n", "main work")
    _run_git(repo, "merge", "-q", "--no-ff", "feature", "-m", "merge feature")
    tip = _head(repo)

    assert len(unrecorded_local_commits(artifacts_dir)[0].commits) == 3
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert _head(repo) == tip


def test_absorb_skips_detached_head(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = _init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )
    _run_git(repo, "checkout", "-q", "--detach", "HEAD")
    tip = _commit(repo, "work.txt", "work\n", "detached raw commit")

    assert len(unrecorded_local_commits(artifacts_dir)[0].commits) == 1
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert _head(repo) == tip


def test_absorb_skips_operation_in_progress(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = _init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )
    _run_git(repo, "checkout", "-q", "-b", "other")
    _commit(repo, "other.txt", "other\n", "other work")
    _run_git(repo, "checkout", "-q", "main")
    tip = _commit(repo, "work.txt", "work\n", "linear raw commit")
    _run_git(repo, "merge", "--no-commit", "other")

    try:
        assert (repo / ".git" / "MERGE_HEAD").exists()
        assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
        assert _head(repo) == tip
    finally:
        _run_git(repo, "merge", "--abort")


@pytest.mark.parametrize("protected_kind", ["tracked", "untracked"])
def test_absorb_skips_raw_commit_of_baseline_dirty_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected_kind: str,
) -> None:
    """Committing baseline dirt clean does not remove its protection boundary."""

    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = _init_repo(tmp_path / "linked")
    protected_path = "base.txt" if protected_kind == "tracked" else "loose.txt"
    if protected_kind == "tracked":
        (repo / protected_path).write_text("baseline edit\n", encoding="utf-8")
    else:
        (repo / protected_path).write_text("baseline untracked\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
                fingerprints=dict(finalizer_git.dirty_path_fingerprints(str(repo))),
            ),
        ],
    )
    sha = _commit(repo, "own.txt", "own work\n", "raw commit includes baseline dirt")
    tip_state = _repo_state(repo)
    assert tip_state[2] == ""

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert _repo_state(repo) == tip_state

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
    repo = _init_repo(tmp_path / "linked")
    protected = repo / "base.txt"
    protected.write_text("dirty at baseline\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
                fingerprints=dict(finalizer_git.dirty_path_fingerprints(str(repo))),
            ),
        ],
    )
    first = _commit(repo, "base.txt", "first raw version\n", "raw protected edit")
    restore = _commit(repo, "base.txt", "base\n", "restore baseline HEAD content")
    tip_state = _repo_state(repo)
    assert _run_git(repo, "diff", "HEAD~2", "HEAD", "--", "base.txt") == ""

    assert [
        commit.sha for commit in unrecorded_local_commits(artifacts_dir)[0].commits
    ] == [first, restore]
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert _repo_state(repo) == tip_state


@pytest.mark.parametrize("protected_side", ["source", "destination"])
def test_absorb_rejects_rename_of_a_protected_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    protected_side: str,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = _init_repo(tmp_path / "linked")
    target = repo / "target.txt"
    target.write_text("original target\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "add target")
    protected = repo / ("base.txt" if protected_side == "source" else "target.txt")
    protected.write_text("dirty at baseline\n", encoding="utf-8")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
                fingerprints=dict(finalizer_git.dirty_path_fingerprints(str(repo))),
            ),
        ],
    )
    _run_git(repo, "mv", "-f", "base.txt", "target.txt")
    _run_git(repo, "commit", "-q", "-m", "rename protected path")
    tip_state = _repo_state(repo)

    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert _repo_state(repo) == tip_state


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
    repo = _init_repo(tmp_path / "linked")
    baseline = _head(repo)
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=baseline,
            ),
        ],
    )
    raw_shas = [_commit(repo, "raw-one.txt", "one\n", "first raw commit")]
    if interleaving == "foreign_between":
        interleaved_sha = _commit(
            repo,
            "foreign.txt",
            "foreign\n",
            "concurrent work\n\nSASE_AGENT=other-agent",
        )
        raw_shas.append(_commit(repo, "raw-two.txt", "two\n", "second raw commit"))
        expected_history = [raw_shas[0], interleaved_sha, raw_shas[1]]
    else:
        interleaved_sha = _commit(
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
            _record_host_stitch(artifacts_dir, repo, interleaved_sha, pushed=False)
        expected_history = [raw_shas[0], interleaved_sha]
    tip_state = _repo_state(repo)

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == raw_shas
    assert _run_git(
        repo, "rev-list", "--reverse", f"{baseline}..HEAD"
    ).splitlines() == (expected_history)
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert _repo_state(repo) == tip_state

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        raise_if_unpublished_local_commits(
            artifacts_dir,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )
    diagnostic = exc_info.value.result.diagnostics[0]
    assert diagnostic.code == "unpublished_local_commits"
    assert all(sha in diagnostic.message for sha in raw_shas)


@pytest.mark.parametrize("preceding", ["foreign", "host", "remote"])
def test_absorb_preserves_commit_before_complete_raw_suffix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preceding: str,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    repo = _init_repo(tmp_path / "linked")
    baseline = _head(repo)
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
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
        _run_git(repo, "remote", "add", "origin", str(remote))
        _run_git(repo, "push", "-q", "-u", "origin", "HEAD")
        prior = _commit(repo, "prior.txt", "remote work\n", "remote-reachable prior")
        _run_git(repo, "push", "-q", "origin", "HEAD")
    elif preceding == "foreign":
        prior = _commit(
            repo,
            "prior.txt",
            "foreign work\n",
            "prior concurrent work\n\nSASE_AGENT=other-agent",
        )
    else:
        prior = _commit(repo, "prior.txt", "host work\n", "prior host stitch")
        _record_host_stitch(artifacts_dir, repo, prior, pushed=False)
    raw_sha = _commit(repo, "own.txt", "own work\n", "raw suffix")
    tip = _head(repo)

    absorbed = absorb_raw_local_commits(str(tmp_path), artifacts_dir)

    assert len(absorbed) == 1
    assert absorbed[0].reset_target == prior
    assert absorbed[0].recovery_ref == "refs/sase/recovery/raw-commits/run-1"
    assert _run_git(repo, "rev-parse", absorbed[0].recovery_ref) == tip
    assert _head(repo) == prior
    assert _run_git(repo, "diff", "--cached", "--name-only").splitlines() == ["own.txt"]
    assert raw_sha in [commit.sha for commit in absorbed[0].commits]
    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()


def test_absorb_revalidates_head_before_pinning_and_resetting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    repo = _init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )
    raw_sha = _commit(repo, "raw.txt", "raw\n", "raw commit")
    original_proof = raw_commits._prove_owned_suffix
    raced_head: list[str] = []
    raced_state: list[tuple[str, str, str, str, str]] = []

    def prove_then_advance(finding: object) -> object:
        proof = original_proof(finding)  # type: ignore[arg-type]
        raced_head.append(_commit(repo, "racer.txt", "racer\n", "concurrent commit"))
        raced_state.append(_repo_state(repo))
        return proof

    monkeypatch.setattr(raw_commits, "_prove_owned_suffix", prove_then_advance)

    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()

    assert len(raced_head) == 1
    assert _repo_state(repo) == raced_state[0]
    assert _head(repo) == raced_head[0]
    assert not _run_git(
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
    repo = _init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )
    tip = _commit(repo, "work.txt", "work\n", "raw commit")

    assert absorb_raw_local_commits(str(tmp_path), artifacts_dir) == ()
    assert _head(repo) == tip


def test_backstop_fails_with_unpublished_local_commits(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    _write_baseline(
        artifacts_dir,
        [
            _baseline_record(
                repo_id="sibling:core",
                repo=repo,
                kind="sibling",
                name="core",
                scope="run_start",
                head=_head(repo),
            ),
        ],
    )
    sha = _commit(repo, "work.txt", "work\n", "stranded agent work")

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        raise_if_unpublished_local_commits(
            artifacts_dir,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )

    result = exc_info.value.result
    assert result.diagnostics[0].code == "unpublished_local_commits"
    assert "unpublished_local_commits" not in RETRYABLE_DIAGNOSTIC_CODES
    assert sha in result.diagnostics[0].message
    assert "stranded agent work" in result.diagnostics[0].message
    assert str(repo) in result.diagnostics[0].message


def test_backstop_passes_when_no_unrecorded_commits(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()

    assert (
        raise_if_unpublished_local_commits(
            artifacts_dir,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )
        is None
    )
    assert (
        raise_if_unpublished_local_commits(
            None,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )
        is None
    )


def test_context_absorbs_eligible_raw_commit_into_obligation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Publishing context stages an eligible raw chain for the host to commit.

    The absorbed sha is reported in the context payload so the agent and the
    run's finalizer evidence both show it, and a second publication absorbs
    nothing more.
    """

    from sase.finalizers.declaration import (
        SASE_FINAL_TURN_NONCE_ENV,
        publish_final_context,
    )
    from sase.finalizers.plan import resolve_and_persist_finalizer_plan
    from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
    from sase.macro.directives import PromptDirectives

    from ._commit_finalizer_sibling_helpers import set_agent_env

    repo = _init_repo(tmp_path / "repo")
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir(parents=True)
    set_agent_env(monkeypatch, repo)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts_dir))
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")

    def build(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed = finalizer_git.git_changed_files(project_dir)
        if not changed:
            return (False, [], "", "")
        return (
            True,
            changed,
            "commit",
            "Uncommitted changes detected:\n" + "\n".join(changed),
        )

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build,
    )
    resolve_and_persist_finalizer_plan(
        PromptDirectives(), artifacts_dir=str(artifacts_dir)
    )
    capture_dirty_baseline(str(repo), str(artifacts_dir))

    base = _head(repo)
    sha = _commit(repo, "work.txt", "work\n", "agent raw commit")

    first = publish_final_context(artifacts_dir=str(artifacts_dir))
    absorbed = first.payload["commit_declaration"]["absorbed_raw_commits"]
    assert absorbed == [
        {
            "repo": "main",
            "path": finalizer_git.normalize_path(str(repo)),
            "commits": [{"sha": sha, "subject": "agent raw commit"}],
            "recovery_ref": "refs/sase/recovery/raw-commits/260521_120000",
            "reset_target": base,
        }
    ]
    assert _head(repo) == base
    assert len(first.context.obligations) == 1

    second = publish_final_context(artifacts_dir=str(artifacts_dir))
    assert second.payload["commit_declaration"]["absorbed_raw_commits"] == []
    assert second.context.context_digest == first.context.context_digest
