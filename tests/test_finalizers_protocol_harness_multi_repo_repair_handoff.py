"""Conflict-repair handoff across linked repos for the finalizer protocol."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import StitchCommandResult
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

from .finalizers_protocol_harness_test_helpers import (
    append_commit_result,
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
    submit_current_dirty,
)


def test_conflict_repair_handoff_commits_linked_repo_introduced_during_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo, name="main")
    sibling = dirty_repo(linked, name="sase-core", kind="sibling")
    dirty = {"repos": (main,)}
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[tuple[str, str, str | None]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        _excludes: tuple[str, ...],
        _context: object,
        bead_action: str | None = None,
    ) -> StitchCommandResult:
        calls.append((repo_arg.name, message, bead_action))
        if repo_arg.name == "main":
            return StitchCommandResult(
                returncode=EXIT_CODE_CONFLICT, stderr="conflict\n"
            )
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        append_commit_result(
            artifacts,
            repo_arg,
            sha="c" * 40,
            tree="d" * 40,
        )
        return StitchCommandResult(returncode=0, stdout=f"committed {repo_arg.name}\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
        bead_action: str | None = None,
    ) -> StitchCommandResult:
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout=f"resumed {repo_arg.name}\n")

    def on_invoke(_prompt: str, **_kwargs: object) -> InvokeResult:
        dirty["repos"] = (main, sibling)
        submit_current_dirty(
            artifacts,
            message="fix(lsp): warm hold target completions",
            bead_action="keep",
        )
        return InvokeResult(content="repaired linked")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.side_effect = on_invoke

    submit_commit(artifacts)
    result = run_controller(artifacts, provider)

    assert result.content == "done\n\nrepaired linked"
    assert [name for name, _message, _action in calls] == ["main", "sase-core"]
    assert calls[0][1] == "fix(final): reconcile commit declaration"
    assert calls[1][1] == "fix(lsp): warm hold target completions"
    assert calls[1][2] == "keep"
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert [marker["commit_sha"] for marker in markers] == ["a" * 40, "c" * 40]
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    evidence = payload["instances"][0]["evidence"]
    assert any(item["kind"] == "repair_handoff_declaration" for item in evidence)


def test_conflict_repair_residue_and_linked_handoff_both_commit_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo, name="main")
    sibling = dirty_repo(linked, name="sase-core", kind="sibling")
    dirty = {"repos": (main,)}
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
        bead_action: str | None = None,
    ) -> StitchCommandResult:
        calls.append(repo_arg.name)
        if repo_arg.name == "main" and calls.count("main") == 1:
            return StitchCommandResult(
                returncode=EXIT_CODE_CONFLICT, stderr="conflict\n"
            )
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        sha = "c" if repo_arg.name == "main" else "e"
        tree = "d" if repo_arg.name == "main" else "f"
        append_commit_result(
            artifacts,
            repo_arg,
            sha=sha * 40,
            tree=tree * 40,
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
        bead_action: str | None = None,
    ) -> StitchCommandResult:
        append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    def on_invoke(_prompt: str, **_kwargs: object) -> InvokeResult:
        dirty["repos"] = (main, sibling)
        submit_current_dirty(
            artifacts,
            message="fix(lsp): residue and linked",
            bead_action="keep",
        )
        return InvokeResult(content="repaired")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.side_effect = on_invoke

    submit_commit(artifacts)
    result = run_controller(artifacts, provider)

    assert result.content == "done\n\nrepaired"
    assert calls == ["main", "main", "sase-core"]
    markers = json.loads((artifacts / "commit_results.json").read_text())
    assert [marker["commit_sha"] for marker in markers] == [
        "a" * 40,
        "c" * 40,
        "e" * 40,
    ]


def test_conflict_repair_handoff_uses_host_order_for_multiple_remaining(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo, name="main")
    sibling = dirty_repo(linked, name="sase-core", kind="sibling")
    ext = dirty_repo(external, name="gh:sase-org/sase-core", kind="external")
    dirty = {"repos": (main,)}
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
        bead_action: str | None = None,
    ) -> StitchCommandResult:
        calls.append(repo_arg.name)
        if repo_arg.name == "main":
            return StitchCommandResult(
                returncode=EXIT_CODE_CONFLICT, stderr="conflict\n"
            )
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        append_commit_result(
            artifacts,
            repo_arg,
            sha="c" * 40,
            tree="d" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
        bead_action: str | None = None,
    ) -> StitchCommandResult:
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    def on_invoke(_prompt: str, **_kwargs: object) -> InvokeResult:
        dirty["repos"] = (sibling, ext, main)
        submit_current_dirty(
            artifacts,
            message="fix(core): remaining after repair",
            reverse_repositories=True,
        )
        return InvokeResult(content="repaired")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.side_effect = on_invoke

    submit_commit(artifacts)
    result = run_controller(artifacts, provider)

    assert result.content == "done\n\nrepaired"
    assert calls[0] == "main"
    assert calls[1:] == ["sase-core", "gh:sase-org/sase-core"]


def test_conflict_repair_handoff_updates_queued_repo_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo, name="main")
    research = dirty_repo(other, name="research", kind="sibling")
    dirty = {"repos": (main, research)}
    patch_dirty(monkeypatch, repo, dirty)
    messages: list[tuple[str, str]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        messages.append((repo_arg.name, message))
        if repo_arg.name == "main":
            return StitchCommandResult(
                returncode=EXIT_CODE_CONFLICT, stderr="conflict\n"
            )
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        append_commit_result(
            artifacts,
            repo_arg,
            sha="c" * 40,
            tree="d" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    def on_invoke(_prompt: str, **_kwargs: object) -> InvokeResult:
        submit_current_dirty(artifacts, message="fix(research): latest snapshot")
        return InvokeResult(content="repaired")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.side_effect = on_invoke

    submit_commit(artifacts)
    result = run_controller(artifacts, provider)

    assert result.content == "done\n\nrepaired"
    assert messages == [
        ("main", "fix(final): reconcile commit declaration"),
        ("research", "fix(research): latest snapshot"),
    ]
