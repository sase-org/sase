"""Tests for durable artifact-link publication retry state."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from sase.linked_repos import hidden_sidecar_clone_dir
from sase.sdd._artifact_link_commit import commit_artifact_link_indexes
from sase.sdd._artifact_link_publication_retry import (
    register_artifact_link_publication_failure,
    sweep_artifact_link_publication_retries,
)
from sase.sdd._artifact_link_store_support import sidecar_index_path
from sase.sdd.artifact_link_store import machine_document_sidecar_roots
from sase.sdd.store import write_sdd_store_record
from tests.sdd_store._helpers import clone, commit_all, git, init_bare_repo

_PROJECT_KEY = "acme_widget"


def _seeded_remote(tmp_path: Path, role: str) -> Path:
    remote = tmp_path / f"{role}.git"
    seed = tmp_path / f"{role}-seed"
    init_bare_repo(remote)
    clone(remote, seed)
    (seed / "README.md").write_text(f"# {role}\n", encoding="utf-8")
    commit_all(seed, "seed")
    git(["push", "-u", "origin", "main"], seed)
    return remote


def _primary_with_sidecar(tmp_path: Path, *, role: str, remote: Path) -> Path:
    primary = tmp_path / "primary"
    primary.mkdir()
    write_sdd_store_record(
        primary,
        {
            "schema_version": 2,
            "storage": "sidecar_repos",
            "provider": "github",
            "sidecars": {
                role: {
                    "repo": f"acme/widget--{role}",
                    "remote_url": str(remote),
                }
            },
        },
    )
    return primary


def _write_index(repo: Path) -> Path:
    index = sidecar_index_path(repo, "plan:202609/retry.md")
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact_ref": "plan:202609/retry.md",
                "rows": [
                    {
                        "schema_version": 2,
                        "source_ref": "agent:planner.coder",
                        "relation": "read",
                        "target_ref": "plan:202609/retry.md",
                        "description": "records a retry fixture",
                        "origin": "read",
                        "created_by": "sase",
                        "created_at": "2026-09-06T00:00:00Z",
                        "uses": 1,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return index


def test_retry_sweep_publishes_previously_unpushed_hidden_sidecar_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    plans_remote = _seeded_remote(tmp_path, "plans")
    primary = _primary_with_sidecar(tmp_path, role="plans", remote=plans_remote)
    monkeypatch.setattr(
        "sase.bead.workspace.resolve_primary_workspace_for_project",
        lambda key: primary if key == _PROJECT_KEY else None,
    )

    roots, diagnostics = machine_document_sidecar_roots(_PROJECT_KEY, primary)
    assert diagnostics == ()
    assert len(roots) == 1
    hidden_plans = Path(hidden_sidecar_clone_dir(_PROJECT_KEY, "plans"))
    index = _write_index(hidden_plans)

    result = commit_artifact_link_indexes(
        [index],
        repo_roots=(hidden_plans,),
        mutation_origin="machine",
        push_after_commit=False,
        verify_publication=False,
    )
    assert result.committed is True

    local_head = git(["rev-parse", "HEAD"], hidden_plans).stdout.strip()
    remote_listing = git(["ls-remote", str(plans_remote), "main"], tmp_path).stdout
    assert local_head not in remote_listing

    registration = register_artifact_link_publication_failure(
        project_key=_PROJECT_KEY,
        role="plans",
        repo_root=hidden_plans,
        remote_url=str(plans_remote),
        error="simulated push failure",
        now=1_000.0,
    )
    assert registration.recorded is True
    assert (
        tmp_path
        / "state"
        / "projects"
        / _PROJECT_KEY
        / "artifact_link_publications.json"
    ).is_file()

    report = sweep_artifact_link_publication_retries(
        roots,
        now=3_700.0,
        deadline=time.monotonic() + 60.0,
        worker_lock_wait=1.0,
    )

    assert report.attempted == 1
    assert report.published == 1
    assert report.failed == 0
    remote_listing = git(["ls-remote", str(plans_remote), "main"], tmp_path).stdout
    assert local_head in remote_listing
