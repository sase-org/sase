"""Coverage for cross-source dedupe of dirty repos in the commit finalizer.

A sidecar reachable through more than one discovery source — e.g. both a
configured sibling/linked repo and an SDD sidecar target — used to be
enumerated twice in ``DirtyState.repos``, duplicating finalizer prompt
instructions and failure-message lines. ``collect_dirty_state`` now dedupes
by normalized path, keeping the most specific ``kind``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.linked_repos import LINKED_REPOS_JSON_ENV
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.sdd.store import SDD_STORAGE_SIDECAR_REPOS, SddStore

from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    mark_opened_external,
    set_agent_env,
    set_clean_main,
)


def _use_sdd_store(monkeypatch: pytest.MonkeyPatch, store: SddStore) -> None:
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)


def test_repo_reachable_as_both_sibling_and_sdd_sidecar_appears_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    plans = tmp_path / "plans"
    shared = tmp_path / "shared-sidecar"
    for repo in (main, plans, shared):
        init_git_repo(repo)
    (shared / "notes.md").write_text("dirty\n", encoding="utf-8")
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        LINKED_REPOS_JSON_ENV,
        json.dumps([{"name": "shared", "workspace_dir": str(shared)}]),
    )
    _use_sdd_store(
        monkeypatch,
        SddStore(
            storage=SDD_STORAGE_SIDECAR_REPOS,
            sdd_dir=plans,
            repo_root=plans,
            sidecar_dirs={"research": shared},
            sidecar_remote_urls={
                "research": "git@example.invalid:sase/research.git",
            },
        ),
    )

    dirty_state = collect_dirty_state(str(main), artifact_root=tmp_path / "artifacts")

    assert [
        (repo.kind, repo.name, repo.path, repo.changed_files)
        for repo in dirty_state.repos
    ] == [
        (
            "sdd",
            "research",
            finalizer_git.normalize_path(str(shared)),
            ("notes.md",),
        )
    ]
    assert dirty_state.details.count("SDD sidecar repo research") == 1


def test_repo_reachable_as_both_external_and_sdd_sidecar_prefers_sdd_kind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    plans = tmp_path / "plans"
    shared = tmp_path / "shared-external"
    for repo in (main, plans, shared):
        init_git_repo(repo)
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    artifacts_dir = tmp_path / "artifacts"
    mark_opened_external(monkeypatch, artifacts_dir, "shared", shared)
    (shared / "notes.md").write_text("dirty\n", encoding="utf-8")
    _use_sdd_store(
        monkeypatch,
        SddStore(
            storage=SDD_STORAGE_SIDECAR_REPOS,
            sdd_dir=plans,
            repo_root=plans,
            sidecar_dirs={"research": shared},
            sidecar_remote_urls={
                "research": "git@example.invalid:sase/research.git",
            },
        ),
    )

    dirty_state = collect_dirty_state(str(main), artifact_root=artifacts_dir)

    assert [(repo.kind, repo.path) for repo in dirty_state.repos] == [
        ("sdd", finalizer_git.normalize_path(str(shared))),
    ]
