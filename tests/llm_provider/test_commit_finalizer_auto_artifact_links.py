"""Finalizer reconciliation for implicit artifact-link index writes."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
from unittest.mock import MagicMock

import pytest

from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.finalizers.commit import BuiltinCommitFinalizerError
from sase.finalizers.controller import run_finalizers
from sase.finalizers.declaration import (
    SASE_FINAL_TURN_NONCE_ENV,
    publish_final_context,
    submit_final_manifest,
)
from sase.finalizers.plan import resolve_and_persist_finalizer_plan
from sase.finalizers.reconciliation import prepare_commit_dirty_state
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.types import InvokeResult
from sase.sdd._artifact_link_ignore import ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    ArtifactLinkStore,
)
from sase.linked_repos import LINKED_REPOS_JSON_ENV
from sase.sdd.store import SddStore
from sase.sibling_repos import SIBLING_REPOS_JSON_ENV
from sase.xprompt.directives import PromptDirectives
from tests._conftest_environment import redirect_sase_home


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_git(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )


def _commit_all(repo: Path, message: str = "initial") -> None:
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", message)


def _create_primary(tmp_path: Path) -> Path:
    main = tmp_path / "main"
    _init_git(main)
    (main / "README.md").write_text("main\n", encoding="utf-8")
    _commit_all(main)
    return main


def _create_sidecar(tmp_path: Path, name: str) -> Path:
    repo = tmp_path / name
    _init_git(repo)
    (repo / "README.md").write_text(f"{name}\n", encoding="utf-8")
    _commit_all(repo)
    return repo


def _set_finalizer_env(monkeypatch: pytest.MonkeyPatch, project_dir: Path) -> None:
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "260821_120000")
    monkeypatch.setenv("CODEX_PROJECT_DIR", str(project_dir))
    monkeypatch.delenv("SASE_DISABLE_COMMIT_STOP_HOOK", raising=False)
    monkeypatch.delenv(SIBLING_REPOS_JSON_ENV, raising=False)

    def build(path: str) -> tuple[bool, list[str], str, str]:
        changed = finalizer_git.git_changed_files(path)
        if not changed:
            return (False, [], "", "")
        return (True, changed, "commit", "Uncommitted changes detected")

    monkeypatch.setattr(
        "sase.llm_provider.commit_finalizer_state.build_commit_details",
        build,
    )
    monkeypatch.setattr(
        "sase.config.load_merged_config",
        lambda: {"sdd": {"push_after_commit": False}},
    )


def _sdd_store(plans: Path, research: Path | None = None) -> SddStore:
    sidecar_dirs = {"research": research} if research is not None else {}
    return SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        sidecar_dirs=sidecar_dirs,
    )


def _read_row(target: str) -> dict[str, object]:
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "source_ref": "agent:alice.athena.09l",
        "relation": "read",
        "target_ref": target,
        "description": "Need the plan context",
        "origin": "read",
        "created_by": "alice.athena.09l",
        "created_at": "2026-08-21T12:00:00Z",
        "uses": 1,
    }


def _record_reads(plans: Path, *targets: str) -> ArtifactLinkStore:
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans},
    )
    for target in targets:
        store.upsert_row(_read_row(target))
    return store


def _head_files(repo: Path) -> set[str]:
    names = _run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    return {line for line in names.splitlines() if line.strip()}


def _prepare(artifacts_dir: Path):
    return prepare_commit_dirty_state(
        resolve_finalizer_project_dir(),
        artifacts_dir,
    )


def test_two_implicit_plan_reads_commit_once_without_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = _create_primary(tmp_path)
    plans = _create_sidecar(tmp_path, "plans")
    _set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: _sdd_store(plans)
    )
    _record_reads(
        plans,
        "plan:202608/one.md",
        "plan:202608/two.md",
    )
    sidecars = list((plans / "links").rglob("*"))
    assert len([path for path in sidecars if path.is_file()]) == 4
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is True
    assert state.artifact_link_publication_error is None
    assert state.dirty_state.is_clean
    assert _run_git(plans, "status", "--porcelain", "--untracked-files=all") == ""
    assert "chore(artifact-links): persist link indexes" in _run_git(
        plans, "log", "-1", "--pretty=%s"
    )
    files = _head_files(plans)
    assert files == {
        "links/202608/one.md.json",
        "links/202608/two.md.json",
        ".gitignore",
    }
    assert ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN in (plans / ".gitignore").read_text(
        encoding="utf-8"
    )
    assert (plans / "links" / "202608" / "one.md.lock").is_file()
    assert (plans / "links" / "202608" / "two.md.lock").is_file()

    second = _prepare(artifacts)
    assert second.artifact_links_auto_committed is False
    assert int(_run_git(plans, "rev-list", "--count", "HEAD").strip()) == 2


def test_mixed_unrelated_dirt_is_left_for_the_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = _create_primary(tmp_path)
    plans = _create_sidecar(tmp_path, "plans")
    _set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: _sdd_store(plans)
    )
    _record_reads(plans, "plan:202608/one.md")
    (plans / "notes.md").write_text("unrelated agent edit\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is True
    remaining = [
        path for repo in state.dirty_state.repos for path in repo.changed_files
    ]
    assert any(path.endswith("notes.md") for path in remaining)
    assert not any(path.endswith(".json") for path in remaining)
    assert "links/202608/one.md.json" in _head_files(plans)


def test_pre_existing_dirty_index_is_not_auto_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = _create_primary(tmp_path)
    plans = _create_sidecar(tmp_path, "plans")
    _set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: _sdd_store(plans)
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    store = _record_reads(plans, "plan:202608/preexisting.md")
    capture_dirty_baseline(str(main), str(artifacts))
    store.upsert_row(_read_row("plan:202608/new.md"))

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is True
    files = _head_files(plans)
    assert "links/202608/new.md.json" in files
    assert "links/202608/preexisting.md.json" not in files
    status = _run_git(plans, "status", "--porcelain", "--untracked-files=all")
    assert "preexisting.md.json" in status


def test_malformed_candidates_remain_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = _create_primary(tmp_path)
    plans = _create_sidecar(tmp_path, "plans")
    _set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: _sdd_store(plans)
    )
    _record_reads(plans, "plan:202608/one.md")
    broken = plans / "links" / "202608" / "broken.md.json"
    broken.write_text("{not-json", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is True
    remaining = [
        path for repo in state.dirty_state.repos for path in repo.changed_files
    ]
    assert any(path.endswith("broken.md.json") for path in remaining)


def test_multiple_sidecars_commit_once_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = _create_primary(tmp_path)
    plans = _create_sidecar(tmp_path, "plans")
    research = _create_sidecar(tmp_path, "research")
    _set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store",
        lambda *_args: _sdd_store(plans, research),
    )
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )
    store.upsert_row(_read_row("plan:202608/one.md"))
    store.upsert_row(
        {
            **_read_row("research:202608/source.md"),
            "target_ref": "research:202608/source.md",
        }
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is True
    assert state.dirty_state.is_clean
    assert "links/202608/one.md.json" in _head_files(plans)
    assert "links/202608/source.md.json" in _head_files(research)


def test_publication_failure_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = _create_primary(tmp_path)
    bare = tmp_path / "plans.git"
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(bare)],
        capture_output=True,
        check=True,
    )
    plans = tmp_path / "plans"
    subprocess.run(
        ["git", "clone", str(bare), str(plans)],
        capture_output=True,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=plans, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=plans,
        check=True,
    )
    (plans / "README.md").write_text("seed\n", encoding="utf-8")
    _commit_all(plans)
    _run_git(plans, "push", "-q", "-u", "origin", "HEAD:main")
    _run_git(plans, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    _set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: _sdd_store(plans)
    )
    _record_reads(plans, "plan:202608/one.md")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is True
    assert state.artifact_link_publication_error is not None
    error = state.artifact_link_publication_error
    assert "was committed locally but NOT published" in error
    assert "unpublished artifact-link commit(s)" in error
    assert str(plans) in error
    assert "chore(artifact-links): persist link indexes" in _run_git(
        plans, "log", "-1", "--pretty=%s"
    )

    _run_git(plans, "remote", "set-url", "origin", str(bare))
    from sase.sdd._artifact_link_commit import _ensure_artifact_link_commit_published

    assert _ensure_artifact_link_commit_published(plans) is None
    remote_log = subprocess.run(
        ["git", "log", "--format=%s", "main"],
        cwd=bare,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "chore(artifact-links): persist link indexes" in remote_log


def test_executor_accepts_artifact_link_auto_commit_against_existing_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Marker timing cannot regress behind mocks of prepare_commit_dirty_state."""
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = _create_primary(tmp_path)
    plans = _create_sidecar(tmp_path, "plans")
    _set_finalizer_env(monkeypatch, main)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv(LINKED_REPOS_JSON_ENV, "[]")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: _sdd_store(plans)
    )
    _record_reads(plans, "plan:202608/one.md")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    plans_cwd = str(plans.expanduser().resolve())
    (artifacts / "commit_results.json").write_text(
        json.dumps(
            [
                {
                    "cwd": plans_cwd,
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

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    repositories = manifest["payloads"][0]["payload"]["repositories"]
    assert repositories, "plans sidecar should be a commit obligation"
    for decision in repositories:
        decision["action"] = "commit"
        decision["message"] = "chore(artifact-links): persist link indexes"
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))

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
    runner.assert_not_called()
    aggregate = json.loads(
        (artifacts / "finalizer_result.json").read_text(encoding="utf-8")
    )
    assert aggregate["status"] == "success"
    assert "chore(artifact-links): persist link indexes" in _run_git(
        plans, "log", "-1", "--pretty=%s"
    )
    markers = json.loads(
        (artifacts / "commit_results.json").read_text(encoding="utf-8")
    )
    shas = {item.get("commit_sha") for item in markers}
    assert "a" * 40 in shas
    assert any(
        item.get("cwd") == plans_cwd and item.get("commit_sha") != "a" * 40
        for item in markers
    )
    assert _run_git(plans, "status", "--porcelain", "--untracked-files=all") == ""


def test_executor_rejects_artifact_link_auto_commit_without_new_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = _create_primary(tmp_path)
    plans = _create_sidecar(tmp_path, "plans")
    _set_finalizer_env(monkeypatch, main)
    monkeypatch.setenv("SASE_AGENT_NAME", "agent-1")
    monkeypatch.setenv(SASE_FINAL_TURN_NONCE_ENV, "nonce-1")
    monkeypatch.setenv(LINKED_REPOS_JSON_ENV, "[]")
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: _sdd_store(plans)
    )
    _record_reads(plans, "plan:202608/one.md")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))

    real_prepare = prepare_commit_dirty_state

    def prepare_without_ledger(project_dir: str, artifacts_dir: Path):
        before = []
        existing = artifacts / "commit_results.json"
        if existing.is_file():
            before = json.loads(existing.read_text(encoding="utf-8"))
        state = real_prepare(project_dir, artifacts_dir)
        existing.write_text(json.dumps(before), encoding="utf-8")
        return state

    monkeypatch.setattr(
        "sase.finalizers.commit.prepare_commit_dirty_state",
        prepare_without_ledger,
    )
    runner = MagicMock()
    monkeypatch.setattr("sase.finalizers.commit.run_stitch_create", runner)

    resolve_and_persist_finalizer_plan(
        PromptDirectives(),
        artifacts_dir=str(artifacts),
    )
    publication = publish_final_context(artifacts_dir=str(artifacts))
    manifest = deepcopy(publication.payload["manifest_template"])
    for decision in manifest["payloads"][0]["payload"]["repositories"]:
        decision["action"] = "commit"
        decision["message"] = "chore(artifact-links): persist link indexes"
    submit_final_manifest(manifest, artifacts_dir=str(artifacts))

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
    assert "chore(artifact-links): persist link indexes" in _run_git(
        plans, "log", "-1", "--pretty=%s"
    )
