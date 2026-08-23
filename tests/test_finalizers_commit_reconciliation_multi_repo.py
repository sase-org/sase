"""Multi-repo commit reconciliation coverage for the finalizer controller."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult

from .finalizers_commit_reconciliation_test_helpers import (
    dirty_repo,
    dirty_repos,
    marker,
    patch_multi_repo_state,
    persist_and_submit_commit,
    prepare_agent_env,
    write_commit_results,
)


def test_reconciliation_auto_commit_updates_marker_and_skips_sidecar_stitch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0ak: auto-committing a plans sidecar must prove the already-clean repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(repo),
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=("links/202608/one.md.json",),
            ),
        )
    }
    patch_multi_repo_state(monkeypatch, repo, dirty)
    write_commit_results(
        artifacts,
        [marker(plans, sha="a" * 40, tree="b" * 40, result="old")],
    )
    calls: list[str] = []

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        remaining = tuple(item for item in dirty["repos"] if item.name != "plans")
        dirty["repos"] = remaining
        payload = json.loads((artifacts / "commit_results.json").read_text())
        for index, item in enumerate(payload):
            if item.get("cwd") == str(plans):
                payload[index] = marker(plans, sha="c" * 40, tree="d" * 40)
                break
        else:
            payload.append(marker(plans, sha="c" * 40, tree="d" * 40))
        (artifacts / "commit_results.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
        )

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
        payload = json.loads((artifacts / "commit_results.json").read_text())
        payload.append(marker(Path(repo_arg.path), sha="e" * 40, tree="f" * 40))
        (artifacts / "commit_results.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

    persist_and_submit_commit(artifacts)
    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    assert calls == ["main"]
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"


def test_reconciliation_marker_for_other_checkout_does_not_prove_clean(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=("links/202608/one.md.json",),
            ),
        )
    }
    patch_multi_repo_state(monkeypatch, repo, dirty)
    write_commit_results(
        artifacts,
        [marker(plans, sha="a" * 40, tree="b" * 40, result="old")],
    )
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        dirty["repos"] = ()
        payload = json.loads((artifacts / "commit_results.json").read_text())
        payload.append(marker(repo, sha="c" * 40, tree="d" * 40))
        (artifacts / "commit_results.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, ()),
            artifact_links_auto_committed=True,
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    persist_and_submit_commit(artifacts)
    with pytest.raises(
        BuiltinCommitFinalizerError,
        match="vanished|discarded|attributable",
    ):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    runner.assert_not_called()


def test_unpublished_artifact_links_fail_after_proven_auto_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=("links/202608/one.md.json",),
            ),
        )
    }
    patch_multi_repo_state(monkeypatch, repo, dirty)
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        dirty["repos"] = ()
        write_commit_results(artifacts, [marker(plans, sha="c" * 40, tree="d" * 40)])
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, ()),
            artifact_links_auto_committed=True,
            artifact_link_publication_error=(
                "ERROR: chore(artifact-links): persist link indexes was committed "
                "locally but NOT published.\n  unpublished artifact-link commit(s): 1"
            ),
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    persist_and_submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="NOT published"):
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    runner.assert_not_called()
