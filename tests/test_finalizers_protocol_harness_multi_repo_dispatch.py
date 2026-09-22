"""Multi-repo dispatch ordering and conflict blocking for the finalizer protocol."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
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
    successful_stitch,
)


def test_sequential_multi_repo_kinds_and_protected_excludes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            dirty_repo(repo, name="main", kind="main"),
            dirty_repo(linked, name="plans", kind="sibling"),
        )
    }
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[tuple[str, tuple[str, ...]]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append((repo_arg.name, tuple(excludes)))
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        payload = []
        existing = artifacts / "commit_results.json"
        if existing.is_file():
            payload = json.loads(existing.read_text(encoding="utf-8"))
        payload.append(
            {
                "cwd": repo_arg.path,
                "result": "ok",
                "commit_sha": "a" * 40,
                "commit_tree": "b" * 40,
            }
        )
        existing.write_text(json.dumps(payload), encoding="utf-8")
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr(
        "sase.finalizers.commit._protected_baseline_paths",
        lambda _artifacts, _path: ("legacy.txt",),
    )

    submit_commit(artifacts)
    result = run_controller(artifacts)

    assert result.content == "done"
    assert [name for name, _excludes in calls] == ["main", "plans"]
    assert calls[0][1] == ("legacy.txt",)


def test_reversed_manifest_still_executes_in_host_context_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            dirty_repo(repo, name="main", kind="main"),
            dirty_repo(linked, name="plans", kind="sibling"),
        )
    }
    patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_create",
        successful_stitch(artifacts, dirty, calls),
    )

    submit_commit(artifacts, reverse_repositories=True)
    result = run_controller(artifacts)

    assert result.content == "done"
    assert calls == ["main", "plans"]


def test_reversed_manifest_first_host_repo_conflict_blocks_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            dirty_repo(repo, name="main"),
            dirty_repo(other, name="research", kind="sibling"),
        )
    }
    patch_dirty(monkeypatch, repo, dirty)
    seen: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        seen.append(repo_arg.name)
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        seen.append(f"resume:{repo_arg.name}")
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="still\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="tried to repair")

    submit_commit(artifacts, reverse_repositories=True)
    with pytest.raises(BuiltinCommitFinalizerError, match="second unresolved"):
        run_controller(artifacts, provider)

    assert seen == ["main", "resume:main"]
    assert provider.invoke.call_count == 1


def test_first_repo_conflict_blocks_later_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            dirty_repo(repo, name="main"),
            dirty_repo(other, name="research", kind="sibling"),
        )
    }
    patch_dirty(monkeypatch, repo, dirty)
    seen: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        seen.append(repo_arg.name)
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        seen.append(f"resume:{repo_arg.name}")
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="still\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="tried to repair")

    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="second unresolved"):
        run_controller(artifacts, provider)

    assert seen == ["main", "resume:main"]
    assert provider.invoke.call_count == 1
    assert "conflict-repair" in provider.invoke.call_args.args[0]


def test_repaired_repo_conflict_does_not_starve_later_repo_conflict(
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
    seen: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        seen.append(repo_arg.name)
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        seen.append(f"resume:{repo_arg.name}")
        dirty["repos"] = tuple(
            item for item in dirty["repos"] if item.path != repo_arg.path
        )
        marker_char = "a" if repo_arg.name == "main" else "c"
        tree_char = "b" if repo_arg.name == "main" else "d"
        append_commit_result(
            artifacts,
            repo_arg,
            sha=marker_char * 40,
            tree=tree_char * 40,
        )
        return StitchCommandResult(returncode=0, stdout=f"resumed {repo_arg.name}\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.side_effect = [
        InvokeResult(content="resolved main"),
        InvokeResult(content="resolved research"),
    ]

    submit_commit(artifacts)
    result = run_controller(artifacts, provider)

    assert result.content == "done\n\nresolved main\n\nresolved research"
    assert seen == ["main", "resume:main", "research", "resume:research"]
    assert provider.invoke.call_count == 2
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["instances"][0]["attempts"] == [{"attempt": 1, "status": "success"}]

    artifact_dir = artifacts / "finalizers" / "commit"
    assert (artifact_dir / "conflict_repair_prompt.main.md").is_file()
    assert (artifact_dir / "conflict_repair_prompt.research.md").is_file()
    assert not (artifact_dir / "conflict_repair_prompt.md").exists()
    assert (artifact_dir / "conflict_repair_response.main.md").read_text(
        encoding="utf-8"
    ) == "resolved main"
    assert (artifact_dir / "conflict_repair_response.research.md").read_text(
        encoding="utf-8"
    ) == "resolved research"
    assert (artifact_dir / "attempt-1.main-conflict-repair.stdout").is_file()
    assert (artifact_dir / "attempt-1.research-conflict-repair.stdout").is_file()
