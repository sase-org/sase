"""Regression coverage for hidden agents-sidecar finalizer races."""

from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest

from sase.agents_sync.git_sync_ops import AGENTS_SYNC_AUTO_COMMIT_TYPE
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_git_progress import (
    discarded_dirty_work_evidence,
    progress_fingerprint,
)
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.sdd.store import AGENTS_SIDECAR_ROLE, SDD_STORAGE_SIDECAR_REPOS, SddStore

from ._commit_finalizer_sibling_helpers import (
    commit_all,
    init_git_repo,
    set_agent_env,
    set_clean_main,
)


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _sidecar_store(
    *,
    plans: Path,
    agents: Path,
    visible: Path | None = None,
) -> SddStore:
    sidecar_dirs = {AGENTS_SIDECAR_ROLE: agents}
    if visible is not None:
        sidecar_dirs["research"] = visible
    return SddStore(
        storage=SDD_STORAGE_SIDECAR_REPOS,
        sdd_dir=plans,
        repo_root=plans,
        sidecar_dirs=sidecar_dirs,
        sidecar_remote_urls={
            role: f"git@example.invalid:sase/{role}.git" for role in sidecar_dirs
        },
    )


def _use_sdd_store(monkeypatch: pytest.MonkeyPatch, store: SddStore) -> None:
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)


def _disable_agents_prompt_archive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_publication_project_key",
        lambda *_args, **_kwargs: None,
    )


def _resolve_agents_prompt_archive_to(
    monkeypatch: pytest.MonkeyPatch,
    agents: Path,
) -> None:
    monkeypatch.setattr(
        "sase.agents_sync.commit_publication.resolve_publication_project_key",
        lambda *_args, **_kwargs: "test-project",
    )
    monkeypatch.setattr(
        "sase.agents_sync.targets.resolve_sync_targets",
        lambda *_args, **_kwargs: SimpleNamespace(
            targets=(SimpleNamespace(sidecar_path=agents),)
        ),
    )


def test_hidden_agents_sidecar_is_excluded_from_sdd_dirty_collection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    visible = tmp_path / "research"
    for repo in (main, plans, agents, visible):
        init_git_repo(repo)
    (agents / "README.md").write_text(
        "machine-managed sync payload\n", encoding="utf-8"
    )
    (visible / "report.md").write_text("agent-authored report\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    _use_sdd_store(
        monkeypatch,
        _sidecar_store(plans=plans, agents=agents, visible=visible),
    )
    _disable_agents_prompt_archive(monkeypatch)

    dirty_state = collect_dirty_state(str(main), artifact_root=tmp_path / "artifacts")

    assert [
        (repo.kind, repo.name, repo.path, repo.changed_files)
        for repo in dirty_state.repos
    ] == [
        (
            "sdd",
            "research",
            finalizer_git.normalize_path(str(visible)),
            ("report.md",),
        )
    ]
    assert all(
        repo.path != finalizer_git.normalize_path(str(agents))
        for repo in dirty_state.repos
    )


def test_agents_prompt_archive_dirty_state_has_single_agents_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    plans = tmp_path / "plans"
    agents = tmp_path / "agents"
    for repo in (main, plans, agents):
        init_git_repo(repo)
    prompt = agents / "prompts" / "202608" / "test_prompt.md"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("# Test prompt\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    _use_sdd_store(monkeypatch, _sidecar_store(plans=plans, agents=agents))
    _resolve_agents_prompt_archive_to(monkeypatch, agents)

    dirty_state = collect_dirty_state(str(main), artifact_root=tmp_path / "artifacts")

    agents_path = finalizer_git.normalize_path(str(agents))
    agents_entries = [repo for repo in dirty_state.repos if repo.path == agents_path]
    assert [(repo.name, repo.changed_files, repo.kind) for repo in agents_entries] == [
        ("agents prompt archive", ("prompts/202608/test_prompt.md",), "sdd")
    ]


def _dirty_state(repo: Path, changed_files: tuple[str, ...]) -> DirtyState:
    return DirtyState(
        project_dir=finalizer_git.normalize_path(str(repo)),
        repos=(
            DirtyRepo(
                name="agents",
                path=finalizer_git.normalize_path(str(repo)),
                changed_files=changed_files,
                kind="sdd",
            ),
        ),
        details="",
    )


def _clean_state(repo: Path) -> DirtyState:
    return DirtyState(
        project_dir=finalizer_git.normalize_path(str(repo)),
        repos=(),
        details="",
    )


def test_agents_sync_auto_commit_is_attributable_dirty_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "agents"
    init_git_repo(repo)
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",))
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    commit_all(repo, f"sync agents\n\nSASE_TYPE={AGENTS_SYNC_AUTO_COMMIT_TYPE}")

    assert (
        discarded_dirty_work_evidence(
            before,
            _clean_state(repo),
            fingerprint_before=fingerprint_before,
        )
        == ()
    )


def test_dirty_cleanup_without_head_advance_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "agents"
    init_git_repo(repo)
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",))
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    _run_git(repo, "checkout", "--", "README.md")

    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
    )

    assert [item.reason for item in evidence] == ["head_not_advanced"]


def test_foreign_agent_commit_without_agents_sync_type_still_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "agents"
    init_git_repo(repo)
    (repo / "README.md").write_text("dirty payload\n", encoding="utf-8")
    before = _dirty_state(repo, ("README.md",))
    fingerprint_before = progress_fingerprint(before)
    monkeypatch.setenv("SASE_AGENT_NAME", "current-agent")

    commit_all(repo, "commit dirty payload\n\nSASE_AGENT=other-agent")

    evidence = discarded_dirty_work_evidence(
        before,
        _clean_state(repo),
        fingerprint_before=fingerprint_before,
    )

    assert [item.reason for item in evidence] == ["missing_agent_provenance"]
