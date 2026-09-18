"""Multi-repo dispatch coverage for the finalizer protocol."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.axe.runner_reporting import write_error_report
from sase.core.finalizer_wire import FinalizerInstanceResultWire
from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.declaration import (
    publish_final_context,
    submit_final_manifest,
)
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

from .finalizers_protocol_harness_test_helpers import (
    dirty_repo,
    patch_dirty,
    prepare_agent_env,
    run_controller,
    submit_commit,
    successful_stitch,
)


def _append_commit_result(
    artifacts: Path,
    repo: DirtyRepo,
    *,
    sha: str,
    tree: str,
) -> None:
    existing = artifacts / "commit_results.json"
    payload = (
        json.loads(existing.read_text(encoding="utf-8")) if existing.exists() else []
    )
    payload.append(
        {
            "cwd": repo.path,
            "result": "ok",
            "commit_sha": sha,
            "commit_tree": tree,
        }
    )
    existing.write_text(json.dumps(payload), encoding="utf-8")


def _submit_current_dirty(
    artifacts: Path,
    *,
    message: str,
    bead_action: str | None = None,
    reverse_repositories: bool = False,
) -> None:
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    if reverse_repositories:
        repositories.reverse()
    for decision in repositories:
        decision["action"] = "commit"
        decision["message"] = message
        if bead_action is not None:
            decision["bead_action"] = bead_action
        else:
            decision.pop("bead_action", None)
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))


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
        _append_commit_result(
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
        _append_commit_result(
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
        _append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout=f"resumed {repo_arg.name}\n")

    def on_invoke(_prompt: str, **_kwargs: object) -> InvokeResult:
        dirty["repos"] = (main, sibling)
        _submit_current_dirty(
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
        _append_commit_result(
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
        _append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    def on_invoke(_prompt: str, **_kwargs: object) -> InvokeResult:
        dirty["repos"] = (main, sibling)
        _submit_current_dirty(
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
        _append_commit_result(
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
        _append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    def on_invoke(_prompt: str, **_kwargs: object) -> InvokeResult:
        dirty["repos"] = (sibling, ext, main)
        _submit_current_dirty(
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
        _append_commit_result(
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
        _append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    def on_invoke(_prompt: str, **_kwargs: object) -> InvokeResult:
        _submit_current_dirty(artifacts, message="fix(research): latest snapshot")
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


def test_conflict_repair_handoff_missing_declaration_names_landed_sha(
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

    def run_stitch(
        _repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        dirty["repos"] = (sibling,)
        (artifacts / "final_submission.json").unlink()
        _append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="repaired without declaring")

    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_controller(artifacts, provider)

    rendered = str(exc_info.value)
    assert "a" * 40 in rendered
    assert "sase-core" in rendered
    assert "src/app.py" in rendered
    report_path = write_error_report(
        str(tmp_path),
        agent_model=None,
        agent_llm_provider=None,
        workflow_name="commit",
        cl_name="test",
        duration="1s",
        error_summary=rendered,
        error_traceback=None,
    )
    assert report_path is not None
    report = Path(report_path).read_text(encoding="utf-8")
    assert "a" * 40 in report
    assert "sase-core" in report


def test_conflict_repair_continuation_conflict_does_not_launch_repair(
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
        dirty["repos"] = (sibling,)
        _submit_current_dirty(artifacts, message="fix(core): remaining after repair")
        _append_commit_result(
            artifacts,
            repo_arg,
            sha="a" * 40,
            tree="b" * 40,
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="repaired")

    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="continuation bound"):
        run_controller(artifacts, provider)

    assert seen == ["main", "resume:main", "sase-core"]
    assert provider.invoke.call_count == 1


def test_same_repo_second_conflict_after_repair_later_cycle_fails_fast(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (dirty_repo(repo, name="main"),)}
    patch_dirty(monkeypatch, repo, dirty)
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    mutate = ConfiguredFinalizerInstance(
        instance_id="mutate",
        provider_ref="builtin@command",
        after=("commit",),
        config={"command": ["true"], "submission": "none"},
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    config = FinalizerConfig(
        defaults=("commit", "mutate"),
        required=(),
        instances={"commit": commit, "mutate": mutate},
        provenance={},
    )
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    attempt_fingerprints = {"value": {"src/app.py": ("M", "before-repair")}}
    monkeypatch.setattr(
        "sase.finalizers.commit_repair.dirty_path_fingerprints",
        lambda _path: dict(attempt_fingerprints["value"]),
    )
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
        dirty["repos"] = ()
        _append_commit_result(artifacts, repo_arg, sha="a" * 40, tree="b" * 40)
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    def run_mutate(*_args: object, **_kwargs: object) -> FinalizerInstanceResultWire:
        dirty["repos"] = (dirty_repo(repo, name="main"),)
        attempt_fingerprints["value"] = {"src/app.py": ("M", "after-repair")}
        return FinalizerInstanceResultWire(instance_id="mutate", status="success")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    monkeypatch.setattr(
        "sase.finalizers.controller.execute_non_commit_finalizer",
        run_mutate,
    )
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")

    submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_controller(artifacts, provider)

    assert exc_info.value.code == "second_unresolved_conflict"
    assert "second unresolved conflict in main" in str(exc_info.value)
    assert seen == ["main", "resume:main", "main"]
    assert provider.invoke.call_count == 1
