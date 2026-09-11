"""Tests for artifact-link outbox drain eligibility."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.artifact_cli.read import handle_read
from sase.sdd._artifact_link_outbox_io import read_artifact_link_outbox_entries
from sase.sdd.artifact_link_outbox import (
    append_artifact_link_outbox_entry,
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_event_publisher import (
    artifact_link_alias_producer_id,
    artifact_link_machine_run_id,
    artifact_link_stable_fact_created_at,
    canonical_event,
    stable_artifact_link_operation_id,
)
from sase.sdd.artifact_link_release_evidence import (
    record_artifact_link_release_evidence,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_link_outbox_helpers import (
    _commit_count,
    _init_plans_repo,
    _patch_read_context,
    _read_args,
    _run_git,
)
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


def test_drain_publishes_machine_alias_but_retains_unreleased_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    producer = artifact_link_alias_producer_id()
    append_artifact_link_outbox_event(
        project_key=store.project_key,
        agent_name=producer,
        run_id=artifact_link_machine_run_id(),
        event=canonical_event(
            {
                "schema_version": 1,
                "project_key": store.project_key,
                "operation_id": stable_artifact_link_operation_id(
                    "artifact-link-alias",
                    store.project_key,
                    "plan:old.md",
                    "plan:new.md",
                ),
                "created_by": producer,
                "origin": "migrated",
                "created_at": artifact_link_stable_fact_created_at(),
                "kind": {
                    "type": "alias",
                    "old_ref": "plan:old.md",
                    "new_ref": "plan:new.md",
                },
            }
        ),
    )
    append_artifact_link_outbox_entry(
        project_key=store.project_key,
        agent_name="reader",
        run_id="run-1",
        row=_row(source="agent:reader", target="plan:doc.md", origin="read"),
    )

    report = drain_artifact_link_outbox(
        store=store,
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.drained == 1
    assert len(report.event_paths) == 1
    [remaining] = read_artifact_link_outbox_entries(store.project_key)
    assert remaining.agent_name == "reader"


def test_drain_run_without_release_evidence_leaves_entry_queued_and_uncommitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    repo = tmp_path / "plans"
    doc = _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    _patch_read_context(monkeypatch, doc=doc, store=store, run_id="run-1")
    before = _commit_count(repo)

    assert handle_read(_read_args()) == 0
    report = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )

    assert report.drained == 0
    assert report.retained == 1
    assert report.committed is False
    assert _commit_count(repo) == before
    assert len(read_artifact_link_outbox_entries("gh_sase-org__sase")) == 1
    assert not list((repo / "links").rglob("*"))
    assert _run_git(repo, "status", "--porcelain", "--untracked-files=all") == ""


def test_repeated_drain_after_partial_failure_does_not_double_count_uses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retried drain over the same queued reads must not double-count."""
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    doc = _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    _patch_read_context(monkeypatch, doc=doc, store=store, run_id="run-1")
    assert handle_read(_read_args()) == 0
    assert handle_read(_read_args()) == 0
    record_artifact_link_release_evidence(
        project_key="gh_sase-org__sase",
        run_id="run-1",
        agent_id="reader",
        qualifying_repo_ids=(str(repo),),
    )

    first = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert first.drained == 2
    assert first.committed is True
    [row] = store.load_aggregate()["rows"]
    assert row["uses"] == 2

    assert handle_read(_read_args()) == 0
    second = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert second.drained == 1
    assert second.committed is True
    [row] = store.load_aggregate()["rows"]
    assert row["uses"] == 3

    idle = drain_artifact_link_outbox(
        store=store,
        agent_name="reader",
        drop_stale_terminal=False,
        push_after_commit=False,
    )
    assert idle.queued == 0
    [row] = store.load_aggregate()["rows"]
    assert row["uses"] == 3


def test_drain_does_not_release_a_different_run_of_the_same_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-named agent's other run must not borrow this run's evidence."""
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    append_artifact_link_outbox_entry(
        project_key="gh_sase-org__sase",
        agent_name="reader",
        run_id="run-1",
        row=_row(
            source="agent:reader",
            relation="read",
            target="plan:doc.md",
            origin="read",
        ),
    )
    append_artifact_link_outbox_entry(
        project_key="gh_sase-org__sase",
        agent_name="reader",
        run_id="run-2",
        row=_row(
            source="agent:reader",
            relation="read",
            target="plan:other.md",
            origin="read",
        ),
    )
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

    assert report.drained == 1
    assert report.retained == 1
    remaining = read_artifact_link_outbox_entries("gh_sase-org__sase")
    assert len(remaining) == 1
    assert remaining[0].run_id == "run-2"


def test_drain_allows_trusted_machine_derived_events_without_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.bead.model import IssueType
    from sase.bead.project import BEADS_DIRNAME_ROOT, BeadProject

    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    beads_repo = tmp_path / "beads"
    _init_plans_repo(repo)
    _init_plans_repo(beads_repo)
    with BeadProject.init(beads_repo, beads_dirname=BEADS_DIRNAME_ROOT) as project:
        issue = project.create("Linked plan", IssueType.PLAN)
        store = ArtifactLinkStore(
            project_key="gh_sase-org__sase",
            sidecar_roots={"plan": repo},
            beads_dir=project.beads_dir,
        )
        append_artifact_link_outbox_entry(
            project_key="gh_sase-org__sase",
            agent_name="sase",
            run_id="machine",
            row=_row(
                source="plan:doc.md",
                relation="implements",
                target=f"bead:{issue.id}",
                origin="derived",
                created_by="sase",
            ),
        )

        report = drain_artifact_link_outbox(
            store=store,
            agent_name="sase",
            drop_stale_terminal=False,
            push_after_commit=False,
        )

        assert report.drained == 1
        assert len(report.event_paths) == 1
        assert not list((repo / "links").rglob("*"))
        assert read_artifact_link_outbox_entries("gh_sase-org__sase") == ()
