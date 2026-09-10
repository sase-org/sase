"""Tests for durable artifact-link read outbox replay."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

import pytest

from sase.artifact_cli.read import handle_read
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.sdd._artifact_link_ignore import ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN
from sase.sdd._artifact_link_outbox_io import (
    convert_legacy_artifact_link_outbox_entries,
    read_artifact_link_outbox_entries,
)
from sase.sdd.artifact_link_outbox import (
    ARTIFACT_LINK_OUTBOX_FILENAME,
    append_artifact_link_outbox_entry,
    append_artifact_link_outbox_event,
    drain_artifact_link_outbox,
)
from sase.sdd.artifact_link_event_publisher import (
    artifact_link_alias_producer_id,
    artifact_link_machine_run_id,
    artifact_link_stable_fact_created_at,
    canonical_event,
    observation_or_put_event_from_row,
    stable_artifact_link_operation_id,
)
from sase.sdd.artifact_link_release_evidence import (
    record_artifact_link_release_evidence,
)
from sase.sdd.artifact_link_store import ArtifactLinkStore
from tests._conftest_environment import redirect_sase_home
from tests.main.artifact_cli_reference_helpers import resolved_reference
from tests.sdd._artifact_link_store_helpers import _row, allow_machine_sidecar_writes


def _run_git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _init_plans_repo(repo: Path) -> Path:
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "SASE Test"], cwd=repo, check=True)
    subprocess.run(
        ["git", "config", "user.email", "sase-test@example.invalid"],
        cwd=repo,
        check=True,
    )
    (repo / ".gitignore").write_text(
        f"{ARTIFACT_LINK_LOCK_GITIGNORE_PATTERN}\n",
        encoding="utf-8",
    )
    doc = repo / "doc.md"
    doc.write_text("# Doc\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-q", "-m", "initial")
    return doc


def _commit_count(repo: Path) -> int:
    return int(_run_git(repo, "rev-list", "--count", "HEAD").strip())


def _head_files(repo: Path) -> set[str]:
    names = _run_git(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
    return {line for line in names.splitlines() if line.strip()}


def _read_args() -> argparse.Namespace:
    return argparse.Namespace(
        reference="plan:doc.md",
        reason="Need the design of record",
        format="markdown",
        lines=None,
    )


def _patch_read_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    doc: Path,
    store: ArtifactLinkStore,
    run_id: str = "run-1",
) -> None:
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "reader")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", run_id)
    monkeypatch.setattr(
        "sase.config.require_agent_owner_identity",
        lambda: AgentOwnerIdentity("alice", "athena"),
    )
    plan_result = resolved_reference(doc, reference="plan:doc.md")
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_cli_reference",
        lambda _value: plan_result,
    )
    monkeypatch.setattr(
        "sase.artifact_cli.read.resolve_artifact_link_store",
        lambda: store,
    )


def _outbox_lines(home: Path, project_key: str) -> list[dict[str, object]]:
    path = home / "projects" / project_key / ARTIFACT_LINK_OUTBOX_FILENAME
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_outbox_rejects_reused_operation_id_with_different_event_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    project_key = "gh_sase-org__sase"
    operation_id = "a" * 32
    first = observation_or_put_event_from_row(
        _row(source="agent:reader", target="plan:doc.md", origin="read"),
        project_key=project_key,
        operation_id=operation_id,
    )
    second = observation_or_put_event_from_row(
        _row(source="agent:reader", target="plan:other.md", origin="read"),
        project_key=project_key,
        operation_id=operation_id,
    )

    append_artifact_link_outbox_event(
        project_key=project_key,
        agent_name="reader",
        run_id="run-1",
        event=first,
    )
    with pytest.raises(RuntimeError, match="reused for different event bytes"):
        append_artifact_link_outbox_event(
            project_key=project_key,
            agent_name="reader",
            run_id="run-1",
            event=second,
        )

    assert len(_outbox_lines(home, project_key)) == 1


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

    # No release evidence yet, so this run's own reads stay queued.
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

    # The run then authors a real change and its commit is verified,
    # recording this run's own release evidence.
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

    # A third read is queued for the same run after the first drain landed.
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

    # Draining again with nothing new queued is a safe no-op.
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


def test_new_outbox_entries_persist_canonical_events(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)

    entry = append_artifact_link_outbox_entry(
        project_key="gh_sase-org__sase",
        agent_name="reader",
        run_id="run-1",
        row=_row(
            source="agent:reader",
            relation="read",
            target="plan:doc.md",
            origin="read",
            created_by="reader",
            created_at="2026-09-09T12:00:00Z",
        ),
        now=100.0,
    )

    assert len(entry.id) == 32
    assert entry.event is not None
    assert entry.event["operation_id"] == entry.id
    assert entry.row is not None
    assert entry.row["uses"] == 1
    [stored] = _outbox_lines(home, "gh_sase-org__sase")
    assert "event" in stored
    assert "row" not in stored
    assert stored["id"] == entry.id
    assert stored["event"] == entry.event


def test_legacy_row_only_outbox_entries_convert_before_drain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = tmp_path / ".sase"
    redirect_sase_home(monkeypatch, home)
    allow_machine_sidecar_writes(monkeypatch)
    repo = tmp_path / "plans"
    _init_plans_repo(repo)
    store = ArtifactLinkStore(
        project_key="gh_sase-org__sase",
        sidecar_roots={"plan": repo},
    )
    row = _row(
        source="agent:reader",
        relation="read",
        target="plan:doc.md",
        origin="read",
    )
    path = home / "projects" / "gh_sase-org__sase" / ARTIFACT_LINK_OUTBOX_FILENAME
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "legacy-row",
                "created_at": 100.0,
                "project_key": "gh_sase-org__sase",
                "agent_name": "reader",
                "run_id": "run-1",
                "row": row,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    converted = convert_legacy_artifact_link_outbox_entries("gh_sase-org__sase")

    assert converted.converted == 1
    assert converted.covered == 0
    assert converted.invalid == ()
    [converted_entry] = read_artifact_link_outbox_entries("gh_sase-org__sase")
    assert converted_entry.event is not None
    assert converted_entry.created_at == 100.0
    assert converted_entry.agent_name == "reader"
    assert converted_entry.run_id == "run-1"
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
    assert report.committed is True
    assert len(report.event_paths) == 1
    assert not list((repo / "links").rglob("*"))
    [indexed] = store.load_aggregate()["rows"]
    assert indexed["uses"] == 1
    assert read_artifact_link_outbox_entries("gh_sase-org__sase") == ()


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
