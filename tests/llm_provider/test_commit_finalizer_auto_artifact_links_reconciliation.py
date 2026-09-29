"""Reconciliation dirt behavior for implicit artifact-link index writes."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from sase.finalizers.reconciliation import prepare_commit_dirty_state
from sase.llm_provider.commit_finalizer_baseline import capture_dirty_baseline
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.sdd._artifact_link_outbox_io import read_artifact_link_outbox_entries
from sase.sdd.artifact_link_outbox import append_artifact_link_outbox_entry
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home

from ._commit_finalizer_artifact_links_helpers import (
    commit_all,
    create_primary,
    create_sidecar,
    read_row,
    record_reads,
    run_git,
    sdd_store,
    set_finalizer_env,
)


def _head_files(repo: Path) -> set[str]:
    names = run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    return {line for line in names.splitlines() if line.strip()}


def _prepare(artifacts_dir: Path):
    return prepare_commit_dirty_state(
        resolve_finalizer_project_dir(),
        artifacts_dir,
    )


def test_two_implicit_plan_reads_produce_no_dirt_or_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reads recorded through the real outbox path create no VCS dirt.

    This reverses the module's original premise: a bare read used to write
    its link-index row straight to the sidecar, which the finalizer then
    auto-committed with no model declaration at all. Reads now only queue a
    pending row in the read-link outbox (see
    ``sase.sdd.artifact_link_outbox``), so two implicit reads and no other
    edits must leave the sidecar completely clean.
    """
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
    plans = create_sidecar(tmp_path, "plans")
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: sdd_store(plans)
    )
    for target in ("plan:202608/one.md", "plan:202608/two.md"):
        append_artifact_link_outbox_entry(
            project_key="gh_sase-org__sase",
            agent_name="alice.athena.09l",
            run_id="260821_120000",
            row=read_row(target),
        )
    assert not list((plans / "links").rglob("*"))
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is False
    assert state.artifact_link_publication_error is None
    assert state.dirty_state.is_clean
    assert run_git(plans, "status", "--porcelain", "--untracked-files=all") == ""
    assert int(run_git(plans, "rev-list", "--count", "HEAD").strip()) == 1
    assert len(read_artifact_link_outbox_entries("gh_sase-org__sase")) == 2

    second = _prepare(artifacts)
    assert second.artifact_links_auto_committed is False
    assert int(run_git(plans, "rev-list", "--count", "HEAD").strip()) == 1


def test_mixed_unrelated_dirt_is_left_for_the_declaration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
    plans = create_sidecar(tmp_path, "plans")
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: sdd_store(plans)
    )
    record_reads(plans, "plan:202608/one.md")
    (plans / "notes.md").write_text("unrelated agent edit\n", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is False
    remaining = [
        path for repo in state.dirty_state.repos for path in repo.changed_files
    ]
    assert any(path.endswith("notes.md") for path in remaining)
    assert any(path.endswith("links/202608/one.md.json") for path in remaining)
    assert "links/202608/one.md.json" not in _head_files(plans)


def test_pre_existing_dirty_index_is_not_auto_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
    plans = create_sidecar(tmp_path, "plans")
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: sdd_store(plans)
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    store = record_reads(plans, "plan:202608/preexisting.md")
    capture_dirty_baseline(str(main), str(artifacts))
    store.upsert_row(read_row("plan:202608/new.md"))

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is False
    files = _head_files(plans)
    assert "links/202608/new.md.json" not in files
    assert "links/202608/preexisting.md.json" not in files
    status = run_git(plans, "status", "--porcelain", "--untracked-files=all")
    assert "preexisting.md.json" in status
    assert "new.md.json" in status


def test_malformed_candidates_remain_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
    plans = create_sidecar(tmp_path, "plans")
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: sdd_store(plans)
    )
    record_reads(plans, "plan:202608/one.md")
    broken = plans / "links" / "202608" / "broken.md.json"
    broken.write_text("{not-json", encoding="utf-8")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is False
    remaining = [
        path for repo in state.dirty_state.repos for path in repo.changed_files
    ]
    assert any(path.endswith("broken.md.json") for path in remaining)
    assert any(path.endswith("one.md.json") for path in remaining)


def test_multiple_sidecars_commit_once_each(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
    plans = create_sidecar(tmp_path, "plans")
    research = create_sidecar(tmp_path, "research")
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store",
        lambda *_args: sdd_store(plans, research),
    )
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": plans, "research": research},
    )
    store.upsert_row(read_row("plan:202608/one.md"))
    store.upsert_row(
        {
            **read_row("research:202608/source.md"),
            "target_ref": "research:202608/source.md",
        }
    )
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is False
    assert not state.dirty_state.is_clean
    assert "links/202608/one.md.json" not in _head_files(plans)
    assert "links/202608/source.md.json" not in _head_files(research)


def test_publication_failure_is_recoverable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    main = create_primary(tmp_path)
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
    commit_all(plans)
    run_git(plans, "push", "-q", "-u", "origin", "HEAD:main")
    run_git(plans, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    set_finalizer_env(monkeypatch, main)
    monkeypatch.setattr(
        "sase.sdd.store.resolve_sdd_store", lambda *_args: sdd_store(plans)
    )
    record_reads(plans, "plan:202608/one.md")
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    state = _prepare(artifacts)

    assert state.artifact_links_auto_committed is False
    assert state.artifact_link_publication_error is None
    assert "chore(artifact-links): persist link indexes" not in run_git(
        plans, "log", "-1", "--pretty=%s"
    )
