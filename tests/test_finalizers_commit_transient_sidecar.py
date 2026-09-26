"""Transient bead-sidecar handling in the commit finalizer.

A bead-sidecar sync/rebase can dirty a sidecar after the declaration was
accepted and clean it before the next scan. The finalizer refreshes dirty
state once after machine-owned reconciliation: a transient extra that
proves clean commits only the declared main checkout, while a persistently
dirty sidecar (or an unrelated edit) still fails with the repository name
and paths and is never committed.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
    execute_commit_finalizer,
)
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult

from .finalizers_commit_reconciliation_test_helpers import (
    dirty_repo,
    dirty_repos,
    patch_multi_repo_state,
    persist_and_submit_commit,
    prepare_agent_env,
)


def _execution_context(artifacts: Path) -> FinalizerExecutionContext:
    return FinalizerExecutionContext(
        artifacts_dir=str(artifacts),
        plan_digest="plan",
        run_id="run",
        agent_id="agent-1",
        turn_nonce="nonce",
        selected=("commit",),
    )


def _commit_instance() -> ConfiguredFinalizerInstance:
    return ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
    )


def _run_executor(
    artifacts: Path,
    run_stitch: object,
) -> object:
    return execute_commit_finalizer(
        _commit_instance(),
        _execution_context(artifacts),
        provider=MagicMock(),
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        stitch_runner=run_stitch,  # type: ignore[arg-type]
    )


def test_transient_extra_sidecar_cleans_on_recheck_commits_only_main(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    beads = tmp_path / "beads"
    beads.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo)
    transient = dirty_repo(
        beads, name="beads", kind="sdd", changed_files=("issues.jsonl",)
    )
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (main,)}
    patch_multi_repo_state(monkeypatch, repo, dirty)
    persist_and_submit_commit(artifacts)

    calls: list[str] = []
    prepare_calls = {"n": 0}

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        prepare_calls["n"] += 1
        if prepare_calls["n"] == 1:
            dirty["repos"] = (main, transient)
            return PreparedCommitDirtyState(
                dirty_state=dirty_repos(repo, (main, transient)),
            )
        if prepare_calls["n"] == 2:
            dirty["repos"] = (main,)
            return PreparedCommitDirtyState(dirty_state=dirty_repos(repo, (main,)))
        return PreparedCommitDirtyState(dirty_state=dirty_repos(repo, dirty["repos"]))

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        del message, excludes
        calls.append(repo_arg.name)
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": str(repo_arg.path),
                        "result": "abc123",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)

    execution = _run_executor(artifacts, run_stitch)

    assert execution.result.status == "success"
    assert calls == ["main"]
    assert prepare_calls["n"] >= 2


def test_persistent_extra_sidecar_fails_with_name_and_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    beads = tmp_path / "beads"
    beads.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo)
    persistent = dirty_repo(
        beads, name="beads", kind="sdd", changed_files=("issues.jsonl",)
    )
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (main,)}
    patch_multi_repo_state(monkeypatch, repo, dirty)
    persist_and_submit_commit(artifacts)

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, (main, persistent)),
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    runner = MagicMock()

    with pytest.raises(BuiltinCommitFinalizerError, match="beads.*issues\\.jsonl"):
        _run_executor(artifacts, runner)

    runner.assert_not_called()


def test_unrelated_sidecar_edit_still_stops_finalization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    beads = tmp_path / "beads"
    beads.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo)
    unrelated = dirty_repo(beads, name="beads", kind="sdd", changed_files=("notes.md",))
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (main,)}
    patch_multi_repo_state(monkeypatch, repo, dirty)
    persist_and_submit_commit(artifacts)

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, (main, unrelated)),
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    runner = MagicMock()

    with pytest.raises(BuiltinCommitFinalizerError, match="beads.*notes\\.md"):
        _run_executor(artifacts, runner)

    runner.assert_not_called()
