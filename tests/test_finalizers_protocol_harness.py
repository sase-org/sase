"""Generic-controller acceptance coverage for the finalizer protocol."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from sase.agent.pending_handoff import PLAN_PENDING_MARKER
from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.config import (
    ConfiguredFinalizerInstance,
    FinalizerConfig,
    FinalizerFieldProvenance,
)
from sase.finalizers.controller import FinalizerControllerError, run_finalizers
from sase.finalizers.declaration import (
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import (
    DirtyRepo,
    DirtyState,
)
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT
from sase.xprompt.directives import PromptDirectives, extract_prompt_directives


def _prepare_agent_env(
    monkeypatch: pytest.MonkeyPatch,
    artifacts: Path,
    repo: Path,
) -> None:
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(repo))


def _dirty_state(
    repos: tuple[DirtyRepo, ...],
    *,
    project_dir: Path,
) -> DirtyState:
    return DirtyState(
        project_dir=str(project_dir),
        repos=repos,
        details="dirty" if repos else "",
    )


def _repo(path: Path, *, name: str = "main", kind: str = "main") -> DirtyRepo:
    return DirtyRepo(
        name=name,
        path=str(path),
        changed_files=("src/app.py",),
        kind=kind,  # type: ignore[arg-type]
    )


def _patch_dirty(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
) -> None:
    def collect(_project_dir: str, artifact_root: object = None) -> DirtyState:
        return _dirty_state(dirty["repos"], project_dir=repo)

    monkeypatch.setattr(
        "sase.finalizers.commit.resolve_finalizer_project_dir",
        lambda: str(repo),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: collect(str(repo)),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "content")},
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.git_changed_files",
        lambda path: (
            ["src/app.py"] if any(item.path == path for item in dirty["repos"]) else []
        ),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state",
        lambda _project_dir, _artifacts: PreparedCommitDirtyState(
            dirty_state=collect(str(repo)),
        ),
    )


def _submit_commit(artifacts: Path, *, action: str = "commit") -> None:
    resolve_and_persist_finalizer_plan(PromptDirectives(), artifacts_dir=str(artifacts))
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    for decision in manifest["payloads"][0]["payload"]["repositories"]:
        decision["action"] = action
        if action == "commit":
            decision["message"] = "fix(final): reconcile commit declaration"
        else:
            decision.pop("message", None)
            decision["reason"] = "not mine"
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))


def _run(artifacts: Path, provider: MagicMock | None = None) -> InvokeResult:
    return run_finalizers(
        provider=provider or MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )


def _successful_stitch(
    artifacts: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
    calls: list[str],
) -> Any:
    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append(repo_arg.name)
        remaining = tuple(item for item in dirty["repos"] if item.path != repo_arg.path)
        dirty["repos"] = remaining
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

    return run_stitch


def test_outside_sase_agent_is_a_safe_noop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.delenv("SASE_AGENT_TIMESTAMP", raising=False)
    provider = MagicMock()
    result = run_finalizers(
        provider=provider,
        original_prompt="do work",
        invoke_result=InvokeResult(content="outside"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )
    assert result.content == "outside"
    provider.invoke.assert_not_called()
    assert not (artifacts / "finalizer_result.json").exists()
    assert not (artifacts / "final_context.json").exists()


def test_missing_artifacts_dir_is_a_safe_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "run-1")
    result = run_finalizers(
        provider=MagicMock(),
        original_prompt="do work",
        invoke_result=InvokeResult(content="no-artifacts"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=None,
    )
    assert result.content == "no-artifacts"


def test_handoff_skips_generic_controller(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    _prepare_agent_env(monkeypatch, artifacts, repo)
    (artifacts / PLAN_PENDING_MARKER).write_text("1\n", encoding="utf-8")
    dirty = {"repos": (_repo(repo),)}
    _patch_dirty(monkeypatch, repo, dirty)
    provider = MagicMock()

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    result = _run(artifacts, provider)

    assert result.content == "done"
    provider.invoke.assert_not_called()
    assert not (artifacts / "finalizer_result.json").exists()


def test_final_none_writes_empty_success_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": ()}
    _patch_dirty(monkeypatch, repo, dirty)
    _, directives = extract_prompt_directives("%final:none\nDo work")

    resolve_and_persist_finalizer_plan(directives, artifacts_dir=str(artifacts))
    result = _run(artifacts)

    assert result.content == "done"
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["instances"] == []


def test_sequential_multi_repo_kinds_and_protected_excludes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            _repo(repo, name="main", kind="main"),
            _repo(linked, name="plans", kind="sibling"),
        )
    }
    _patch_dirty(monkeypatch, repo, dirty)
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

    _submit_commit(artifacts)
    result = _run(artifacts)

    assert result.content == "done"
    assert [name for name, _excludes in calls] == ["main", "plans"]
    assert calls[0][1] == ("legacy.txt",)


def test_first_repo_conflict_blocks_later_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {
        "repos": (
            _repo(repo, name="main"),
            _repo(other, name="research", kind="sibling"),
        )
    }
    _patch_dirty(monkeypatch, repo, dirty)
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

    _submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="second unresolved"):
        _run(artifacts, provider)

    assert seen == ["main", "resume:main"]
    assert provider.invoke.call_count == 1
    assert "conflict-repair" in provider.invoke.call_args.args[0]


def test_successful_conflict_resume_continues_same_stitch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (_repo(repo),)}
    _patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append("create")
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        calls.append("resume")
        dirty["repos"] = ()
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": repo_arg.path,
                        "result": "ok",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(
        content="resolved",
        usage={"input_tokens": 4},
    )

    _submit_commit(artifacts)
    result = _run(artifacts, provider)

    assert calls == ["create", "resume"]
    assert "resolved" in result.content
    assert result.usage == {"input_tokens": 4}
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"


@pytest.mark.parametrize("marker_matches_sidecar", [True, False])
def test_resumed_sidecar_row_is_matched_by_exact_cwd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    marker_matches_sidecar: bool,
) -> None:
    """A resumed sidecar row counts only when its cwd is that sidecar."""
    repo = tmp_path / "repo"
    repo.mkdir()
    sidecar = tmp_path / "plans"
    sidecar.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (_repo(sidecar, name="plans", kind="sibling"),)}
    _patch_dirty(monkeypatch, repo, dirty)
    calls: list[str] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        _message: str,
        _excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append("create")
        return StitchCommandResult(returncode=EXIT_CODE_CONFLICT, stderr="conflict\n")

    def resume(
        repo_arg: DirtyRepo,
        _context: object,
    ) -> StitchCommandResult:
        calls.append("resume")
        dirty["repos"] = ()
        marker_cwd = str(sidecar) if marker_matches_sidecar else str(repo)
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": marker_cwd,
                        "result": "ok",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="resumed\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_resume", resume)
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="resolved")

    _submit_commit(artifacts)
    if marker_matches_sidecar:
        result = _run(artifacts, provider)
        assert calls == ["create", "resume"]
        assert "resolved" in result.content
        payload = json.loads((artifacts / "finalizer_result.json").read_text())
        assert payload["status"] == "success"
    else:
        with pytest.raises(
            BuiltinCommitFinalizerError,
            match="no commit_results.json entry was recorded",
        ):
            _run(artifacts, provider)
        assert calls == ["create", "resume"]


def test_stale_checkpoint_after_conflict_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (_repo(repo),)}
    _patch_dirty(monkeypatch, repo, dirty)
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_create",
        lambda *_args: StitchCommandResult(returncode=EXIT_CODE_CONFLICT),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_resume",
        lambda *_args: StitchCommandResult(
            returncode=1,
            stderr="Could not find the expected commit at HEAD",
        ),
    )
    provider = MagicMock()
    provider.invoke.return_value = InvokeResult(content="tried")

    _submit_commit(artifacts)
    with pytest.raises(BuiltinCommitFinalizerError, match="resume failed"):
        _run(artifacts, provider)


def test_post_submit_edit_is_rejected_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (_repo(repo),)}
    _patch_dirty(monkeypatch, repo, dirty)
    fingerprints = {"value": {"src/app.py": ("M", "content")}}
    monkeypatch.setattr(
        "sase.finalizers.declaration.dirty_path_fingerprints",
        lambda _path: dict(fingerprints["value"]),
    )
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _submit_commit(artifacts)
    (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).write_text(
        "spent\n",
        encoding="utf-8",
    )
    fingerprints["value"] = {"src/app.py": ("M", "edited-after-submit")}
    with pytest.raises(
        (BuiltinCommitFinalizerError, FinalizerControllerError),
        match="stale|declaration|changed",
    ):
        _run(artifacts)

    runner.assert_not_called()


def test_later_finalizer_dirt_reactivates_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": ()}
    _patch_dirty(monkeypatch, repo, dirty)
    mutate = ConfiguredFinalizerInstance(
        instance_id="mutate",
        provider_ref="builtin@command",
        after=("commit",),
        config={"command": ["true"], "submission": "none"},
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    commit = ConfiguredFinalizerInstance(
        instance_id="commit",
        provider_ref="builtin@commit",
        max_attempts=2,
        provenance={"use": FinalizerFieldProvenance("test", None)},
    )
    config = FinalizerConfig(
        defaults=("commit", "mutate"),
        required=(),
        instances={"commit": commit, "mutate": mutate},
        provenance={},
    )
    monkeypatch.setattr("sase.finalizers.plan.load_finalizer_config", lambda: config)
    monkeypatch.setattr(
        "sase.finalizers.controller.load_finalizer_config",
        lambda: config,
    )
    calls: list[str] = []
    monkeypatch.setattr(
        "sase.finalizers.commit.run_stitch_create",
        _successful_stitch(artifacts, dirty, calls),
    )

    def run_mutate(*_args: object, **_kwargs: object) -> Any:
        dirty["repos"] = (_repo(repo),)
        from sase.core.finalizer_wire import FinalizerInstanceResultWire

        return FinalizerInstanceResultWire(instance_id="mutate", status="success")

    monkeypatch.setattr(
        "sase.finalizers.controller.execute_non_commit_finalizer",
        run_mutate,
    )

    def recover() -> InvokeResult:
        _submit_commit(artifacts)
        return InvokeResult(content="recovered", usage={"input_tokens": 1})

    provider = MagicMock()
    provider.invoke.side_effect = lambda *_args, **_kwargs: recover()

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    result = _run(artifacts, provider)

    assert "recovered" in result.content
    assert calls == ["main"]
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["cycles"] >= 1


def test_clean_commit_only_does_not_recover(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": ()}
    _patch_dirty(monkeypatch, repo, dirty)
    provider = MagicMock()

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    result = _run(artifacts, provider)

    assert result.content == "done"
    provider.invoke.assert_not_called()
    payload = json.loads((artifacts / "finalizer_result.json").read_text())
    assert payload["status"] == "success"
    assert payload["cycles"] == 1


def test_controller_no_progress_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty = {"repos": (_repo(repo),)}
    _patch_dirty(monkeypatch, repo, dirty)

    from sase.core.finalizer_wire import FinalizerInstanceResultWire
    from sase.finalizers.commit import BuiltinCommitExecution

    executions = {"count": 0}

    def fake_execute(*_args: object, **_kwargs: object) -> BuiltinCommitExecution:
        executions["count"] += 1
        return BuiltinCommitExecution(
            invoke_result=InvokeResult(content="done"),
            result=FinalizerInstanceResultWire(instance_id="commit", status="success"),
        )

    monkeypatch.setattr(
        "sase.finalizers.controller.execute_commit_finalizer",
        fake_execute,
    )

    _submit_commit(artifacts)
    with pytest.raises(FinalizerControllerError, match="no progress"):
        _run(artifacts)

    assert executions["count"] == 1
