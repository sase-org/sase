"""Tests for durable artifact-link publication retry state."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import sase.sdd._artifact_link_publication_retry as retry_mod
import sase.sdd._artifact_link_publication_retry_support as retry_support
from sase.linked_repos import hidden_sidecar_clone_dir
from sase.sdd._artifact_link_commit import commit_artifact_link_indexes
from sase.sdd._artifact_link_commit import _ensure_artifact_link_commit_published
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


def test_retry_sweep_reports_missing_upstream_without_worker_mutation(
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
    git(["branch", "--unset-upstream"], hidden_plans)
    monkeypatch.setattr(
        retry_mod,
        "_run_publication_worker",
        lambda *_args, **_kwargs: pytest.fail("missing upstream entered worker"),
    )

    report = sweep_artifact_link_publication_retries(
        roots,
        now=3_700.0,
        deadline=time.monotonic() + 60.0,
        worker_lock_wait=1.0,
    )

    assert report.attempted == 0
    assert report.failed == 1
    assert any("no tracking upstream" in item for item in report.diagnostics)


def test_retry_sweep_defers_dirty_unpublished_root_without_worker_mutation(
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
    (hidden_plans / "untracked.txt").write_text("preserve\n", encoding="utf-8")
    monkeypatch.setattr(
        retry_mod,
        "_run_publication_worker",
        lambda *_args, **_kwargs: pytest.fail("dirty root entered worker"),
    )

    report = sweep_artifact_link_publication_retries(
        roots,
        now=3_700.0,
        deadline=time.monotonic() + 60.0,
        worker_lock_wait=1.0,
    )

    assert report.attempted == 0
    assert report.deferred == 1
    assert report.failed == 0
    assert any(
        "uncommitted or untracked changes" in item for item in report.diagnostics
    )
    state = json.loads(
        (
            tmp_path
            / "state"
            / "projects"
            / _PROJECT_KEY
            / "artifact_link_publications.json"
        ).read_text(encoding="utf-8")
    )
    records = state["records"]
    assert len(records) == 1
    assert (
        "uncommitted or untracked changes" in next(iter(records.values()))["last_error"]
    )
    assert (hidden_plans / "untracked.txt").read_text(encoding="utf-8") == "preserve\n"


def test_inline_publication_reports_missing_tracking_upstream(
    tmp_path: Path,
) -> None:
    plans_remote = _seeded_remote(tmp_path, "plans")
    plans = tmp_path / "plans"
    clone(plans_remote, plans)
    _write_index(plans)
    commit_all(plans, "local artifact-link commit")
    git(["branch", "--unset-upstream"], plans)

    error = _ensure_artifact_link_commit_published(
        plans,
        description="artifact-link mutation",
    )

    assert error is not None
    assert "was committed locally but NOT published" in error
    assert "sidecar repository has no tracking upstream" in error
    assert "push -u <remote> HEAD" in error


def test_retry_git_probe_timeout_is_clipped_to_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = [100.0]
    captured_timeouts: list[float] = []
    monkeypatch.setattr(retry_support.time, "monotonic", lambda: now[0])

    def _run(args: list[str], **kwargs: object):
        captured_timeouts.append(float(kwargs["timeout"]))
        return retry_support.subprocess.CompletedProcess(
            args,
            returncode=0,
            stdout="abc123\n",
            stderr="",
        )

    monkeypatch.setattr(retry_support.subprocess, "run", _run)

    assert (
        retry_support._git_text(tmp_path, ["rev-parse", "HEAD"], deadline=103.25)
        == "abc123"
    )
    assert captured_timeouts == [3.25]


def test_retry_roots_rotate_after_deadline_consuming_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "state"))
    roots = (
        retry_mod.MachineArtifactLinkRoot(
            project_key=_PROJECT_KEY,
            role="plans",
            repo_root=tmp_path / "plans",
            remote_url="plans.git",
        ),
        retry_mod.MachineArtifactLinkRoot(
            project_key=_PROJECT_KEY,
            role="research",
            repo_root=tmp_path / "research",
            remote_url="research.git",
        ),
    )
    now = [0.0]
    seen: list[str] = []
    monkeypatch.setattr(retry_support.time, "monotonic", lambda: now[0])

    def _consume_budget(root, **_kwargs: object) -> None:
        seen.append(root.role)
        now[0] = 101.0

    monkeypatch.setattr(retry_mod, "_sweep_root", _consume_budget)

    report = sweep_artifact_link_publication_retries(roots, deadline=100.0)

    assert seen == ["plans"]
    assert report.deferred == 1

    now[0] = 0.0
    seen.clear()

    def _record_role(root, **_kwargs: object) -> None:
        seen.append(root.role)

    monkeypatch.setattr(retry_mod, "_sweep_root", _record_role)

    sweep_artifact_link_publication_retries(roots, deadline=100.0)

    assert seen == ["research", "plans"]
