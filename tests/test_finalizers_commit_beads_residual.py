"""Residual beads-sidecar reconciliation after commit decisions.

Regression for the run that landed its primary commit yet failed with
``dirty_after_commit_decisions`` when bead event streams and ``issues.jsonl``
became dirty after the bead-sidecar commit was published. The finalizer gets
one bounded late pass that reuses the store lock, event-stream integrity
guard, commit marker, and publication verification; it never retries the
primary stitch and never deletes sidecar files.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from sase.finalizers.commit import BuiltinCommitFinalizerError, StitchCommandResult
from sase.finalizers.controller import run_finalizers
from sase.finalizers.reconciliation import PreparedCommitDirtyState
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_types import BeadStateSyncOutcome, DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV
from tests.sdd_policy_helpers import set_sdd_policy

from .finalizers_commit_reconciliation_test_helpers import (
    dirty_repo,
    dirty_repos,
    patch_multi_repo_state,
    persist_and_submit_commit,
    prepare_agent_env,
)


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _configure_identity(repo: Path) -> None:
    _run_git(repo, "config", "user.name", "SASE Test")
    _run_git(repo, "config", "user.email", "sase-test@example.invalid")


def _create_primary_repo(repo: Path) -> None:
    repo.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    _configure_identity(repo)
    (repo / ".gitignore").write_text(".sase/\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")


def _clone_sdd_store(repo: Path, bare: Path) -> Path:
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )
    sdd_store = repo / ".sase" / "sdd"
    sdd_store.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["git", "clone", str(bare), str(sdd_store)],
        capture_output=True,
        check=True,
    )
    _configure_identity(sdd_store)
    (sdd_store / "README.md").write_text("seed\n", encoding="utf-8")
    _run_git(sdd_store, "add", ".")
    _run_git(sdd_store, "commit", "-q", "-m", "initial sdd")
    _run_git(sdd_store, "push", "-q", "-u", "origin", "HEAD:main")
    return sdd_store


def _write_initial_bead_state(sdd_store: Path) -> tuple[Path, Path, str]:
    from sase.bead.model import IssueType
    from sase.bead.project import BeadProject

    with BeadProject.init(sdd_store, beads_dirname="beads") as project:
        bead = project.create("Residual bead", IssueType.PLAN)
        bead_id = bead.id
    beads = sdd_store / "beads"
    stream = beads / "events" / "streams" / f"{bead_id}.jsonl"
    issues = beads / "issues.jsonl"
    return stream, issues, bead_id


def _commit_and_publish_bead_state(sdd_store: Path, message: str) -> None:
    _run_git(sdd_store, "add", ".")
    _run_git(sdd_store, "commit", "-q", "-m", message)
    _run_git(sdd_store, "push", "-q", "origin", "HEAD:main")


def _append_late_machine_change(sdd_store: Path, bead_id: str) -> None:
    from sase.bead.project import BeadProject

    project = BeadProject(sdd_store, beads_dirname="beads")
    project.append_note(bead_id, "late valid note")


def _rewrite_stream(stream: Path) -> None:
    import json as _json

    lines = stream.read_text(encoding="utf-8").splitlines()
    if not lines:
        stream.write_text('{"rewritten":true}\n', encoding="utf-8")
        return
    first = _json.loads(lines[0])
    first["note"] = "rewritten-corruption"
    first["operation"] = "corrupted_operation"
    lines[0] = _json.dumps(first, separators=(",", ":"))
    stream.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _remote_subjects(bare: Path) -> list[str]:
    result = subprocess.run(
        ["git", "log", "--format=%s", "main"],
        cwd=bare,
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.splitlines() if line.strip()]


def _use_git_dirty_details(monkeypatch: pytest.MonkeyPatch) -> None:
    def build(project_dir: str) -> tuple[bool, list[str], str, str]:
        changed_files = finalizer_git.git_changed_files(project_dir)
        if not changed_files:
            return (False, [], "", "")
        details = "Uncommitted changes detected:\n" + "\n".join(changed_files)
        return (True, changed_files, "commit", details)

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build,
    )


def _setup_real_git_repos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path, Path, str, Path]:
    repo = tmp_path / "sase_10"
    bare = tmp_path / "sdd-store.git"
    _create_primary_repo(repo)
    sdd_store = _clone_sdd_store(repo, bare)
    stream, issues, bead_id = _write_initial_bead_state(sdd_store)
    _commit_and_publish_bead_state(sdd_store, "chore(beads): seed bead state")
    (repo / "feature.py").write_text("VALUE = 1\n", encoding="utf-8")

    artifacts = tmp_path / "artifacts"
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260926_120000")
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(repo))
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setenv("SASE_FINAL_TURN_NONCE", "nonce-1")
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)
    _use_git_dirty_details(monkeypatch)
    set_sdd_policy(monkeypatch, "separate_repo")
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )
    from sase.core.agent_identity_facade import AgentOwnerIdentity

    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("testuser", "testmachine"),
    )
    return repo, bare, sdd_store, stream, issues, bead_id, artifacts


def _primary_markers(artifacts: Path) -> list[dict]:
    path = artifacts / "commit_results.json"
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [item for item in payload if item.get("cwd")]


def test_late_machine_owned_bead_change_is_repaired_after_primary_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Late append-only bead dirt is committed once; the primary marker survives."""
    repo, bare, sdd_store, _stream, _issues, bead_id, artifacts = _setup_real_git_repos(
        tmp_path, monkeypatch
    )
    persist_and_submit_commit(artifacts)
    calls = {"n": 0}

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls["n"] += 1
        assert repo_arg.name == "main"
        _run_git(repo_arg.path, "add", ".")
        _run_git(repo_arg.path, "commit", "-q", "-m", message)
        sha = _run_git(repo_arg.path, "rev-parse", "HEAD").strip()
        tree = _run_git(repo_arg.path, "rev-parse", "HEAD^{tree}").strip()
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": str(repo_arg.path),
                        "result": sha,
                        "commit_sha": sha,
                        "commit_tree": tree,
                    }
                ]
            ),
            encoding="utf-8",
        )
        # Race: another writer appends valid bead events after the primary
        # commit lands but before the final residual check.
        _append_late_machine_change(sdd_store, bead_id)
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

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
    assert calls["n"] == 1
    markers = _primary_markers(artifacts)
    primary = [item for item in markers if item.get("cwd") == str(repo)]
    assert len(primary) == 1
    # The late bead commit was created and published; no primary retry.
    assert "chore(beads): sync bead state" in _remote_subjects(bare)
    assert _run_git(repo, "status", "--porcelain").strip() == ""
    project_dir = resolve_finalizer_project_dir()
    assert project_dir == str(repo)


def test_late_unrelated_stream_rewrite_is_refused_without_discarding_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rewritten event stream fails with an integrity diagnostic; history survives."""
    repo, _bare, sdd_store, stream, _issues, _bead_id, artifacts = (
        _setup_real_git_repos(tmp_path, monkeypatch)
    )
    ancestor = stream.read_text(encoding="utf-8")
    persist_and_submit_commit(artifacts)
    calls = {"n": 0}

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls["n"] += 1
        _run_git(repo_arg.path, "add", ".")
        _run_git(repo_arg.path, "commit", "-q", "-m", message)
        sha = _run_git(repo_arg.path, "rev-parse", "HEAD").strip()
        tree = _run_git(repo_arg.path, "rev-parse", "HEAD^{tree}").strip()
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": str(repo_arg.path),
                        "result": sha,
                        "commit_sha": sha,
                        "commit_tree": tree,
                    }
                ]
            ),
            encoding="utf-8",
        )
        _rewrite_stream(stream)
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    assert exc_info.value.code == "dirty_after_commit_decisions"
    assert calls["n"] == 1
    markers = _primary_markers(artifacts)
    assert any(item.get("cwd") == str(repo) for item in markers)
    # The integrity guard restores the ancestor instead of publishing corruption.
    assert ancestor.splitlines()[0] in stream.read_text(encoding="utf-8")
    assert stream.is_file()
    assert (
        "integrity" in str(exc_info.value).lower()
        or "bead sidecar" in str(exc_info.value).lower()
    )


def test_changes_arriving_during_extra_pass_still_fail_without_retrying_primary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One bounded pass only: new dirt during the pass stays a failure."""
    repo = tmp_path / "repo"
    repo.mkdir()
    beads = tmp_path / "beads"
    beads.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo)
    late = dirty_repo(beads, name="beads", kind="sdd", changed_files=("issues.jsonl",))
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (main,)}
    patch_multi_repo_state(monkeypatch, repo, dirty)
    persist_and_submit_commit(artifacts)
    calls = {"stitch": 0, "bead": 0}

    def fake_bead_sync(
        _project_dir: str, _artifacts_dir: Path | None = None
    ) -> BeadStateSyncOutcome:
        calls["bead"] += 1
        # The extra pass itself races: fresh dirt appears while committing.
        dirty["repos"] = (late,)
        return BeadStateSyncOutcome(
            committed=True,
            beads_root=str(beads),
            remaining_files=("issues.jsonl",),
        )

    def fake_prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, dirty["repos"]),
        )

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls["stitch"] += 1
        dirty["repos"] = (late,)
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

    monkeypatch.setattr(
        "sase.finalizers.commit.auto_commit_separate_sdd_store_if_possible",
        fake_bead_sync,
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state", fake_prepare
    )
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    assert exc_info.value.code == "dirty_after_commit_decisions"
    assert "issues.jsonl" in str(exc_info.value)
    assert calls["stitch"] == 1
    assert calls["bead"] == 1


def test_bead_lock_failure_reports_typed_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock failure keeps the sidecar path, files, and recovery steps."""
    repo = tmp_path / "repo"
    repo.mkdir()
    beads = tmp_path / "beads"
    beads.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    main = dirty_repo(repo)
    late = dirty_repo(beads, name="beads", kind="sdd", changed_files=("issues.jsonl",))
    dirty: dict[str, tuple[DirtyRepo, ...]] = {"repos": (main,)}
    patch_multi_repo_state(monkeypatch, repo, dirty)
    persist_and_submit_commit(artifacts)

    def fake_bead_sync(
        _project_dir: str, _artifacts_dir: Path | None = None
    ) -> BeadStateSyncOutcome:
        return BeadStateSyncOutcome(
            committed=False,
            beads_root=str(beads),
            remaining_files=("issues.jsonl",),
            reconcile_error="SddRepositoryHealthError: store write lock not acquired",
            reconcile_error_kind="lock",
        )

    def fake_prepare(_project_dir: str, _artifacts: Path) -> PreparedCommitDirtyState:
        return PreparedCommitDirtyState(
            dirty_state=dirty_repos(repo, dirty["repos"]),
        )

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        dirty["repos"] = (late,)
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

    monkeypatch.setattr(
        "sase.finalizers.commit.auto_commit_separate_sdd_store_if_possible",
        fake_bead_sync,
    )
    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state", fake_prepare
    )
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    message = str(exc_info.value)
    assert exc_info.value.code == "dirty_after_commit_decisions"
    assert str(beads) in message
    assert "issues.jsonl" in message
    assert "lock" in message.lower()
    assert "Recovery" in message


def test_unpublishable_late_bead_commit_fails_with_recovery_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A late bead commit that stays local fails even when the tree looks clean."""
    repo, _bare, sdd_store, _stream, _issues, bead_id, artifacts = (
        _setup_real_git_repos(tmp_path, monkeypatch)
    )
    _run_git(sdd_store, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    persist_and_submit_commit(artifacts)
    calls = {"n": 0}

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls["n"] += 1
        _run_git(repo_arg.path, "add", ".")
        _run_git(repo_arg.path, "commit", "-q", "-m", message)
        sha = _run_git(repo_arg.path, "rev-parse", "HEAD").strip()
        tree = _run_git(repo_arg.path, "rev-parse", "HEAD^{tree}").strip()
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / "commit_results.json").write_text(
            json.dumps(
                [
                    {
                        "cwd": str(repo_arg.path),
                        "result": sha,
                        "commit_sha": sha,
                        "commit_tree": tree,
                    }
                ]
            ),
            encoding="utf-8",
        )
        _append_late_machine_change(sdd_store, bead_id)
        return StitchCommandResult(returncode=0, stdout="ok\n")

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    assert exc_info.value.code in (
        "dirty_after_commit_decisions",
        "bead_state_unpublished",
    )
    assert (
        "NOT published" in str(exc_info.value)
        or "publication" in str(exc_info.value).lower()
        or "bead sidecar" in str(exc_info.value).lower()
    )
    assert calls["n"] == 1
    assert any(item.get("cwd") == str(repo) for item in _primary_markers(artifacts))


def test_agent_owned_residual_edit_is_not_hidden_by_bead_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Agent-owned primary dirt still fails; the bead pass does not mask it."""
    repo = tmp_path / "repo"
    repo.mkdir()
    artifacts = tmp_path / "artifacts"
    prepare_agent_env(monkeypatch, artifacts, repo)
    dirty: dict[str, bool] = {"value": True}
    from .finalizers_commit_reconciliation_test_helpers import patch_commit_state

    patch_commit_state(monkeypatch, repo, dirty)
    persist_and_submit_commit(artifacts)
    calls = {"n": 0}

    def run_stitch(
        repo_arg: DirtyRepo,
        message: str,
        excludes: tuple[str, ...],
        _context: object,
    ) -> StitchCommandResult:
        calls["n"] += 1
        # Stitch leaves agent-owned work dirty on purpose.
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

    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", run_stitch)

    with pytest.raises(BuiltinCommitFinalizerError) as exc_info:
        run_finalizers(
            provider=MagicMock(),
            original_prompt="do work",
            invoke_result=InvokeResult(content="done"),
            model_tier="large",
            suppress_output=True,
            model_override=None,
            artifacts_dir=str(artifacts),
        )

    assert exc_info.value.code in (
        "dirty_after_stitch",
        "dirty_after_commit_decisions",
    )
    assert (
        "uncommitted" in str(exc_info.value).lower()
        or "dirty" in str(exc_info.value).lower()
    )
    assert calls["n"] == 1
