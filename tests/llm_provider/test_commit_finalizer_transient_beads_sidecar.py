"""Transient bead-sidecar sync coverage for dirty discovery.

A bead-sidecar checkout reachable through both a configured sibling target
and an SDD sidecar target must be scanned once per collection and always
classified as ``sdd``. Scanning it twice (once as sibling, once as sdd)
lets a sync/rebase between the two status calls expose the same checkout
as ``sibling:beads`` on one scan and ``sdd:beads`` on another, which both
misses the proven ``issues.jsonl`` reprojection auto-commit (it only owns
``sdd`` repos) and fails an otherwise valid declaration.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from sase.bead.model import IssueType, PhaseSize
from sase.core import bead_mutation_facade as rust_beads
from sase.linked_repos import LINKED_REPOS_JSON_ENV
from sase.llm_provider import commit_finalizer_git as finalizer_git
from sase.llm_provider import commit_finalizer_git_autocommit as finalizer_autocommit
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_state._dirty_repos import (
    known_sdd_sidecar_paths,
)
from sase.sdd.store import SDD_STORAGE_SIDECAR_REPOS, SddStore

from ._commit_finalizer_sibling_helpers import (
    init_git_repo,
    set_agent_env,
    set_clean_main,
)


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True)


def _use_sdd_store(monkeypatch: pytest.MonkeyPatch, store: SddStore) -> None:
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)


def test_sibling_sdd_overlap_scanned_once_as_sdd(
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

    import sase.llm_provider.commit_finalizer_state._dirty_repos as dirty_repos

    real_git_changed_files = dirty_repos.git_changed_files
    calls: dict[str, int] = {}

    def counting(repo_dir: str) -> list[str]:
        key = finalizer_git.normalize_path(repo_dir)
        calls[key] = calls.get(key, 0) + 1
        return real_git_changed_files(repo_dir)

    monkeypatch.setattr(dirty_repos, "git_changed_files", counting)

    dirty_state = collect_dirty_state(str(main), artifact_root=tmp_path / "artifacts")

    shared_key = finalizer_git.normalize_path(str(shared))
    assert calls.get(shared_key) == 1
    assert [(repo.kind, repo.name) for repo in dirty_state.repos] == [
        ("sdd", "research")
    ]


def test_known_sdd_paths_classify_sibling_overlap_as_sdd(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    plans = tmp_path / "plans"
    shared = tmp_path / "shared-sidecar"
    for repo in (main, plans, shared):
        init_git_repo(repo)
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

    known = known_sdd_sidecar_paths(str(main))

    assert known[finalizer_git.normalize_path(str(shared))] == "research"


def _create_beads_repo_with_dirty_projection(tmp_path: Path) -> Path:
    root = tmp_path / "state"
    root.mkdir()
    rust_beads.init_store(root, "beads", issue_prefix="beads")
    beads = root / "beads"
    rust_beads.create(
        beads,
        title="One",
        issue_type=IssueType.TASK,
        size=PhaseSize.SMALL,
        task_type="bug",
        created_by="test",
    )
    correct = (beads / "issues.jsonl").read_bytes()
    stale = correct.replace(b'"title":"One"', b'"title":"Stale"')
    assert stale != correct
    subprocess.run(["git", "init", "-q"], cwd=beads, check=True)
    _run_git(beads, "config", "user.name", "SASE Test")
    _run_git(beads, "config", "user.email", "sase-test@example.invalid")
    (beads / "issues.jsonl").write_bytes(stale)
    _run_git(beads, "add", ".")
    _run_git(beads, "commit", "-q", "-m", "stale projection")
    (beads / "issues.jsonl").write_bytes(correct)
    return beads


def test_proven_reprojection_overlap_stays_sdd_and_auto_committable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main = tmp_path / "sase_10"
    plans = tmp_path / "plans"
    main.mkdir()
    plans.mkdir()
    beads = _create_beads_repo_with_dirty_projection(tmp_path)
    set_agent_env(monkeypatch, main)
    set_clean_main(monkeypatch)
    monkeypatch.setenv(
        LINKED_REPOS_JSON_ENV,
        json.dumps([{"name": "beads", "workspace_dir": str(beads)}]),
    )
    store = SddStore(
        storage="sidecar_repos",
        sdd_dir=plans,
        repo_root=plans,
        beads_dir=beads,
    )
    monkeypatch.setattr("sase.sdd.store.resolve_sdd_store", lambda *_args: store)

    dirty_state = collect_dirty_state(str(main), artifact_root=tmp_path / "artifacts")

    assert [(repo.kind, repo.name) for repo in dirty_state.repos] == [("sdd", "beads")]
    candidates = finalizer_autocommit.sdd_bead_reprojection_auto_commit_candidates(
        dirty_state
    )
    assert len(candidates) == 1
    assert candidates[0].repo_dir == finalizer_git.normalize_path(str(beads))
