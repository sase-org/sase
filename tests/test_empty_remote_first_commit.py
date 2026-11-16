"""Regression tests for the first commit into an empty remote.

Covers plan ``202611/empty_remote_first_commit.md`` changes 1-3:
empty-remote publish, unpushed-marker state check, and unborn host records.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from sase.finalizers.commit_transient import already_clean_fingerprint_before
from sase.finalizers.declaration_store import (
    FINAL_CONTEXT_HOST_FILENAME,
    HostRepositoryRecord,
    host_repository_records,
    read_host_repository_file,
    write_host_repository_file,
)
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_git_status import UNKNOWN_HEAD_SENTINEL
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.workflows.commit.checkpoint import CommitCheckpoint


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _init_remote(tmp_path: Path, name: str) -> Path:
    remote = tmp_path / f"{name}.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
        text=True,
    )
    return remote


def _clone(remote: Path, dest: Path) -> Path:
    subprocess.run(
        ["git", "clone", "-q", str(remote), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    _run_git(dest, "config", "user.email", "test@test.com")
    _run_git(dest, "config", "user.name", "Test")
    _run_git(dest, "config", "commit.gpgsign", "false")
    return dest


def _dirty_state(
    repo: Path, changed: tuple[str, ...], *, kind: str = "main", name: str = "main"
) -> DirtyState:
    return DirtyState(
        project_dir=normalize_path(str(repo)),
        repos=(
            DirtyRepo(
                name=name,
                path=normalize_path(str(repo)),
                changed_files=changed,
                kind=kind,  # type: ignore[arg-type]
            ),
        ),
        details="",
    )


def test_empty_remote_first_commit_pushes_and_sets_upstream(tmp_path: Path) -> None:
    """A clone of a bare empty remote publishes its root commit to origin/main."""
    from sase.vcs_provider import get_vcs_provider

    remote = _init_remote(tmp_path, "empty")
    clone = _clone(remote, tmp_path / "clone")
    (clone / "hello.txt").write_text("hi\n", encoding="utf-8")

    provider = get_vcs_provider(str(clone))
    ok, _ = provider.create_commit({"message": "feat: first commit"}, str(clone))

    assert ok is True
    local = _run_git(clone, "rev-parse", "HEAD")
    remote_main = subprocess.run(
        ["git", "--git-dir", str(remote), "rev-parse", "refs/heads/main"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert remote_main == local
    upstream = _run_git(
        clone, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"
    )
    assert upstream == "origin/main"


def test_non_empty_remote_missing_default_branch_still_fails(
    tmp_path: Path,
) -> None:
    """A non-empty remote without the detected default branch keeps failing."""
    from sase.vcs_provider import get_vcs_provider

    remote = _init_remote(tmp_path, "nonempty")
    seed = tmp_path / "seed"
    subprocess.run(
        ["git", "init", "-b", "other", str(seed)],
        check=True,
        capture_output=True,
    )
    _run_git(seed, "config", "user.email", "test@test.com")
    _run_git(seed, "config", "user.name", "Test")
    (seed / "a.txt").write_text("a\n", encoding="utf-8")
    _run_git(seed, "add", "-A")
    _run_git(seed, "commit", "-q", "-m", "seed other")
    _run_git(seed, "remote", "add", "origin", str(remote))
    _run_git(seed, "push", "-q", "-u", "origin", "other")

    clone = _clone(remote, tmp_path / "clone2")
    # Clone of a remote whose HEAD is unborn for main: checkout a new branch.
    _run_git(clone, "checkout", "-b", "work")
    (clone / "b.txt").write_text("b\n", encoding="utf-8")

    provider = get_vcs_provider(str(clone))
    ok, err = provider.create_commit({"message": "feat: work"}, str(clone))
    assert ok is False
    assert err is not None


def test_other_class_dispatch_error_writes_pushed_false_marker(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An ``other``-class failure after a local commit still records recovery."""
    import os

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True)
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "init")
    old = _run_git(repo, "rev-parse", "HEAD")
    (repo / "b.txt").write_text("b\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "second")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    from sase.workflows.commit._workflow_tracking import (
        CommitWorkflowTrackingMixin,
    )

    class FakeProvider:
        def revision_id(self, rev, cwd):
            out = _git(Path(cwd), "rev-parse", "--verify", rev)
            if out.returncode != 0:
                raise RuntimeError("no rev")
            return out.stdout.strip()

    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "x"},
        cwd=str(repo),
        pre_dispatch_revision=old,
    )
    mixin = CommitWorkflowTrackingMixin()
    mixin._method = "create_commit"
    mixin._payload = {"message": "x"}
    mixin._diff_path = None

    recorded = mixin._record_unpushed_commit_marker_if_present(
        cp, FakeProvider(), "fatal: couldn't find remote ref main"
    )
    assert recorded is not None
    assert recorded.commit_sha == _run_git(repo, "rev-parse", "HEAD")
    assert (artifacts / "commit_state.json").is_file()
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert any(m.get("pushed") is False for m in markers)
    _ = os.environ.pop("SASE_ARTIFACTS_DIR", None)


def test_proven_unborn_pre_dispatch_head_writes_marker(
    tmp_path: Path, monkeypatch
) -> None:
    """A proven-unborn pre-dispatch HEAD plus a new commit writes a marker."""
    repo = tmp_path / "unborn"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True)
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    assert _git(repo, "rev-parse", "--verify", "HEAD").returncode != 0
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "first")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    from sase.workflows.commit._workflow_tracking import (
        CommitWorkflowTrackingMixin,
    )

    class FakeProvider:
        def revision_id(self, rev, cwd):
            out = _git(Path(cwd), "rev-parse", "--verify", rev)
            if out.returncode != 0:
                raise RuntimeError("no rev")
            return out.stdout.strip()

    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "x"},
        cwd=str(repo),
        pre_dispatch_revision=None,
        pre_dispatch_unborn=True,
    )
    mixin = CommitWorkflowTrackingMixin()
    mixin._method = "create_commit"
    mixin._payload = {"message": "x"}
    mixin._diff_path = None

    recorded = mixin._record_unpushed_commit_marker_if_present(
        cp, FakeProvider(), "fatal: couldn't find remote ref main"
    )
    assert recorded is not None


def test_none_pre_dispatch_without_unborn_proof_writes_no_marker(
    tmp_path: Path, monkeypatch
) -> None:
    """A ``None`` baseline without unborn proof never invents a new commit."""
    repo = tmp_path / "repo2"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True)
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "init")

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    from sase.workflows.commit._workflow_tracking import (
        CommitWorkflowTrackingMixin,
    )

    class FailingProvider:
        def revision_id(self, rev, cwd):
            raise RuntimeError("cannot read HEAD")

    cp = CommitCheckpoint(
        method="create_commit",
        payload={"message": "x"},
        cwd=str(repo),
        pre_dispatch_revision=None,
    )
    assert cp.pre_dispatch_unborn is False
    mixin = CommitWorkflowTrackingMixin()
    mixin._method = "create_commit"
    mixin._payload = {"message": "x"}
    mixin._diff_path = None

    assert (
        mixin._record_unpushed_commit_marker_if_present(
            cp, FailingProvider(), "some other error"
        )
        is None
    )


def test_unborn_declaration_then_root_commit_leaves_no_discarded_evidence(
    tmp_path: Path,
) -> None:
    """Unborn before-HEAD plus a host root commit is attributable, not discard."""
    from sase.llm_provider.commit_finalizer_git_progress import (
        discarded_dirty_work_evidence,
    )

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True)
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("dirty\n", encoding="utf-8")

    before = _dirty_state(repo, ("README.md",))
    (records,) = host_repository_records(before)
    assert records.head is None
    assert records.head_unborn is True

    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "first commit\n\nSASE_AGENT=test-agent")
    import os

    os.environ["SASE_AGENT_NAME"] = "test-agent"
    try:
        fingerprint = already_clean_fingerprint_before(list(before.repos), (records,))
        assert fingerprint[0][1] == UNKNOWN_HEAD_SENTINEL
        after = DirtyState(project_dir=before.project_dir, repos=(), details="")
        evidence = discarded_dirty_work_evidence(
            before, after, fingerprint_before=fingerprint, artifacts_dir=None
        )
        # The root commit carries this agent's tag, so it is attributable.
        assert evidence == ()
    finally:
        os.environ.pop("SASE_AGENT_NAME", None)


def test_legacy_host_record_without_flag_keeps_old_fallback(
    tmp_path: Path,
) -> None:
    """A legacy record without ``head_unborn`` falls back to the current HEAD."""
    from sase.finalizers.commit_declaration import repository_decision_id
    from sase.llm_provider.commit_finalizer_git_status import git_head_commit_id

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True)
    _run_git(repo, "config", "user.email", "test@test.com")
    _run_git(repo, "config", "user.name", "Test")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _run_git(repo, "add", "-A")
    _run_git(repo, "commit", "-q", "-m", "init")

    legacy = HostRepositoryRecord(
        obligation_id="repo-abc",
        kind="main",
        name="main",
        path=normalize_path(str(repo)),
    )
    assert legacy.head_unborn is False
    dirty = DirtyState(
        project_dir=normalize_path(str(repo)),
        repos=(
            DirtyRepo(
                name="main",
                path=normalize_path(str(repo)),
                changed_files=(),
                kind="main",  # type: ignore[arg-type]
            ),
        ),
        details="",
    )
    (path, head, _changed) = already_clean_fingerprint_before(
        list(dirty.repos), (legacy,)
    )[0]
    assert head == git_head_commit_id(normalize_path(str(repo)))
    assert repository_decision_id(dirty.repos[0])


def test_host_repository_file_round_trips_with_and_without_field(
    tmp_path: Path,
) -> None:
    """The host file round-trips ``head_unborn`` and tolerates its absence."""
    path = tmp_path / FINAL_CONTEXT_HOST_FILENAME
    records = (
        HostRepositoryRecord(
            obligation_id="repo-abc",
            kind="main",
            name="main",
            path="/tmp/repo",
            path_count=1,
            head=None,
            head_unborn=True,
        ),
    )
    write_host_repository_file(path, context_digest="d", records=records)
    assert read_host_repository_file(path) == records

    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "context_digest": "d",
                "repositories": [
                    {
                        "obligation_id": "repo-abc",
                        "kind": "main",
                        "name": "main",
                        "path": "/tmp/repo",
                        "path_count": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (legacy,) = read_host_repository_file(path)
    assert legacy.head is None
    assert legacy.head_unborn is False
