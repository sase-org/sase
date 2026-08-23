"""Mixed sidecar commit reconciliation coverage for the finalizer controller."""

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
from sase.finalizers.declaration import FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult

from .finalizers_commit_reconciliation_test_helpers import (
    dirty_repo,
    dirty_repos,
    fingerprints_for_files,
    marker,
    mixed_sidecar_files,
    patch_multi_repo_state,
    persist_and_submit_commit,
    prepare_agent_env,
    spend_declaration_recovery,
    write_commit_results,
)


def test_reconciliation_mixed_sidecar_stitches_remaining_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """research.0w.cld: auto-commit the link index, then stitch the report."""
    repo = tmp_path / "repo"
    repo.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    patch_multi_repo_state(monkeypatch, repo, dirty)
    calls: list[str] = []

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining_repos: list[DirtyRepo] = []
        committed_index = False
        for item in before:
            if index not in item.changed_files:
                remaining_repos.append(item)
                continue
            committed_index = True
            leftover = tuple(path for path in item.changed_files if path != index)
            if leftover:
                remaining_repos.append(
                    dirty_repo(
                        Path(item.path),
                        name=item.name,
                        kind=item.kind,
                        changed_files=leftover,
                    )
                )
        remaining = tuple(remaining_repos)
        dirty["repos"] = remaining
        if committed_index:
            payload: list[object] = []
            results_path = artifacts / "commit_results.json"
            if results_path.is_file():
                payload = json.loads(results_path.read_text(encoding="utf-8"))
            payload.append(marker(plans, sha="c" * 40, tree="d" * 40))
            results_path.write_text(json.dumps(payload), encoding="utf-8")
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, remaining),
            artifact_links_auto_committed=committed_index,
            dirty_state_before=dirty_repos(repo, before),
            fingerprints_before={
                item.path: fingerprints_for_files(*item.changed_files)
                for item in before
            },
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
    assert calls == ["plans"]
    assert not (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).exists()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"


def test_reconciliation_mixed_sidecar_rejects_edited_residual_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    patch_multi_repo_state(monkeypatch, repo, dirty)
    fingerprints = {
        "value": {str(plans): fingerprints_for_files(report, index)},
    }
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda path: dict(fingerprints["value"].get(path, {})),
    )
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining = (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report,),
            ),
        )
        dirty["repos"] = remaining
        fingerprints["value"][str(plans)] = {report: ("M", "edited-after-submit")}
        write_commit_results(artifacts, [marker(plans, sha="c" * 40, tree="d" * 40)])
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
            dirty_state_before=dirty_repos(repo, before),
            fingerprints_before={str(plans): fingerprints_for_files(report, index)},
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    spend_declaration_recovery(artifacts)

    persist_and_submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="changed after submit"):
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


def test_reconciliation_mixed_sidecar_rejects_unexpected_residual_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    patch_multi_repo_state(monkeypatch, repo, dirty)
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining = (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, "unexpected.md"),
            ),
        )
        dirty["repos"] = remaining
        write_commit_results(artifacts, [marker(plans, sha="c" * 40, tree="d" * 40)])
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
            dirty_state_before=dirty_repos(repo, before),
            fingerprints_before={str(plans): fingerprints_for_files(report, index)},
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    spend_declaration_recovery(artifacts)

    persist_and_submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="changed after submit"):
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


def test_reconciliation_mixed_sidecar_rejects_transition_without_new_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    patch_multi_repo_state(monkeypatch, repo, dirty)
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining = (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report,),
            ),
        )
        dirty["repos"] = remaining
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
            dirty_state_before=dirty_repos(repo, before),
            fingerprints_before={str(plans): fingerprints_for_files(report, index)},
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


def test_reconciliation_mixed_sidecar_rejects_marker_for_other_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    plans = tmp_path / "plans"
    plans.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    patch_multi_repo_state(monkeypatch, repo, dirty)
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining = (
            dirty_repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report,),
            ),
        )
        dirty["repos"] = remaining
        write_commit_results(artifacts, [marker(repo, sha="c" * 40, tree="d" * 40)])
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
            dirty_state_before=dirty_repos(repo, before),
            fingerprints_before={str(plans): fingerprints_for_files(report, index)},
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
