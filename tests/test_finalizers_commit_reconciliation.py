"""Commit reconciliation coverage for the finalizer controller."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
)
from sase.finalizers.declaration import (
    FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME,
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.controller import run_finalizers
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider.commit_finalizer_types import (
    DirtyRepo,
    DirtyState,
)
from sase.llm_provider.types import InvokeResult
from sase.xprompt.directives import PromptDirectives


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


def _dirty_state(repo: Path, *, dirty: bool) -> DirtyState:
    if not dirty:
        return DirtyState(project_dir=str(repo), repos=(), details="")
    return DirtyState(
        project_dir=str(repo),
        repos=(
            DirtyRepo(
                name="main",
                path=str(repo),
                changed_files=("src/app.py",),
                kind="main",
            ),
        ),
        details="dirty",
    )


def _repo(
    path: Path,
    *,
    name: str = "main",
    kind: str = "main",
    changed_files: tuple[str, ...] = ("src/app.py",),
) -> DirtyRepo:
    return DirtyRepo(
        name=name,
        path=str(path),
        changed_files=changed_files,
        kind=kind,  # type: ignore[arg-type]
    )


def _dirty_repos(project_dir: Path, repos: tuple[DirtyRepo, ...]) -> DirtyState:
    return DirtyState(
        project_dir=str(project_dir),
        repos=repos,
        details="dirty" if repos else "",
    )


def _changed_files_for(path: str, repos: tuple[DirtyRepo, ...]) -> list[str]:
    for repo in repos:
        if repo.path == path:
            return list(repo.changed_files)
    return []


def _fingerprints_for(
    path: str, repos: tuple[DirtyRepo, ...]
) -> dict[str, tuple[str, str]]:
    files = _changed_files_for(path, repos)
    if not files:
        return {"src/app.py": ("M", "content")}
    return dict.fromkeys(files, ("M", "content"))


def _patch_commit_state(
    monkeypatch: pytest.MonkeyPatch,
    repo: Path,
    dirty: dict[str, bool],
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.commit.resolve_finalizer_project_dir",
        lambda: str(repo),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_state(repo, dirty=dirty["value"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda _path: {"src/app.py": ("M", "content")},
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.git_changed_files",
        lambda _path: ["src/app.py"] if dirty["value"] else [],
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state",
        lambda _project_dir, _artifacts: PreparedCommitDirtyState(
            dirty_state=_dirty_state(repo, dirty=dirty["value"]),
        ),
    )


def _patch_multi_repo_state(
    monkeypatch: pytest.MonkeyPatch,
    project_dir: Path,
    dirty: dict[str, tuple[DirtyRepo, ...]],
) -> None:
    monkeypatch.setattr(
        "sase.finalizers.commit.resolve_finalizer_project_dir",
        lambda: str(project_dir),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration._collect_dirty_state",
        lambda _root: _dirty_repos(project_dir, dirty["repos"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda path: _fingerprints_for(path, dirty["repos"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.git_changed_files",
        lambda path: _changed_files_for(path, dirty["repos"]),
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state",
        lambda _project_dir, _artifacts: PreparedCommitDirtyState(
            dirty_state=_dirty_repos(project_dir, dirty["repos"]),
        ),
    )


def _write_commit_results(artifacts: Path, markers: list[dict[str, str]]) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "commit_results.json").write_text(
        json.dumps(markers),
        encoding="utf-8",
    )


def _marker(
    cwd: Path, *, sha: str, tree: str, result: str | None = None
) -> dict[str, str]:
    return {
        "cwd": str(cwd),
        "result": result if result is not None else sha,
        "commit_sha": sha,
        "commit_tree": tree,
    }


def _persist_and_submit_commit(
    artifacts: Path,
    *,
    action: str = "commit",
    message: str = "fix(final): reconcile commit declaration",
    reason: str = "operator refused dirty work",
) -> None:
    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = publication.payload["manifest_template"]
    for decision in manifest["payloads"][0]["payload"]["repositories"]:
        decision["action"] = action
        if action == "commit":
            decision["message"] = message
        else:
            decision.pop("message", None)
            decision["reason"] = reason
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))


def test_builtin_commit_executes_declared_stitch_without_reprompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, artifacts, repo)
    _patch_commit_state(monkeypatch, repo, dirty)
    calls: list[tuple[DirtyRepo, str, tuple[str, ...]]] = []

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls.append((repo_arg, message, tuple(excludes)))
        dirty["value"] = False
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": str(repo),
                        "result": "abc123",
                        "commit_sha": "a" * 40,
                        "commit_tree": "b" * 40,
                    }
                ]
            ),
            encoding="utf-8",
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)
    provider = MagicMock()

    _persist_and_submit_commit(artifacts)
    result = run_finalizers(
        provider=provider,
        original_prompt="do work",
        invoke_result=InvokeResult(content="done"),
        model_tier="large",
        suppress_output=True,
        model_override=None,
        artifacts_dir=str(artifacts),
    )

    assert result.content == "done"
    provider.invoke.assert_not_called()
    assert [(call[0].name, call[1], call[2]) for call in calls] == [
        ("main", "fix(final): reconcile commit declaration", ())
    ]
    assert not (artifacts / "commit_finalizer_result.json").exists()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    assert aggregate["instances"][0]["evidence"][0]["kind"] == "cwd"


def test_builtin_commit_refusal_fails_without_running_stitch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, artifacts, repo)
    _patch_commit_state(monkeypatch, repo, dirty)
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts, action="refuse", reason="not mine")
    with pytest.raises(BuiltinCommitFinalizerError, match="not mine"):
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
    assert not (artifacts / "commit_finalizer_result.json").exists()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "refused"
    assert aggregate["instances"][0]["refusal_reason"] == "not mine"


def test_post_submit_cleanup_fails_without_proven_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, artifacts, repo)
    _patch_commit_state(monkeypatch, repo, dirty)
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts)
    dirty["value"] = False
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


def test_stale_commit_results_do_not_prove_clean_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    dirty = {"value": True}
    _prepare_agent_env(monkeypatch, artifacts, repo)
    _patch_commit_state(monkeypatch, repo, dirty)
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "cwd": str(repo),
                    "result": "old",
                    "commit_sha": "a" * 40,
                    "commit_tree": "b" * 40,
                }
            ]
        ),
        encoding="utf-8",
    )
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts)
    dirty["value"] = False
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
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            _repo(repo),
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=("links/202608/one.md.json",),
            ),
        )
    }
    _patch_multi_repo_state(monkeypatch, repo, dirty)
    _write_commit_results(
        artifacts,
        [_marker(plans, sha="a" * 40, tree="b" * 40, result="old")],
    )
    calls: list[str] = []

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        remaining = tuple(item for item in dirty["repos"] if item.name != "plans")
        dirty["repos"] = remaining
        payload = json.loads((artifacts / "commit_results.json").read_text())
        for index, item in enumerate(payload):
            if item.get("cwd") == str(plans):
                payload[index] = _marker(plans, sha="c" * 40, tree="d" * 40)
                break
        else:
            payload.append(_marker(plans, sha="c" * 40, tree="d" * 40))
        (artifacts / "commit_results.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return PreparedCommitDirtyState(
            dirty_state=_dirty_repos(repo, remaining),
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
        payload.append(_marker(Path(repo_arg.path), sha="e" * 40, tree="f" * 40))
        (artifacts / "commit_results.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

    _persist_and_submit_commit(artifacts)
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
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=("links/202608/one.md.json",),
            ),
        )
    }
    _patch_multi_repo_state(monkeypatch, repo, dirty)
    _write_commit_results(
        artifacts,
        [_marker(plans, sha="a" * 40, tree="b" * 40, result="old")],
    )
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        dirty["repos"] = ()
        payload = json.loads((artifacts / "commit_results.json").read_text())
        payload.append(_marker(repo, sha="c" * 40, tree="d" * 40))
        (artifacts / "commit_results.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return PreparedCommitDirtyState(
            dirty_state=_dirty_repos(repo, ()),
            artifact_links_auto_committed=True,
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts)
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
    _prepare_agent_env(monkeypatch, artifacts, repo)
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=("links/202608/one.md.json",),
            ),
        )
    }
    _patch_multi_repo_state(monkeypatch, repo, dirty)
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        dirty["repos"] = ()
        _write_commit_results(artifacts, [_marker(plans, sha="c" * 40, tree="d" * 40)])
        return PreparedCommitDirtyState(
            dirty_state=_dirty_repos(repo, ()),
            artifact_links_auto_committed=True,
            artifact_link_publication_error=(
                "ERROR: chore(artifact-links): persist link indexes was committed "
                "locally but NOT published.\n  unpublished artifact-link commit(s): 1"
            ),
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts)
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


def _mixed_sidecar_files() -> tuple[str, ...]:
    return ("202608/report.md", "links/202608/one.md.json")


def _fingerprints_for_files(*paths: str) -> dict[str, tuple[str, str]]:
    return dict.fromkeys(paths, ("M", "content"))


def _spend_declaration_recovery(artifacts: Path) -> None:
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / FINAL_DECLARATION_RECOVERY_PROMPT_FILENAME).write_text(
        "spent\n",
        encoding="utf-8",
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
    _prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = _mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    _patch_multi_repo_state(monkeypatch, repo, dirty)
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
                    _repo(
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
            payload.append(_marker(plans, sha="c" * 40, tree="d" * 40))
            results_path.write_text(json.dumps(payload), encoding="utf-8")
        return PreparedCommitDirtyState(
            dirty_state=_dirty_repos(repo, remaining),
            artifact_links_auto_committed=committed_index,
            dirty_state_before=_dirty_repos(repo, before),
            fingerprints_before={
                item.path: _fingerprints_for_files(*item.changed_files)
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
        payload.append(_marker(Path(repo_arg.path), sha="e" * 40, tree="f" * 40))
        (artifacts / "commit_results.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

    _persist_and_submit_commit(artifacts)
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
    _prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = _mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    _patch_multi_repo_state(monkeypatch, repo, dirty)
    fingerprints = {
        "value": {str(plans): _fingerprints_for_files(report, index)},
    }
    monkeypatch.setattr(
        "sase.finalizers.declaration_store.dirty_path_fingerprints",
        lambda path: dict(fingerprints["value"].get(path, {})),
    )
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining = (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report,),
            ),
        )
        dirty["repos"] = remaining
        fingerprints["value"][str(plans)] = {report: ("M", "edited-after-submit")}
        _write_commit_results(artifacts, [_marker(plans, sha="c" * 40, tree="d" * 40)])
        return PreparedCommitDirtyState(
            dirty_state=_dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
            dirty_state_before=_dirty_repos(repo, before),
            fingerprints_before={str(plans): _fingerprints_for_files(report, index)},
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    _spend_declaration_recovery(artifacts)

    _persist_and_submit_commit(artifacts)
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
    _prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = _mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    _patch_multi_repo_state(monkeypatch, repo, dirty)
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining = (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, "unexpected.md"),
            ),
        )
        dirty["repos"] = remaining
        _write_commit_results(artifacts, [_marker(plans, sha="c" * 40, tree="d" * 40)])
        return PreparedCommitDirtyState(
            dirty_state=_dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
            dirty_state_before=_dirty_repos(repo, before),
            fingerprints_before={str(plans): _fingerprints_for_files(report, index)},
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)
    _spend_declaration_recovery(artifacts)

    _persist_and_submit_commit(artifacts)
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
    _prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = _mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    _patch_multi_repo_state(monkeypatch, repo, dirty)
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining = (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report,),
            ),
        )
        dirty["repos"] = remaining
        return PreparedCommitDirtyState(
            dirty_state=_dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
            dirty_state_before=_dirty_repos(repo, before),
            fingerprints_before={str(plans): _fingerprints_for_files(report, index)},
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts)
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
    _prepare_agent_env(monkeypatch, artifacts, repo)
    report, index = _mixed_sidecar_files()
    dirty: dict[str, tuple[DirtyRepo, ...]] = {
        "repos": (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report, index),
            ),
        )
    }
    _patch_multi_repo_state(monkeypatch, repo, dirty)
    runner = MagicMock()

    def prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        before = dirty["repos"]
        remaining = (
            _repo(
                plans,
                name="plans",
                kind="sibling",
                changed_files=(report,),
            ),
        )
        dirty["repos"] = remaining
        _write_commit_results(artifacts, [_marker(repo, sha="c" * 40, tree="d" * 40)])
        return PreparedCommitDirtyState(
            dirty_state=_dirty_repos(repo, remaining),
            artifact_links_auto_committed=True,
            dirty_state_before=_dirty_repos(repo, before),
            fingerprints_before={str(plans): _fingerprints_for_files(report, index)},
        )

    monkeypatch.setattr("sase.finalizers.commit.prepare_commit_dirty_state", prepare)
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    _persist_and_submit_commit(artifacts)
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
