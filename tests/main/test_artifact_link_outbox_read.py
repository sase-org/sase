"""Tests for publishing outbox events produced by artifact reads."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_cli.read import handle_read
from sase.sdd._artifact_link_outbox_io import read_artifact_link_outbox_entries
from sase.sdd.artifact_link_outbox import drain_artifact_link_outbox
from sase.sdd.artifact_link_release_evidence import (
    record_artifact_link_release_evidence,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_link_outbox_helpers import (
    _commit_count,
    _head_files,
    _init_plans_repo,
    _patch_read_context,
    _read_args,
    _run_git,
)
from tests.sdd._artifact_link_store_helpers import allow_machine_sidecar_writes


def test_read_records_no_dirty_state_and_drain_publishes_once_evidence_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare read must never dirty the sidecar; a real change publishes it."""
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    doc = _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    _patch_read_context(monkeypatch, doc=doc, store=store, run_id="run-1")
    before = _commit_count(repo)

    assert handle_read(_read_args()) == 0
    assert handle_read(_read_args()) == 0
    assert len(read_artifact_link_outbox_entries("gh_sase-org__sase")) == 2
    pending = tuple(
        entry.event
        for entry in read_artifact_link_outbox_entries("gh_sase-org__sase")
        if entry.event is not None
    )
    assert len(pending) == 2
    operation_ids = {str(event["operation_id"]) for event in pending}
    assert len(operation_ids) == 2
    assert all(
        len(str(event["operation_id"])) == 32
        and all(char in "0123456789abcdef" for char in str(event["operation_id"]))
        for event in pending
    )
    assert _commit_count(repo) == before
    assert not list((repo / "links").rglob("*"))
    assert _run_git(repo, "status", "--porcelain", "--untracked-files=all") == ""

    unqualified = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert unqualified.drained == 0
    assert unqualified.retained == 2
    assert unqualified.committed is False
    assert len(read_artifact_link_outbox_entries("gh_sase-org__sase")) == 2

    record_artifact_link_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=(str(repo),),
    )

    report = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.drained == 2
    assert report.committed is True
    assert _commit_count(repo) == before + 1
    assert all(
        path == ".gitignore" or path.startswith("link-events/v1/")
        for path in _head_files(repo)
    )
    assert read_artifact_link_outbox_entries("gh_sase-org__sase") == ()
    assert not list((repo / "links").rglob("*"))
    [row] = store.load_aggregate()["rows"]
    assert row["uses"] == 2
    assert _run_git(repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_drain_publishes_event_objects_without_legacy_indexes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    doc = _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    _patch_read_context(monkeypatch, doc=doc, store=store, run_id="run-1")
    before = _commit_count(repo)
    assert handle_read(_read_args()) == 0
    assert handle_read(_read_args()) == 0
    record_artifact_link_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=(str(repo),),
    )

    report = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.drained == 2
    assert report.committed is True
    assert len(report.event_paths) == 2
    assert all(
        path.relative_to(repo).parts[:2] == ("link-events", "v1")
        for path in report.event_paths
    )
    assert not list((repo / "links").rglob("*"))
    assert _commit_count(repo) == before + 1
    assert read_artifact_link_outbox_entries("gh_sase-org__sase") == ()
    [row] = store.load_aggregate()["rows"]
    assert row["uses"] == 2
    assert _run_git(repo, "status", "--porcelain", "--untracked-files=all") == ""
