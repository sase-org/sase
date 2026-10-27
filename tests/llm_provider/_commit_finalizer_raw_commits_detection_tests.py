"""Detector coverage for unrecorded local commits."""

from __future__ import annotations

from typing import get_args
import subprocess
from pathlib import Path

import pytest

from sase._linked_repo_markers import OpenedRepoKind
from sase.llm_provider.commit_finalizer_baseline import (
    capture_opened_repo_dirty_baseline,
    load_finalizer_baseline_records,
)
from sase.llm_provider import commit_finalizer_raw_commits as raw_commits
from sase.llm_provider.commit_finalizer_raw_commits import unrecorded_local_commits

from ._commit_finalizer_raw_commits_helpers import (
    NO_HEAD,
    baseline_record,
    commit_file,
    init_repo,
    record_host_stitch,
    repo_head,
    run_git,
    write_baseline,
)


def test_detects_raw_commits_in_main_and_sibling_oldest_first(
    tmp_path: Path,
) -> None:
    main = init_repo(tmp_path / "main")
    sibling = init_repo(tmp_path / "linked")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=main,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(main),
            ),
            baseline_record(
                repo_id="sibling:core",
                repo=sibling,
                kind="sibling",
                name="core",
                scope="run_start",
                head=repo_head(sibling),
            ),
        ],
    )

    sibling_base = repo_head(sibling)
    commit_file(sibling, "one.txt", "one\n", "agent raw one")
    second = commit_file(sibling, "two.txt", "two\n", "agent raw two")
    main_sha = commit_file(main, "m.txt", "m\n", "main raw")

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
    repo = init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    sha = commit_file(repo, "work.txt", "work\n", "host stitch commit")
    record_host_stitch(artifacts_dir, repo, sha, pushed=False)

    assert unrecorded_local_commits(artifacts_dir) == ()


def test_remote_reachable_fast_forwards_since_baseline_are_ignored(
    tmp_path: Path,
) -> None:
    repo = init_repo(tmp_path / "repo")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    run_git(repo, "remote", "add", "origin", str(remote))
    run_git(repo, "push", "-q", "-u", "origin", "HEAD")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    commit_file(repo, "pushed.txt", "pushed\n", "pushed after baseline")
    run_git(repo, "push", "-q", "origin", "HEAD")
    local_sha = commit_file(repo, "local.txt", "local\n", "local only")

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
    repo = init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    commit_file(
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
    repo = init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    commit_file(
        repo,
        "foreign.txt",
        "foreign\n",
        "foreign payload\n\nSASE_AGENT=other-agent",
    )
    own_sha = commit_file(
        repo,
        "own.txt",
        "own\n",
        "own payload\n\nSASE_AGENT=current-agent",
    )
    plain_sha = commit_file(repo, "plain.txt", "plain\n", "plain raw work")

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == [own_sha, plain_sha]


def _pin_owner_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    from sase.core.agent_identity_facade import (
        AgentIdentitySnapshot,
        AgentOwnerIdentity,
    )

    snapshot = AgentIdentitySnapshot(AgentOwnerIdentity("bbugyi200", "athena"))
    monkeypatch.setattr(
        AgentIdentitySnapshot,
        "current",
        classmethod(lambda cls: snapshot),
    )


def _own_linked_message(local_name: str) -> str:
    label = f"bbugyi200.athena.{local_name}"
    return (
        "own payload\n\n"
        f"SASE_AGENT=[{label}][1]\n\n"
        f"[1]: https://github.com/sase-org/sase--agents/blob/main/"
        f"families/{label}.md"
    )


def test_own_linked_form_trailer_counts_as_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent-meta"))
    _pin_owner_identity(monkeypatch)
    repo = init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    own_sha = commit_file(
        repo, "own.txt", "own\n", _own_linked_message("current-agent")
    )

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == [own_sha]


def test_own_global_form_trailer_counts_as_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent-meta"))
    _pin_owner_identity(monkeypatch)
    repo = init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    own_sha = commit_file(
        repo,
        "own.txt",
        "own\n",
        "own payload\n\nSASE_AGENT=bbugyi200.athena.current-agent",
    )

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == [own_sha]


def test_foreign_linked_form_trailer_is_not_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent-meta"))
    _pin_owner_identity(monkeypatch)
    repo = init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    commit_file(repo, "foreign.txt", "foreign\n", _own_linked_message("other-agent"))

    assert unrecorded_local_commits(artifacts_dir) == ()


def test_sase_type_without_agent_is_not_raw(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent-meta"))
    repo = init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    commit_file(
        repo,
        "memory.txt",
        "memory\n",
        "chore: initialize sase memory\n\nSASE_TYPE=memory",
    )

    assert unrecorded_local_commits(artifacts_dir) == ()


def test_plain_raw_commit_still_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent-meta"))
    repo = init_repo(tmp_path / "main")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="main",
                repo=repo,
                kind="main",
                name="main",
                scope="run_start",
                head=repo_head(repo),
            ),
        ],
    )

    plain_sha = commit_file(repo, "plain.txt", "plain\n", "plain raw work")

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert [commit.sha for commit in findings[0].commits] == [plain_sha]


def test_foreign_memory_tool_commits_in_sibling_do_not_fail_backstop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.finalizers.commit_validation import raise_if_unpublished_local_commits
    from sase.llm_provider.types import InvokeResult

    monkeypatch.setenv("SASE_AGENT_NAME", "sase-1li.3--1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(tmp_path / "agent-meta"))
    sibling = init_repo(tmp_path / "chezmoi")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="sibling:chezmoi",
                repo=sibling,
                kind="sibling",
                name="chezmoi",
                scope="run_start",
                head=repo_head(sibling),
            ),
        ],
    )

    for index in range(3):
        commit_file(
            sibling,
            f"home-{index}.txt",
            f"{index}\n",
            "chore: initialize sase memory\n\nSASE_TYPE=memory",
        )

    assert unrecorded_local_commits(artifacts_dir) == ()
    assert (
        raise_if_unpublished_local_commits(
            artifacts_dir,
            instance_id="commit",
            invoke_result=InvokeResult(content="done"),
        )
        is None
    )


def test_sdd_and_headless_baseline_records_are_skipped(
    tmp_path: Path,
) -> None:
    sdd = init_repo(tmp_path / "sdd")
    legacy = init_repo(tmp_path / "legacy")
    artifacts_dir = tmp_path / "artifacts"
    write_baseline(
        artifacts_dir,
        [
            baseline_record(
                repo_id="sdd:research",
                repo=sdd,
                kind="sdd",
                name="research",
                scope="run_start",
                head=repo_head(sdd),
            ),
            baseline_record(
                repo_id="main",
                repo=legacy,
                kind="main",
                name="main",
                scope="run_start",
                head=NO_HEAD,
            ),
        ],
    )

    commit_file(sdd, "note.md", "note\n", "sdd sidecar commit")
    commit_file(legacy, "work.txt", "work\n", "legacy raw commit")

    assert unrecorded_local_commits(artifacts_dir) == ()


def test_opened_repo_baseline_capture_records_head(tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "linked")
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
    assert records[0].head == repo_head(repo)


def test_raw_commit_kinds_cover_opened_repo_kinds() -> None:
    assert set(get_args(OpenedRepoKind)) <= raw_commits._RAW_COMMIT_REPO_KINDS


def test_detects_raw_commit_in_opened_linked_repo(tmp_path: Path) -> None:
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
    sha = commit_file(repo, "work.txt", "work\n", "agent raw linked commit")

    findings = unrecorded_local_commits(artifacts_dir)
    assert len(findings) == 1
    assert findings[0].kind == "linked"
    assert findings[0].name == "bob-mac-capture"
    assert [commit.sha for commit in findings[0].commits] == [sha]
