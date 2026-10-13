"""Execution-time backstop and context-publication absorption."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.finalizers.commit_types import BuiltinCommitFinalizerError
from sase.finalizers.commit_validation import raise_if_unpublished_local_commits
from sase.finalizers.declaration import (
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
)
from sase.finalizers.ledger import RETRYABLE_DIAGNOSTIC_CODES
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
from sase.llm_provider.types import InvokeResult
from sase.macro.directives import PromptDirectives

from ._commit_finalizer_raw_commits_helpers import (
    baseline_record,
    commit_file,
    init_repo,
    repo_head,
    write_baseline,
)
from ._commit_finalizer_sibling_helpers import set_agent_env


def test_backstop_fails_with_unpublished_local_commits(
    tmp_path: Path,
) -> None:
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
    sha = commit_file(repo, "work.txt", "work\n", "stranded agent work")

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

    repo = init_repo(tmp_path / "repo")
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

    base = repo_head(repo)
    sha = commit_file(repo, "work.txt", "work\n", "agent raw commit")

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
    assert repo_head(repo) == base
    assert len(first.context.obligations) == 1

    second = publish_final_context(artifacts_dir=str(artifacts_dir))
    assert second.payload["commit_declaration"]["absorbed_raw_commits"] == []
    assert second.context.context_digest == first.context.context_digest
